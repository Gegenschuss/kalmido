#!/usr/bin/env python3
"""2.126.1 API tests, part A (#2123 #2124): texts worded by a connected agent, on request of a person. Kalmido calls no
model: the person asks, the agent gets job_request with exactly the data it may read, answers with a proposal, the person
takes it over (as that person, one undo step) or discards it. Invented companies, people and figures only.
 - office_text: who may be asked (the agent's office switch, the area's "Agents may read office data", the person works in
   that office; a member without the office module: none; another organisation: none / 404); the input carries the
   document, the client, the positions WITHOUT purchase prices, the current text and the wish (one office log line);
   bad requests 400 (field, wish too long, unknown keys); the agent's answer validated (unknown fields, another field,
   empty text 400; control characters out); the card (target), another person 404; take over writes the field, undo / redo,
   twice 409; a sent document: the request 409, taking over 409 and nothing changed; the switch off before the answer: 403;
   discard tells the agent; a reminder draft carries its invoices (open amount, days overdue) and level
 - doc_summary: only an agent that sees the file (shared with it) and works in the area; the input = what the documents API
   shows it; take over stores the summary (document sheet and API v1), undo / redo; too long 400
 - report: only agents the list is shared with (status report dialog: agents, agent_text); the input = the status report as
   the agent sees the list + its fixed Markdown, never comments / notes; take over -> agent_text for the period, undo ->
   the fixed text again; a list not shared: 404
 - a freelancer without an organisation does all three with the own agent in the personal office / private space
   (freelancer-matrix: agents, office)
usage: p21261_a_api_test.py <datadir>   (P21261A_NOSTART=1: against a running instance on KALMIDO_TEST_PORT)"""
import json
import os
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
import dbx as dbxm  # noqa: E402  # 2.355.0 D (#2846)
FEAT = "cal,comments,collab,office,clients,docs,files"


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def events(ag, kind):
    j = ag.get(V + "/agent/events", params={"since": 0, "limit": 500}).json()
    return [e for e in j.get("data", j.get("events", [])) if e["event"] == kind]


def job_input(ag, jid):
    ev = [e for e in events(ag, "job_request") if e["data"]["job"]["id"] == jid]
    return ev[-1]["data"] if ev else {}


def agents_for(s, kind, **q):
    r = s.get(B + "/api/proposals/agents", params={"kind": kind, **q})
    return [a["id"] for a in r.json().get("agents", [])] if r.ok else None


def ask(s, **b):
    return s.post(B + "/api/proposals", json=b)


def answer(ag, jid, body):
    return ag.post(V + f"/agent/jobs/{jid}/proposal", json=body)


if not os.environ.get("P21261A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
O = "/api/office"
D = O + "/docs"
A.get(B + O + "/settings")
A.put(B + O + "/settings", json={"company_fields": {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
                                                     "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
CL = A.post(B + "/api/clients", json={"name": "Musterfirma GmbH", "address": "Weg 2\n10115 Berlin"}).json()["id"]
Ca.get(B + O + "/settings")
CL2 = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG"}).json()["id"]
FQ = Ca.post(B + D, json={"client_id": CL2, "project_title": "Fremdes Angebot"}).json()["id"]


def quote(title, intro="Alte Einleitung"):
    q = A.post(B + D, json={"client_id": CL, "project_title": title}).json()["id"]
    r = A.put(B + f"{D}/{q}/items", json={"items": [{"kind": "service", "title": "Kamera", "qty": 2, "unit": "day", "rate": 800, "cost": 333.33}]})
    assert r.ok, r.text
    assert A.patch(B + f"{D}/{q}", json={"intro": intro, "closing": "Alter Schluss"}).ok
    return q


def doc(s, did):
    return s.get(B + f"{D}/{did}").json()


A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "office"], "org_id": ORG})
assert r.status_code == 201, r.text
AG, AGS = r.json()["id"], tok(r.json()["token"])
Q = quote("Imagefilm")

# ---------------------------------------------------------------- office_text: who may be asked
check(agents_for(A, "office_text", doc_id=Q) == [], "office_text: the agent's office switch off: nobody to ask")
check(ask(A, kind="office_text", agent_id=AG, doc_id=Q, field="intro").status_code == 404, "office_text: switch off: 404")
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok, "setup: the office switch of the agent")
check(agents_for(A, "office_text", doc_id=Q) == [], "office_text: the area's privacy switch off: nobody to ask")
check(A.put(B + O + "/settings", json={"agents_read": 1}).ok, "setup: agents may read office data")
check(agents_for(A, "office_text", doc_id=Q) == [AG], "office_text: both switches on: the agent")
check(agents_for(Bo, "office_text", doc_id=Q) == [], "office_text: another member: alice's personal agent is not his")
check(agents_for(Ca, "office_text", doc_id=Q) == [] and agents_for(A, "office_text", doc_id=FQ) == [], "office_text: another organisation: none")
check(ask(A, kind="office_text", agent_id=AG, doc_id=FQ, field="intro").status_code == 404, "office_text: another organisation's document 404")
# a team agent of the organisation: a member may ask it; without the office module not
r = A.post(B + "/api/admin/agents", json={"username": "teambot", "display_name": "Team Bot", "scopes": ["read", "office"]})
assert r.status_code in (200, 201), r.text
MB, MBS = r.json()["id"], tok(r.json()["token"])
A.patch(B + f"/api/admin/agents/{MB}", json={"org_id": ORG, "proposals": "all"})
check(A.patch(B + f"{O}/agents/{MB}", json={"office_drafts": True}).ok, "setup: the team agent's office switch")
check(MB in agents_for(Bo, "office_text", doc_id=Q), "office_text: a member may ask the team agent")
Bo.patch(B + "/api/settings", json={"features": "cal,comments,collab"})
check(agents_for(Bo, "office_text", doc_id=Q) == [] and ask(Bo, kind="office_text", agent_id=MB, doc_id=Q).status_code in (403, 404),
      "office_text: a member without the office module: nobody, the request refused")
Bo.patch(B + "/api/settings", json={"features": FEAT})

# ---------------------------------------------------------------- office_text: the request and its input
check(ask(A, kind="office_text", agent_id=AG, doc_id=Q, field="body").status_code == 400, "office_text: an unknown field 400")
check(ask(A, kind="office_text", agent_id=AG, doc_id=Q, field="intro", wish="x" * 501).status_code == 400, "office_text: a wish too long 400")
check(ask(A, kind="office_text", agent_id=AG, doc_id=Q, field="intro", items=[]).status_code == 400, "office_text: unknown keys 400")
log0 = len([x for x in A.get(B + O + "/log", params={"limit": 200}).json()["log"] if x["action"] == "agent_read"])
r = ask(A, kind="office_text", agent_id=AG, doc_id=Q, field="intro", wish="freundlich, kurz")
check(r.status_code == 201, "office_text: the request " + r.text[:200])
J1 = r.json()["id"]
ev = job_input(AGS, J1)
inp = ev.get("input") or {}
check(ev.get("kind") == "office_text" and inp.get("doc", {}).get("id") == Q and inp.get("field") == "intro" and inp.get("text") == "Alte Einleitung"
      and inp.get("wish") == "freundlich, kurz" and inp.get("client", {}).get("name") == "Musterfirma GmbH", f"office_text: the input {str(inp)[:300]}")
its = inp.get("items") or []
check(its and its[0].get("title") == "Kamera" and all("cost" not in it and "margin" not in it for it in its) and "333" not in json.dumps(inp),
      f"office_text: positions without purchase prices {its}")
log = A.get(B + O + "/log", params={"limit": 200}).json()["log"]
al = [x for x in log if x["action"] == "agent_read"]
check(len(al) == log0 + 1 and al[0]["user_id"] == AG and al[0]["doc_id"] == Q, "office_text: one line in the office log for the agent's read")

# ---------------------------------------------------------------- office_text: the agent's answer
check(answer(AGS, J1, {"text": "x", "tone": "warm"}).status_code == 400, "office_text: unknown field in the answer 400")
check(answer(AGS, J1, {"field": "closing", "text": "x"}).status_code == 400, "office_text: another field than asked 400")
check(answer(AGS, J1, {"field": "intro", "text": "  "}).status_code == 400, "office_text: an empty text 400")
check(answer(MBS, J1, {"field": "intro", "text": "x"}).status_code == 404, "office_text: another agent cannot answer (404)")
r = answer(AGS, J1, {"field": "intro", "text": "Vielen Dank für Ihre Anfrage.\n\nGern bieten wir an:\x01"})
check(r.status_code == 201 and r.json()["proposal"]["text"] == "Vielen Dank für Ihre Anfrage.\n\nGern bieten wir an:", "office_text: the answer (control characters out) " + r.text[:200])
v = A.get(B + f"/api/proposals/{J1}").json()
check(v["state"] == "ready" and v["target"]["text"] == "Alte Einleitung" and v["target"]["editable"] is True, f"office_text: the card {v.get('target')}")
check(Bo.get(B + f"/api/proposals/{J1}").status_code == 404, "office_text: another person cannot open the card")
check(A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"], "edits": {"0": {"title": "x"}}}).status_code == 400, "office_text: unknown edit 400")
r = A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"], "edits": {"0": {"text": "Bearbeitete Einleitung"}}})
check(r.ok and r.json()["changed"] == 1, "office_text: taken over " + r.text[:200])
check(doc(A, Q)["intro"] == "Bearbeitete Einleitung" and doc(A, Q)["closing"] == "Alter Schluss", "office_text: the field has the edited text, the other stays")
check(A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code == 409, "office_text: twice 409")
r = A.post(B + f"/api/proposals/{J1}/undo")
check(r.ok and r.json()["undone"] == 1 and doc(A, Q)["intro"] == "Alte Einleitung", "office_text: undo brings the old text back")
r = A.post(B + f"/api/proposals/{J1}/redo")
check(r.ok and doc(A, Q)["intro"] == "Bearbeitete Einleitung", "office_text: redo")
jev = [e for e in events(AGS, "job") if e["data"]["job"]["id"] == J1]
check(jev and jev[-1]["data"]["action"] == "approve", "office_text: the agent hears that it was taken over")
A.patch(B + f"{D}/{Q}", json={"intro": "Von Hand geändert"})
r = A.post(B + f"/api/proposals/{J1}/undo")
check(r.ok and r.json()["undone"] == 0 and r.json()["skipped"] and doc(A, Q)["intro"] == "Von Hand geändert", "office_text: undo skips a text changed since")

# a sent document: neither the request nor taking over
Q2 = quote("Zweites Angebot")
J2 = ask(A, kind="office_text", agent_id=AG, doc_id=Q2, field="closing").json()["id"]
check(answer(AGS, J2, {"field": "closing", "text": "Mit freundlichen Grüßen"}).status_code == 201, "office_text: answer for the second quotation")
check(A.post(B + f"{D}/{Q2}/status", json={"status": "sent"}).ok, "setup: the quotation is sent")
check(ask(A, kind="office_text", agent_id=AG, doc_id=Q2, field="intro").status_code == 409, "office_text: a sent document: request 409")
check(A.get(B + f"/api/proposals/{J2}").json()["target"]["editable"] is False, "office_text: the card knows it can no longer be taken over")
check(A.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"]}).status_code == 409 and doc(A, Q2)["closing"] == "Alter Schluss",
      "office_text: taking over into a sent document 409, nothing changed")
check(A.post(B + f"/api/proposals/{J2}/discard").ok, "office_text: discard")
jev = [e for e in events(AGS, "job") if e["data"]["job"]["id"] == J2]
check(jev and jev[-1]["data"]["action"] == "reject", "office_text: the agent hears the discard")

# the switch off before the agent answers
Q3 = quote("Drittes Angebot")
J3 = ask(A, kind="office_text", agent_id=AG, doc_id=Q3, field="intro").json()["id"]
A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": False})
check(answer(AGS, J3, {"field": "intro", "text": "x"}).status_code == 403, "office_text: the switch off: the answer 403")
A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True})
check(answer(AGS, J3, {"field": "intro", "text": "Guten Tag"}).status_code == 201, "office_text: switched on again: the answer")
A.post(B + f"/api/proposals/{J3}/discard")

# a reminder draft: its invoices, open amount, level
AH = {"Authorization": "Bearer " + AGS.headers["Authorization"].split()[1]}
QA = quote("Angenommenes Angebot")
A.post(B + f"{D}/{QA}/status", json={"status": "sent"})
A.post(B + f"{D}/{QA}/status", json={"status": "accepted"})
r = requests.post(V + f"/office/offers/{QA}/invoice", headers=AH, json={})
check(r.status_code == 201, "setup: an invoice draft " + r.text[:200])
INV = r.json()["doc"]["id"]
A.patch(B + f"{D}/{INV}", json={"recipient": {"name": "Musterfirma GmbH", "lines": ["Weg 2", "10115 Berlin"]}, "service_from": "2026-01-05", "service_to": "2026-01-06"})
check(A.post(B + f"{D}/{INV}/finalize").ok, "setup: the invoice is finalised")
dbxm.overdue(DATA, [INV])  # 2.355.0 D (#2846): reminders only for overdue invoices
r = requests.post(V + "/office/reminders", headers=AH, json={"invoice_ids": [INV], "level": 2})
check(r.status_code == 201, "setup: a reminder draft " + r.text[:200])
REM = r.json()["doc"]["id"]
check(AG in agents_for(A, "office_text", doc_id=REM), "office_text: a reminder draft offers the agent")
J4 = ask(A, kind="office_text", agent_id=AG, doc_id=REM, field="intro").json().get("id")
rin = (job_input(AGS, J4).get("input") or {}).get("reminder") or {}
check(rin.get("level") == 2 and rin.get("invoices") and rin["invoices"][0].get("open") not in (None, "0.00") and "days_overdue" in rin["invoices"][0],
      f"office_text: the reminder's invoices, open amount, days overdue, level {rin}")
check(agents_for(A, "office_text", doc_id=INV) == [], "office_text: a finalised invoice offers nothing")

# ---------------------------------------------------------------- report
LID = A.post(B + "/api/lists", json={"name": "Imagefilm Projekt"}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"list_id": LID, "title": "Drehbuch schreiben", "content": "Geheime Notiz"}).json()["id"]
A.post(B + f"/api/tasks/{T1}/comments", json={"body": "Interner Kommentar"})
A.patch(B + f"/api/tasks/{T1}", json={"status": 2})
L2 = A.post(B + "/api/lists", json={"name": "Nicht geteilt"}).json()["id"]
r = A.post(B + "/api/admin/agents", json={"username": "reportbot", "display_name": "Report Bot", "scopes": ["read", "write"]})
RAG, RAGS = r.json()["id"], tok(r.json()["token"])
A.patch(B + f"/api/admin/agents/{RAG}", json={"org_id": ORG})
rep = A.get(B + f"/api/lists/{LID}/status-report", params={"days": 7}).json()
check(rep.get("agents") == [] and rep.get("agent_text") is None and rep.get("markdown"), "report: not shared: nobody to ask, the fixed text")
check(ask(A, kind="report", agent_id=RAG, list_id=LID, days=7).status_code == 404, "report: a list not shared with the agent 404")
check(A.put(B + f"/api/lists/{LID}/members", json={"user_id": RAG, "role": "edit"}).ok, "setup: the list is shared with the agent")
rep = A.get(B + f"/api/lists/{LID}/status-report", params={"days": 7}).json()
check(RAG in [a["id"] for a in rep.get("agents", [])], "report: the status report names the agent to ask")
check(ask(A, kind="report", agent_id=RAG, list_id=L2, days=7).status_code == 404, "report: another list not shared 404")
check(ask(A, kind="report", agent_id=RAG, list_id=LID, days=400).status_code == 400, "report: a bad period 400")
r = ask(A, kind="report", agent_id=RAG, list_id=LID, days=7, wish="kurz, freundlich", lang="de")
check(r.status_code == 201, "report: the request " + r.text[:200])
J5 = r.json()["id"]
rin = job_input(RAGS, J5).get("input") or {}
txt = json.dumps(rin, ensure_ascii=False)
check("Drehbuch schreiben" in rin.get("report", {}).get("markdown", "") and "Imagefilm Projekt" in rin["report"].get("markdown", "") and rin.get("wish") == "kurz, freundlich",
      f"report: the status data + its fixed text {txt[:300]}")
check("Geheime Notiz" not in txt and "Interner Kommentar" not in txt and "Alice" not in txt, "report: no notes, comments, names in the input")
check(answer(RAGS, J5, {"text": "x", "field": "intro"}).status_code == 400, "report: unknown field 400")
check(answer(RAGS, J5, {"text": "# Wochenbericht\n\nDas Drehbuch ist fertig."}).status_code == 201, "report: the agent's text")
r = A.post(B + f"/api/proposals/{J5}/apply", json={"select": ["0"], "edits": {"0": {"text": "# Wochenbericht\n\nDas Drehbuch ist fertig. Danke!"}}})
check(r.ok, "report: taken over " + r.text[:200])
rep = A.get(B + f"/api/lists/{LID}/status-report", params={"days": 7}).json()
check((rep.get("agent_text") or {}).get("text") == "# Wochenbericht\n\nDas Drehbuch ist fertig. Danke!" and "Imagefilm Projekt" in rep["markdown"],
      f"report: the dialog gets the text taken over, the fixed one stays as it is {rep.get('agent_text')}")
check(A.get(B + f"/api/lists/{LID}/status-report", params={"days": 14}).json().get("agent_text") is None, "report: another period: the fixed text")
A.post(B + f"/api/proposals/{J5}/undo")
check(A.get(B + f"/api/lists/{LID}/status-report", params={"days": 7}).json().get("agent_text") is None, "report: undo: the fixed text again")
A.post(B + f"/api/proposals/{J5}/redo")
check((A.get(B + f"/api/lists/{LID}/status-report", params={"days": 7}).json().get("agent_text") or {}).get("job") == J5, "report: redo")
check(RAGS.get(V + f"/lists/{LID}/status-report").ok and "agent_text" not in RAGS.get(V + f"/lists/{LID}/status-report").json(),
      "report: the API v1 status report stays as it was")

# ---------------------------------------------------------------- a freelancer: all three in the personal office / private space
# freelancer-matrix: agents, office
FID, Fr = freelancer(B, A)
Fr.get(B + O + "/settings")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "office", "write"]})
check(r.status_code == 201, "freelancer: her own agent " + r.text[:200])
FAG, FAGS = r.json()["id"], tok(r.json()["token"])
check(Fr.patch(B + f"{O}/agents/{FAG}", json={"office_drafts": True}).ok and Fr.put(B + O + "/settings", json={"agents_read": 1}).ok,
      "freelancer: both office switches")
FCL = Fr.post(B + "/api/clients", json={"name": "Privatkunde Eins"}).json()["id"]
FQ1 = Fr.post(B + D, json={"client_id": FCL, "project_title": "Portrait"}).json()["id"]
check(agents_for(Fr, "office_text", doc_id=FQ1) == [FAG] and agents_for(A, "office_text", doc_id=FQ1) == [], "freelancer: her agent for her draft, nobody else's")
J6 = ask(Fr, kind="office_text", agent_id=FAG, doc_id=FQ1, field="intro").json().get("id")
check(J6 and answer(FAGS, J6, {"field": "intro", "text": "Danke für Ihr Interesse."}).status_code == 201, "freelancer: request + answer")
check(Fr.post(B + f"/api/proposals/{J6}/apply", json={"select": ["0"]}).ok and doc(Fr, FQ1)["intro"] == "Danke für Ihr Interesse.", "freelancer: taken over")
# doc_summary
r = Fr.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("hotel.txt", "Hotel Beispiel\nRechnung 4711\n2 Nächte 240,00 EUR\nMwSt 7 %\n".encode(), "text/plain")})
check(r.ok, "freelancer: a document " + r.text[:200])
DN = (r.json().get("ids") or [x["id"] for x in r.json().get("docs") or r.json().get("items") or []])[0]
for _ in range(100):
    if Fr.get(B + f"/api/docs/{DN}").json().get("state") in ("done", "failed"):
        break
    time.sleep(0.3)
check(agents_for(Fr, "doc_summary", doc_id=DN) == [], "doc_summary: the agent does not see the file: nobody to ask")
check(ask(Fr, kind="doc_summary", agent_id=FAG, doc_id=DN).status_code == 404, "doc_summary: not shared 404")
check(Fr.post(B + f"/api/files/nodes/{DN}/shares", json={"agent_id": FAG, "role": "view"}).ok, "setup: the file shared with her agent")
check(agents_for(Fr, "doc_summary", doc_id=DN) == [FAG], "doc_summary: shared: her agent")
check(agents_for(A, "doc_summary", doc_id=DN) == [], "doc_summary: another person: nothing (404 inside)")
r = ask(Fr, kind="doc_summary", agent_id=FAG, doc_id=DN, wish="ein Satz")
check(r.status_code == 201, "doc_summary: the request " + r.text[:200])
J7 = r.json()["id"]
din = (job_input(FAGS, J7).get("input") or {}).get("document") or {}
v1d = FAGS.get(V + f"/documents/{DN}").json()
check(din.get("id") == DN and "Rechnung 4711" in (din.get("text") or "") and set(din) <= {"id", "name", "date", "due", "amount", "currency", "sender", "type", "tags", "text", "extracted", "summary"}
      and din.get("text") == v1d.get("text"), f"doc_summary: the input = what the documents API shows the agent {str(din)[:200]}")
check(answer(FAGS, J7, {"text": "x" * 4001}).status_code == 400, "doc_summary: too long 400")
check(answer(FAGS, J7, {"text": "Hotelrechnung über zwei Nächte, 240 EUR, 7 % MwSt."}).status_code == 201, "doc_summary: the answer")
check(Fr.post(B + f"/api/proposals/{J7}/apply", json={"select": ["0"]}).ok, "doc_summary: taken over")
check(Fr.get(B + f"/api/docs/{DN}").json().get("summary") == "Hotelrechnung über zwei Nächte, 240 EUR, 7 % MwSt.", "doc_summary: the document sheet shows the summary")
check(FAGS.get(V + f"/documents/{DN}").json().get("summary") == "Hotelrechnung über zwei Nächte, 240 EUR, 7 % MwSt.", "doc_summary: the documents API too")
Fr.post(B + f"/api/proposals/{J7}/undo")
check(Fr.get(B + f"/api/docs/{DN}").json().get("summary") == "", "doc_summary: undo removes it")
Fr.post(B + f"/api/proposals/{J7}/redo")
check(Fr.get(B + f"/api/docs/{DN}").json().get("summary", "").startswith("Hotelrechnung"), "doc_summary: redo")
# the org agent of alice does not see a private document of hers (another area)
r = A.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("notiz.txt", b"Privat\n", "text/plain")})
AD = (r.json().get("ids") or [x["id"] for x in r.json().get("docs") or r.json().get("items") or []])[0] if r.ok else 0
if AD:
    A.post(B + f"/api/files/nodes/{AD}/shares", json={"agent_id": AG, "role": "view"})
    check(agents_for(A, "doc_summary", doc_id=AD) == [], "doc_summary: a private document is not in the agent's office area")
# report in the private space
FL = Fr.post(B + "/api/lists", json={"name": "Portrait Projekt"}).json()["id"]
Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FAG, "role": "edit"})
check(FAG in [a["id"] for a in Fr.get(B + f"/api/lists/{FL}/status-report").json().get("agents", [])], "freelancer: report: her agent in her list")
J8 = ask(Fr, kind="report", agent_id=FAG, list_id=FL).json().get("id")
check(J8 and answer(FAGS, J8, {"text": "Alles im Plan."}).status_code == 201 and Fr.post(B + f"/api/proposals/{J8}/apply", json={"select": ["0"]}).ok
      and (Fr.get(B + f"/api/lists/{FL}/status-report").json().get("agent_text") or {}).get("text") == "Alles im Plan.", "freelancer: report taken over")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
