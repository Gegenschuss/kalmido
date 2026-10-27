#!/usr/bin/env python3
"""2.51.0 API tests, part A (agents in the office: drafts only, a person confirms), own container (start.sh).
Invented companies, people and figures only.
 - #1348: the agent's switch "May draft office documents" (off by default; only an admin of its office area sets it) and
   the area's privacy switch "Agents may read office data" (off by default): either off = 403; the scope office; reading
   services / clients (no purchase prices); a quotation draft WITHOUT a number, free positions / other prices / discounts
   marked, the marks kept on an unchanged save and gone on a changed or confirmed position; only its own drafts and only
   as drafts; never status, number, finalising, deleting; the chat card with link buttons; every request in the office
   log; another organisation's documents / clients 404 (tenant-matrix: office); a freelancer without organisation (personal office)
 - #1348: the event offer_accepted to the area's office agents
 - #1350: an invoice draft from an accepted quotation, a reminder draft over an open invoice, payment suggestions that
   an admin accepts (booked) or rejects (a member: 403)
usage: p251_a_api_test.py <datadir>   (P251_NOSTART=1: against a running instance on KALMIDO_TEST_PORT)"""
import os
import subprocess
import sys
import time

import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
import dbx as dbxm  # noqa: E402  # 2.355.0 D (#2846)


if not os.environ.get("P251_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do = sess("bob"), sess("carol"), sess("dora")
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo, Ca, Do):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
DORA = Do.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
O = "/api/office"
D = O + "/docs"
V = B + "/api/v1/office"
TODAY = testclock.today().isoformat()
A.get(B + O + "/settings")
A.put(B + O + "/settings", json={"company_fields": {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
                                                     "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
S1 = A.post(B + O + "/services", json={"name_de": "Kamera", "name_en": "Camera", "daily_rate": 800}).json()["id"]
S2 = A.post(B + O + "/services", json={"name_de": "Schnitt", "name_en": "Editing", "daily_rate": 600}).json()["id"]
CL = A.post(B + "/api/clients", json={"name": "Musterfirma GmbH", "address": "Weg 2\n10115 Berlin"}).json()["id"]
CL2 = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG"}).json()["id"]
LID = A.post(B + "/api/lists", json={"name": "Imagefilm Projekt"}).json()["id"]
Ca.get(B + O + "/settings")
FQ = Ca.post(B + D, json={"client_id": CL2, "project_title": "Fremdes Angebot"}).json()["id"]

# a personal agent of Alice working in Alpha (scopes read + office)
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "office"], "org_id": ORG})
check(r.status_code == 201, "setup: a personal agent " + r.text[:200])
AG, AGT = r.json()["id"], r.json()["token"]
AH = {**H, "Authorization": "Bearer " + AGT}


def ag(m, path, **kw):
    return requests.request(m, V + path, headers=AH, **kw)


# ---------------------------------------------------------------- #1348 the two switches
check(ag("GET", "").status_code == 403, "#1348: the agent's switch is off by default (403)")
j = A.get(B + f"{O}/agents/{AG}").json()
check(j.get("office_drafts") is False and j.get("can_set") is True and j.get("agents_read") is False, f"#1348: the switch state for the area's admin {j}")
check(Bo.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).status_code == 403, "#1348: a member may not switch it (403)")
check(Ca.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).status_code == 404 and Ca.get(B + f"{O}/agents/{AG}").status_code == 404,
      "#1348: another organisation does not reach the agent (404)")
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": "yes"}).status_code == 400, "#1348: only true / false")
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok, "#1348: the area's admin switches it on")
r = ag("GET", "")
check(r.status_code == 403 and "office settings" in r.text, "#1348: the privacy switch is off by default (403) " + r.text[:200])
check(A.get(B + O + "/settings").json()["settings"].get("agents_read") == 0, "#1348: agents_read off by default")
check(Bo.put(B + O + "/settings", json={"agents_read": 1}).status_code == 403, "#1348: a member may not switch the privacy switch")
check(A.put(B + O + "/settings", json={"agents_read": 1}).ok, "#1348: the admin switches the privacy switch on")
r = ag("GET", "")
check(r.ok and r.json()["area"]["id"] == ORG and r.json()["person_id"] == ALICE, "#1348: the office area of the agent " + r.text[:200])
r = ag("GET", "", params={"requested_by": CAROL})
check(r.status_code == 404, "#1348: a person the agent does not work with: 404 " + r.text[:200])

# ---------------------------------------------------------------- reading
r = ag("GET", "/services")
check(r.ok and {x["id"] for x in r.json()["data"]} == {S1, S2} and not any(k.startswith("cost") for x in r.json()["data"] for k in x),
      "#1348: services without purchase prices " + r.text[:200])
r = ag("GET", "/clients")
check(r.ok and [x["id"] for x in r.json()["data"]] == [CL], "#1348: only the area's clients " + r.text[:200])
check(ag("GET", "/texts").ok and ag("GET", "/contracts").ok, "#1348: text blocks and framework contracts")
check(ag("GET", f"/docs/{FQ}").status_code == 404, "#1348: a document of another organisation: 404")
check(ag("GET", "/nothing").status_code in (403, 404), "#1348: an unknown kind")

# ---------------------------------------------------------------- the draft
body = {"client_id": CL, "title": "Imagefilm 2027", "list_id": LID, "notify": True,
        "items": [{"service_id": S1, "qty": 3}, {"service_id": S1, "qty": 1, "price": 900},
                  {"text": "Fahrtkosten", "qty": 1, "unit": "flat", "price": 120}, {"service_id": S2, "qty": 2, "discount": 10}]}
check(ag("POST", "/offers", json={**body, "client_id": CL2}).status_code == 404, "#1348: a client of another organisation: 404")
check(ag("POST", "/offers", json=body).status_code == 404, "#1348: a project list the agent does not see: 404")
check(A.put(B + f"/api/lists/{LID}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the project list is shared with the agent")
FL = Ca.post(B + "/api/lists", json={"name": "Fremdes Projekt"}).json()["id"]
check(ag("POST", "/offers", json={**body, "list_id": FL}).status_code == 404, "#1348: a list of another organisation: 404")
check(ag("POST", "/offers", json={**body, "status": "sent"}).status_code == 400, "#1348: no status field")
r = ag("POST", "/offers", json=body)
check(r.status_code == 201, "#1348: a quotation draft " + r.text[:300])
Q = r.json()["doc"]
QID = Q["id"]
check(Q["status"] == "draft" and Q["number"] == "" and Q["agent_id"] == AG and Q["agent_name"] == "Office Bot" and Q["list_id"] == LID,
      f"#1348: a draft without a number, drafted by the agent {Q.get('number')!r} {Q.get('agent_id')}")
fl = [it["agent_flag"] for it in Q["items"]]
check(fl == ["", "price", "free", "discount:10"], f"#1348: the marks of the positions {fl}")
rates = [float(it["rate"]) for it in Q["items"]]
check(rates == [800.0, 900.0, 120.0, 540.0], f"#1348: catalogue price, own price, free price, discount off {rates}")
cm = r.json().get("chat_message_id")
msgs = A.get(B + f"/api/agents/{AG}/chat").json()
msgs = msgs.get("messages", msgs) if isinstance(msgs, dict) else msgs
card = [m for m in msgs if m.get("id") == cm]
check(card and [c.get("href") for c in card[0]["choices"]["choices"]] == [f"#office/offers/{QID}", f"/api/office/docs/{QID}/pdf?inline=1"],
      "#1348: the chat card with Open in the office + PDF preview")
r = requests.post(B + f"/api/v1/agent/chats/{ALICE}", headers=AH, json={"body": "x", "choices": [{"id": "a", "label": "A", "href": "#settings/agents"}]})
check(r.status_code == 400, "#1348: link buttons only to office documents, lists and the PDF preview " + str(r.status_code))
r = requests.post(B + f"/api/v1/agent/chats/{ALICE}", headers=AH, json={"body": "x", "choices": [{"id": "a", "label": "A", "href": "https://example.com/x"}]})
check(r.status_code == 400, "#1348: no outside address as a link button")
r = ag("GET", f"/docs/{QID}/pdf")
check(r.ok and r.content[:4] == b"%PDF", "#1348: the PDF preview of the draft")

# never status, number, finalising, deleting, other routes of the app
for m, path in (("POST", f"/api/office/docs/{QID}/status"), ("POST", f"/api/office/docs/{QID}/number"), ("POST", f"/api/office/docs/{QID}/finalize"),
                ("DELETE", f"/api/office/docs/{QID}"), ("POST", f"/api/office/docs/{QID}/send")):
    r = requests.request(m, B + path, headers=AH, json={"status": "sent"})
    check(r.status_code in (401, 403), f"#1348: an agent token never reaches {m} {path} ({r.status_code})")
for m, path in (("POST", f"/docs/{QID}/status"), ("DELETE", f"/offers/{QID}"), ("POST", f"/docs/{QID}/finalize")):
    r = ag(m, path, json={})
    check(r.status_code in (403, 404, 405), f"#1348: no v1 route {m} {path} ({r.status_code})")

# changing: own drafts only, only drafts; the marks
r = ag("PATCH", f"/offers/{QID}", json={"title": "Imagefilm 2027 (lang)"})
check(r.ok and r.json()["doc"]["project_title"] == "Imagefilm 2027 (lang)" and r.json()["doc"]["number"] == "", "#1348: the agent changes its draft")
check(ag("PATCH", f"/offers/{FQ}", json={"title": "x"}).status_code == 404, "#1348: another organisation's quotation: 404")
HQ = A.post(B + D, json={"client_id": CL, "project_title": "Von Hand"}).json()["id"]
check(ag("PATCH", f"/offers/{HQ}", json={"title": "x"}).status_code == 403, "#1348: a person's draft: 403")
its = A.get(B + f"{D}/{QID}").json()["items"]
keep = [{k: it[k] for k in ("id", "kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax")} for it in its]
A.put(B + f"{D}/{QID}/items", json={"items": keep})
fl = [it["agent_flag"] for it in A.get(B + f"{D}/{QID}").json()["items"]]
check(fl == ["", "price", "free", "discount:10"], f"#1348: an unchanged save keeps the marks {fl}")
its = A.get(B + f"{D}/{QID}").json()["items"]
keep = [{k: it[k] for k in ("id", "kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax")} for it in its]
keep[1]["confirm"] = True
keep[2]["rate"] = 150
A.put(B + f"{D}/{QID}/items", json={"items": keep})
fl = [it["agent_flag"] for it in A.get(B + f"{D}/{QID}").json()["items"]]
check(fl == ["", "", "", "discount:10"], f"#1348: confirmed / changed positions lose the mark {fl}")
log = A.get(B + O + "/log", params={"limit": 200}).json()["log"]
al = [x for x in log if x["action"] in ("agent_read", "agent_write")]
check(len(al) >= 8 and all(x["user_id"] == AG for x in al) and any(x["action"] == "agent_write" and x["doc_id"] == QID for x in al)
      and all(set(x["detail"]) <= {"agent", "for", "what"} for x in al), f"#1348: every agent request in the office log ({len(al)})")

# ---------------------------------------------------------------- offer_accepted + #1350
check(ag("POST", f"/offers/{QID}/invoice", json={}).status_code == 409, "#1350: no invoice from a quotation that is not accepted")
check(A.post(B + f"{D}/{QID}/status", json={"status": "sent"}).ok, "the person sends the quotation")
check(ag("PATCH", f"/offers/{QID}", json={"title": "x"}).status_code == 409, "#1348: a sent quotation is no draft any more (409)")
check(A.post(B + f"{D}/{QID}/status", json={"status": "accepted"}).ok, "the quotation is accepted")
ev = requests.get(B + "/api/v1/agent/events", headers=AH).json()
evs = [e for e in ev.get("events", ev.get("data", [])) if e["event"] == "offer_accepted"]
check(evs and evs[-1]["data"]["doc_id"] == QID and evs[-1]["data"]["list_id"] == LID and evs[-1]["data"]["client_id"] == CL,
      "#1348: the event offer_accepted " + str(evs)[:300])
r = ag("POST", f"/offers/{QID}/invoice", json={"notify": True})
check(r.status_code == 201 and r.json()["doc"]["kind"] == "invoice" and r.json()["doc"]["status"] == "draft" and r.json()["doc"]["agent_id"] == AG
      and not r.json()["doc"]["locked"], "#1350: an invoice draft from the accepted quotation " + r.text[:200])
INV = r.json()["doc"]["id"]
A.patch(B + f"{D}/{INV}", json={"recipient": {"name": "Musterfirma GmbH", "lines": ["Weg 2", "10115 Berlin"]}, "service_from": TODAY, "service_to": TODAY})
r = A.post(B + f"{D}/{INV}/finalize")
check(r.ok, "the person finalises the invoice " + r.text[:200])
r = ag("GET", "/docs", params={"kind": "invoice", "open": "1"})
check(r.ok and [x["id"] for x in r.json()["data"]] == [INV], "#1350: the open invoices " + r.text[:200])
dbxm.overdue(DATA, [INV])  # 2.355.0 D (#2846): reminders only for overdue invoices
r = ag("POST", "/reminders", json={"invoice_ids": [INV], "level": 1})
check(r.status_code == 201 and r.json()["doc"]["kind"] == "reminder" and r.json()["doc"]["status"] == "draft" and not r.json()["doc"]["locked"],
      "#1350: a reminder draft " + r.text[:200])
check(ag("POST", "/reminders", json={"invoice_ids": [FQ]}).status_code in (400, 404), "#1350: no reminder over another organisation's document")
# 2.223.2 B (#2862): an organisation's agent without an office group reaches only the quotes' scope (payment suggestions need one)
check(A.put(B + f"{O}/rights/people/{AG}", json={"groups": ["tpl:projects", "tpl:bookkeeping"]}).ok, "setup: the agent in Project management + Bookkeeping")
r = ag("POST", "/payment-suggestions", json={"invoice_id": INV, "amount": "100.00", "date": TODAY, "reference": "Ueberweisung Musterfirma", "confidence": "high"})
check(r.status_code == 201 and r.json()["state"] == "open", "#1350: a payment suggestion " + r.text[:200])
P1 = r.json()["id"]
P2 = ag("POST", "/payment-suggestions", json={"invoice_id": INV, "amount": "50", "date": TODAY}).json()["id"]
check(ag("POST", "/payment-suggestions", json={"invoice_id": HQ, "amount": "1"}).status_code == 409, "#1350: only on finalised open invoices")
check(ag("POST", "/payment-suggestions", json={"invoice_id": INV, "amount": "1", "confidence": "sure"}).status_code == 400, "#1350: confidence high / medium / low")
check(len(ag("GET", "/payment-suggestions").json()["data"]) == 2, "#1350: the agent lists its suggestions")
check(not A.get(B + f"{D}/{INV}/payments").json()["payments"], "#1350: nothing is booked by the suggestion")
j = Bo.get(B + O + "/pay-props").json()
check(len(j["items"]) == 2 and j["admin"] is False, "#1350: members see the suggestions")
check(Bo.post(B + f"{O}/pay-props/{P1}", json={"action": "accept"}).status_code == 403, "#1350: a member may not accept (403)")
check(Ca.post(B + f"{O}/pay-props/{P1}", json={"action": "accept"}).status_code in (403, 404), "#1350: another organisation reaches nothing")
r = A.post(B + f"{O}/pay-props/{P1}", json={"action": "accept"})
check(r.ok and r.json()["state"] == "accepted" and r.json()["payment_id"], "#1350: the admin accepts: booked " + r.text[:200])
pays = A.get(B + f"{D}/{INV}/payments").json()["payments"]
check(len(pays) == 1 and float(pays[0]["amount"]) == 100.0, "#1350: the payment is recorded")
check(A.post(B + f"{O}/pay-props/{P1}", json={"action": "reject"}).status_code == 409, "#1350: decided once")
check(A.post(B + f"{O}/pay-props/{P2}", json={"action": "reject"}).json()["state"] == "rejected", "#1350: the admin rejects")

# ---------------------------------------------------------------- a freelancer without organisation
Do.get(B + O + "/settings")
r = Do.post(B + "/api/my/agents", json={"username": "dorabot", "display_name": "Dora Bot", "scopes": ["read", "office"]})
DAG, DH = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
check(requests.get(V, headers=DH).status_code == 403, "#1360: the freelancer's agent is off by default")
check(Do.patch(B + f"{O}/agents/{DAG}", json={"office_drafts": True}).ok, "#1360: the freelancer switches her own agent on")
check(A.patch(B + f"{O}/agents/{DAG}", json={"office_drafts": False}).status_code == 404, "#1360: nobody else reaches it")
check(Do.put(B + O + "/settings", json={"agents_read": 1}).ok, "#1360: the privacy switch of the personal office")
CLP = Do.post(B + "/api/clients", json={"name": "Privatkunde Eins"}).json()["id"]
r = requests.get(V + "/clients", headers=DH)
check(r.ok and [x["id"] for x in r.json()["data"]] == [CLP], "#1360: the personal office's clients only")
r = requests.post(V + "/offers", headers=DH, json={"client_id": CLP, "title": "Portrait", "items": [{"text": "Fotos", "qty": 1, "unit": "flat", "price": 300}]})
check(r.status_code == 201 and r.json()["doc"]["items"][0]["agent_flag"] == "free", "#1360: a draft in the personal office " + r.text[:200])
DQ = r.json()["doc"]["id"]
check(ag("GET", f"/docs/{DQ}").status_code == 404 and requests.get(V + f"/docs/{QID}", headers=DH).status_code == 404, "#1360: the areas stay apart (404)")
check(requests.post(V + "/offers", headers=DH, json={"client_id": CL, "title": "x"}).status_code == 404, "#1360: no client of an organisation")

# ---------------------------------------------------------------- switched off again
# 2.223.2 B (#2862): the agent is in office groups since the payment suggestions -- "switched off" = the group No office access
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": False}).ok and A.put(B + f"{O}/rights/people/{AG}", json={"groups": ["tpl:none"]}).ok
      and ag("GET", "/services").status_code == 403, "#1348: switched off = 403 at once")
A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True})
# 2.223.7 C (#2670): offer_accepted (review 15 below) only for an agent whose office groups give it the offers -> back into its groups
A.put(B + f"{O}/rights/people/{AG}", json={"groups": ["tpl:projects", "tpl:bookkeeping"]})
A.put(B + O + "/settings", json={"agents_read": 0})
check(ag("GET", "/services").status_code == 403, "#1348: the privacy switch off = 403 at once")
r = A.post(B + "/api/admin/agents", json={"username": "movebot", "display_name": "Move Bot", "scopes": ["read", "office"]})
MB = r.json()["id"]
A.patch(B + f"/api/admin/agents/{MB}", json={"org_id": ORG})
check(A.patch(B + f"{O}/agents/{MB}", json={"office_drafts": True}).ok, "#1348: the switch of a team agent of the organisation")
check(A.patch(B + f"/api/admin/agents/{MB}", json={"org_id": None}).ok and A.patch(B + f"/api/admin/agents/{MB}", json={"org_id": ORG}).ok
      and A.get(B + f"{O}/agents/{MB}").json()["office_drafts"] is False, "#1348: another workspace switches the office switch off again")
MH = {**H, "Authorization": "Bearer " + r.json()["token"]}
A.patch(B + f"{O}/agents/{MB}", json={"office_drafts": True})
A.put(B + O + "/settings", json={"agents_read": 1})
check(requests.get(V, headers=MH).status_code == 400, "#1348: a team agent must name the person (requested_by)")
check(requests.get(V, headers=MH, params={"requested_by": ALICE}).status_code == 404, "#1348: ... who shares a list with it")
A.put(B + O + "/settings", json={"agents_read": 0})
r = A.post(B + "/api/my/agents", json={"username": "plainbot", "display_name": "Plain Bot", "scopes": ["read"], "org_id": ORG})
PH = {**H, "Authorization": "Bearer " + r.json()["token"]}
r = requests.get(V, headers=PH)
check(r.status_code == 403 and r.json()["error"].get("required_scope") == "office", "#1348: without the scope office: 403 " + r.text[:200])

# ---------------------------------------------------------------- 2.51.0 review 15: offer_accepted and personal agents
# a personal agent of bob in Alpha hears offer_accepted only while bob works in the office himself
A.put(B + O + "/settings", json={"agents_read": 1})
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "display_name": "Bob Bot", "scopes": ["read", "office"], "org_id": ORG})
check(r.status_code == 201, "review 15: bob's personal agent in Alpha " + r.text[:200])
BAG, BH = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
check(A.patch(B + f"{O}/agents/{BAG}", json={"office_drafts": True}).ok, "review 15: the admin switches bob's agent on")


def accepted_offer(title):
    did = A.post(B + D, json={"client_id": CL, "project_title": title}).json()["id"]
    A.put(B + f"{D}/{did}/items", json={"items": [{"kind": "service", "title": "Kamera", "qty": 1, "unit": "day", "rate": 800}]})
    for st_ in ("sent", "accepted"):
        A.post(B + f"{D}/{did}/status", json={"status": st_})
    return did


def heard(hd, did):
    ev_ = requests.get(B + "/api/v1/agent/events", headers=hd, params={"since": 0, "limit": 500}).json()
    return [e for e in ev_.get("events", ev_.get("data", [])) if e["event"] == "offer_accepted" and e["data"].get("doc_id") == did]


Bo.patch(B + "/api/settings", json={"features": "cal,comments,collab,clients"})  # bob without the office module
Q15 = accepted_offer("Review 15 ohne Buero")
check(not heard(BH, Q15), "review 15: the owner has no office: his agent does not hear offer_accepted")
check(heard(AH, Q15), "review 15: alice's agent (owner in the office) still hears it")
Bo.patch(B + "/api/settings", json={"features": FEAT})
Q16 = accepted_offer("Review 15 mit Buero")
check(heard(BH, Q16), "review 15: owner back in the office: his agent hears it")
A.put(B + O + "/settings", json={"agents_read": 0})

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
