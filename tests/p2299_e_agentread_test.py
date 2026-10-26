#!/usr/bin/env python3
"""2.299.0 E (#3194) API tests: a connected agent reads a receipt (proposal kind receipt_read). Kalmido calls no model and
sends nothing out: the person asks one of their agents, the agent gets job_request with what the documents API shows it plus
the address of the file (it reads the file with its own token), answers with the values it read, the person takes them over
(as that person, one undo step) or discards them. Invented companies and figures only, the files are made here.
 - who may be asked: the agent's office switch (in an organisation only with an office group giving the receipts, 2.223.2), the area's "Agents may read office data", the file shared with the agent, the
   person may change the document; another member / another organisation: nobody and 404; office groups: "No office access"
   none, "Project management" (receipts) yes; the agent cannot take anything over (404)
 - the input: the document as API v1 shows it to the agent, mime + content_url (the agent fetches the file), the categories,
   the limits; bank bookings only for an agent whose office groups give it the bank
 - the answer validated strictly (unknown fields, too many positions, a bad VAT id / amount / date / currency, a bank booking
   not offered: 400); values normalised
 - the document sheet: "agent_read" while asked / ready (people only, never in API v1), what Take over would change, the checks
 - take over: amount, date, sender, VAT rate, category + the read values as the recognised values; undo / redo; undo skips a
   value changed by hand; discard tells the agent; the switch off / the file unshared before the answer: 403
 - a locked month: taking over 409, nothing changed (not even the read values)
 - a freelancer without an organisation does the same with the own agent in the personal office (freelancer-matrix: office)
usage: p2299_e_agentread_test.py <datadir>   (P2299E_NOSTART=1: against a running instance on KALMIDO_TEST_PORT)"""
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
from kt import FAILS, OKS, check, sess  # noqa: E402  shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
R = O + "/rights"


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


def agents_for(s, doc_id):
    r = s.get(B + "/api/proposals/agents", params={"kind": "receipt_read", "doc_id": doc_id})
    return [a["id"] for a in r.json().get("agents", [])] if r.ok else None


def ask(s, **b):
    return s.post(B + "/api/proposals", json={"kind": "receipt_read", **b})


def answer(ag, jid, body):
    return ag.post(V + f"/agent/jobs/{jid}/proposal", json=body)


def upload(s, ws, name, text):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, text.encode(), "text/plain")})
    assert r.ok, r.text
    nid = (r.json().get("ids") or [x["id"] for x in r.json().get("docs") or r.json().get("items") or []])[0]
    for _ in range(200):  # the recognition run: wait for its state, not for a time
        if s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"):
            break
        time.sleep(0.2)
    return nid


def dget(s, nid):
    return s.get(B + f"/api/docs/{nid}").json()


def rc(s, nid):
    return (s.get(B + f"/api/docs/{nid}/receipt").json().get("receipt") or {})


RECEIPT = ("Beispiel Bürobedarf GmbH\nMusterweg 3, 12345 Musterstadt\nUSt-IdNr. DE123456789\nRechnung Nr. RE-2026-17\n"
           "Datum 05.10.2026\nPapier A4 10 x 10,00 EUR\nNetto 100,00 EUR\nMwSt 19 % 19,00 EUR\nGesamt 119,00 EUR\n")
GOOD = {"supplier": "Beispiel Bürobedarf GmbH", "vat_id": "DE 123 456 789", "invoice_no": "RE-2026-17", "date": "2026-10-05", "net": "100.00",
        "vat": 19, "gross": "119,00", "vat_pct": 19, "vat_rates": [{"pct": "19", "net": "100.00", "vat": "19.00"}], "currency": "EUR",
        "positions": [{"text": "Papier A4", "qty": 10, "net": "100.00", "vat_pct": "19"}], "category": "Bürobedarf", "account": "4930"}

if not os.environ.get("P2299E_NOSTART"):
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
A.get(B + O + "/settings")
Ca.get(B + O + "/settings")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "readbot", "display_name": "Read Bot", "scopes": ["read", "office", "files:read"], "org_id": ORG})
assert r.status_code == 201, r.text
AG, AGS = r.json()["id"], tok(r.json()["token"])
DOC = upload(A, f"org:{ORG}", "rechnung.txt", RECEIPT)
check(A.patch(B + f"/api/docs/{DOC}", json={"amount": "1.00", "date": "2026-10-01"}).ok, "setup: amount / date by hand (Take over has something to change)")
CDOC = upload(Ca, f"org:{ORG2}", "fremd.txt", "Fremde Firma AG\nRechnung 9\nGesamt 50,00 EUR\n")

# ---------------------------------------------------------------- who may be asked
check(agents_for(A, DOC) == [] and ask(A, agent_id=AG, doc_id=DOC).status_code == 404, "the agent's office switch off: nobody to ask, 404")
check(A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok, "setup: the agent's office switch")
check(agents_for(A, DOC) == [], "the area's privacy switch off: nobody to ask")
check(A.put(B + O + "/settings", json={"agents_read": 1}).ok, "setup: agents may read office data")
check(agents_for(A, DOC) == [] and ask(A, agent_id=AG, doc_id=DOC).status_code == 404, "the file not shared with the agent: nobody, 404")
r = A.post(B + f"/api/files/nodes/{DOC}/shares", json={"agent_id": AG, "role": "view"})
check(r.ok, "setup: the file shared with the agent")
SHARE = r.json().get("id")
# 2.223.2 B (#2862): in an organisation the switch alone opens only the quotes' scope; the receipts need an office group
check(agents_for(A, DOC) == [] and ask(A, agent_id=AG, doc_id=DOC).status_code == 404, "both switches on, the file shared, an organisation's agent without office groups: nobody (receipts need a group, 2.223.2)")
check(ask(A, agent_id=AG, doc_id=DOC, field="intro").status_code == 400, "unknown keys of the request 400")
# office groups decide once the agent is in one: no office access -> none; project management (receipts) -> yes
check(A.put(B + f"{R}/people/{AG}", json={"groups": ["tpl:none"]}).ok, "setup: the agent into No office access")
check(agents_for(A, DOC) == [], "office groups: No office access: nobody to ask")
check(A.put(B + f"{R}/people/{AG}", json={"groups": ["tpl:projects"]}).ok, "setup: the agent into Project management")
check(agents_for(A, DOC) == [AG], "office groups: Project management has the receipts: the agent")
check(agents_for(Bo, DOC) == [] and ask(Bo, agent_id=AG, doc_id=DOC).status_code == 404, "another member (the document is not his): nobody, 404")
check(agents_for(Ca, DOC) == [] and ask(Ca, agent_id=AG, doc_id=DOC).status_code == 404, "another organisation: nobody, 404")
check(agents_for(A, CDOC) == [] and ask(A, agent_id=AG, doc_id=CDOC).status_code == 404, "another organisation's document: 404")

# ---------------------------------------------------------------- the request and its input
r = ask(A, agent_id=AG, doc_id=DOC, wish="bitte genau")
check(r.status_code == 201, "the request " + r.text[:200])
J1 = r.json()["id"]
ev = job_input(AGS, J1)
inp = ev.get("input") or {}
d = inp.get("document") or {}
v1d = AGS.get(V + f"/documents/{DOC}").json()
check(ev.get("kind") == "receipt_read" and d.get("id") == DOC and d.get("text") == v1d.get("text") and "RE-2026-17" in (d.get("text") or ""),
      f"the input = what the documents API shows the agent {str(d)[:200]}")
check(d.get("content_url") == f"/api/v1/files/{DOC}/content" and d.get("mime", "").startswith("text/") and isinstance(inp.get("categories"), list)
      and "bank" not in inp and inp.get("wish") == "bitte genau", f"the input: the file's address, the categories, no bank (project management) {str(inp)[:300]}")
check((ev.get("limits") or {}).get("positions_max") == 100, "the limits carry the positions")
f = AGS.get(B + d.get("content_url", "/x"))
check(f.ok and b"RE-2026-17" in f.content, "the agent fetches the file itself with its token")
check("cost" not in str(inp) and "agent_read" not in v1d, "API v1 never shows the person's agent_read")
a = dget(A, DOC).get("agent_read") or {}
check(a.get("job") == J1 and a.get("state") == "requested" and a.get("agent", {}).get("id") == AG, f"the document sheet: the agent is reading {a}")
check(dget(Bo, DOC).get("agent_read") is None if Bo.get(B + f"/api/docs/{DOC}").ok else True, "another person: no agent_read")

# ---------------------------------------------------------------- the answer, strictly checked
for bad, what in (({"foo": 1}, "an unknown field"), ({"positions": [{"text": "x"}] * 101}, "101 positions"), ({"vat_id": "xx"}, "a bad VAT id"),
                  ({"gross": "-5"}, "a negative gross"), ({"gross": "1.234"}, "three decimals"), ({"date": "2026-13-01"}, "a bad date"),
                  ({"positions": [{"text": "x", "price": 1}]}, "an unknown position field"), ({"positions": [{"qty": 1}]}, "a position without text"),
                  ({"bank_tx": 5}, "a bank booking not offered"), ({}, "nothing read"), ({"supplier": "x" * 201}, "a supplier too long"),
                  ({"currency": "euro"}, "a bad currency"), ({"vat_pct": 45}, "a VAT rate over 30"), ({"vat_rates": "19"}, "VAT rates not a list"),
                  ({"supplier": ["A"]}, "a supplier not a text"), ({"kind": "doc_summary", "text": "x"}, "another kind")):
    check(answer(AGS, J1, bad).status_code == 400, f"answer: {what} 400")
r = answer(AGS, J1, GOOD)
check(r.status_code == 201, "answer: the values " + r.text[:200])
p = r.json().get("proposal") or {}
check((p.get("vat_id"), p.get("vat"), p.get("gross"), p.get("vat_pct"), p["positions"][0]["qty"] if p.get("positions") else None) == ("DE123456789", "19.00", "119.00", "19", "10"),
      f"answer: the values normalised {p}")
check(AGS.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code in (401, 403, 404), "the agent cannot take anything over")
check(Bo.get(B + f"/api/proposals/{J1}").status_code == 404 and Bo.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code == 404,
      "another person: the card 404, taking over 404")
a = dget(A, DOC).get("agent_read") or {}
check(a.get("state") == "ready" and (a.get("values") or {}).get("gross") == "119.00" and {"amount", "date", "sender", "vat_pct", "category"} <= set(a.get("new") or [])
      and isinstance(a.get("checks"), list), f"the document sheet: the values, what Take over changes, the checks {a}")
v = A.get(B + f"/api/proposals/{J1}").json()
check(v.get("kind") == "receipt_read" and (v.get("target") or {}).get("doc_id") == DOC and (v.get("target") or {}).get("editable") is True,
      f"the card: the target {str(v.get('target'))[:200]}")

# ---------------------------------------------------------------- take over, undo, redo
before = dget(A, DOC)
r = A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]})
check(r.ok and r.json().get("changed") == 1, "taken over " + r.text[:200])
d1, r1 = dget(A, DOC), rc(A, DOC)
check(d1.get("amount") == "119.00" and d1.get("date") == "2026-10-05" and (d1.get("sender") or {}).get("name") == "Beispiel Bürobedarf GmbH",
      f"taken over: amount, date, sender {d1.get('amount')} {d1.get('date')} {d1.get('sender')}")
check(r1.get("vat_pct") == "19" and r1.get("category") == "Bürobedarf", f"taken over: the receipt's VAT rate and category {r1}")
x = d1.get("extracted") or {}
check(x.get("invoice_no") == "RE-2026-17" and x.get("vat_id") == "DE123456789", f"taken over: the read values are the recognised values {x}")
check(d1.get("agent_read") is None, "taken over: the line goes")
check(A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code == 409, "taking over twice 409")
r = A.post(B + f"/api/proposals/{J1}/undo")
d2 = dget(A, DOC)
check(r.ok and r.json().get("undone") == 1 and d2.get("amount") == "1.00" and d2.get("date") == "2026-10-01" and rc(A, DOC).get("category") in (None, ""),
      f"undo: the values before {r.text[:120]} {d2.get('amount')} {d2.get('date')}")
check((d2.get("sender") or None) == (before.get("sender") or None), "undo: the sender before")
r = A.post(B + f"/api/proposals/{J1}/redo")
check(r.ok and dget(A, DOC).get("amount") == "119.00" and rc(A, DOC).get("category") == "Bürobedarf", "redo")
check(A.patch(B + f"/api/docs/{DOC}", json={"amount": "120.00"}).ok, "setup: the amount changed by hand")
r = A.post(B + f"/api/proposals/{J1}/undo")
check(r.ok and r.json().get("undone") == 0 and r.json().get("skipped") and dget(A, DOC).get("amount") == "120.00", "undo skips a value changed since")
A.patch(B + f"/api/docs/{DOC}", json={"amount": "119.00"})

# ---------------------------------------------------------------- discard; the switch off / the file unshared before the answer
J2 = ask(A, agent_id=AG, doc_id=DOC).json().get("id")
check(J2 and answer(AGS, J2, {"gross": "119.00"}).status_code == 201 and A.post(B + f"/api/proposals/{J2}/discard").ok, "discarded")
check(any(e["data"].get("job", {}).get("id") == J2 and e["data"].get("action") == "reject" for e in events(AGS, "job")), "discard tells the agent")
check(dget(A, DOC).get("agent_read") is None, "discarded: the line goes")
J3 = ask(A, agent_id=AG, doc_id=DOC).json().get("id")
check(A.delete(B + f"/api/files/shares/{SHARE}").ok and not AGS.get(V + f"/documents/{DOC}").ok, "setup: the file unshared")
check(answer(AGS, J3, {"gross": "119.00"}).status_code == 403, "the file no longer shared before the answer: 403")
check(A.post(B + f"/api/files/nodes/{DOC}/shares", json={"agent_id": AG, "role": "view"}).ok, "setup: shared again")
check(A.put(B + f"{R}/people/{AG}", json={"groups": ["tpl:none"]}).ok, "setup: the agent's office access off")
check(answer(AGS, J3, {"gross": "119.00"}).status_code == 403, "office access off before the answer: 403")
A.post(B + f"/api/proposals/{J3}/discard")

# ---------------------------------------------------------------- bank bookings only for an agent with the bank (office groups)
CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>S-1</Id>
<Ntry><Amt Ccy="EUR">119.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-10-07</Dt></BookgDt><NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>Beispiel Buerobedarf</Nm></Pty></Cdtr></RltdPties>
<RmtInf><Ustrd>RE-2026-17</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="EUR">59.50</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-10-06</Dt></BookgDt><NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>Markt Beispiel</Nm></Pty></Cdtr></RltdPties>
<RmtInf><Ustrd>Einkauf</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
</Stmt></BkToCstmrStmt></Document>"""
r = A.post(B + O + "/bank/import", json={"text": CAMT, "filename": "konto.xml"})
check(r.status_code == 201, "setup: a bank statement " + r.text[:200])
r = A.put(B + f"{R}/people/{AG}", json={"groups": ["tpl:bookkeeping"]})
check(r.ok, "setup: the agent into Bookkeeping (bank + receipts) " + r.text[:200])
J4 = ask(A, agent_id=AG, doc_id=DOC).json().get("id")
bank = (job_input(AGS, J4).get("input") or {}).get("bank")
check(isinstance(bank, list) and len(bank) == 1 and bank[0]["amount"] == "-119.00" and set(bank[0]) == {"id", "day", "amount", "currency", "counterpart", "purpose"},
      f"bookkeeping: the open booking with the receipt's amount, nothing else {bank}")
if bank:
    check(answer(AGS, J4, {"gross": "119.00", "bank_tx": bank[0]["id"] + 1000}).status_code == 400, "a booking not offered 400")
    check(answer(AGS, J4, {"gross": "119.00", "bank_tx": bank[0]["id"]}).status_code == 201, "the suggested booking")
    b = (dget(A, DOC).get("agent_read") or {}).get("bank") or {}
    check(b.get("id") == bank[0]["id"] and b.get("matched") is False, f"the document sheet: the booking as the person sees it {b}")
    check(A.post(B + f"{O}/bank/tx/{bank[0]['id']}/match", json={"kind": "receipt", "id": DOC}).ok, "the person matches it in the bank (its own route)")
    b = (dget(A, DOC).get("agent_read") or {}).get("bank") or {}
    check(b.get("this") is True, "matched with this receipt")
A.post(B + f"/api/proposals/{J4}/discard")
check(A.put(B + f"{R}/people/{AG}", json={"groups": ["tpl:projects"]}).ok, "setup: back to Project management")
J5 = ask(A, agent_id=AG, doc_id=DOC).json().get("id")
check("bank" not in (job_input(AGS, J5).get("input") or {}), "project management: no bank bookings in the input")
check(answer(AGS, J5, {"gross": "119.00", "bank_tx": (bank or [{"id": 1}])[0]["id"]}).status_code == 400, "project management: a booking 400")
A.post(B + f"/api/proposals/{J5}/discard")

# ---------------------------------------------------------------- a freelancer: the same in the personal office
# freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.get(B + O + "/settings")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "office", "files:read"]})
check(r.status_code == 201, "freelancer: her own agent " + r.text[:200])
FAG, FAGS = r.json()["id"], tok(r.json()["token"])
check(Fr.patch(B + f"{O}/agents/{FAG}", json={"office_drafts": True}).ok and Fr.put(B + O + "/settings", json={"agents_read": 1}).ok,
      "freelancer: both office switches")
FD = upload(Fr, "private", "hotel.txt", "Hotel Beispiel\nRechnung 4711\n2 Nächte 240,00 EUR\nMwSt 7 %\n")
check(agents_for(Fr, FD) == [], "freelancer: not shared: nobody")
check(Fr.post(B + f"/api/files/nodes/{FD}/shares", json={"agent_id": FAG, "role": "view"}).ok, "setup: shared with her agent")
check(agents_for(Fr, FD) == [FAG] and agents_for(A, FD) == [], "freelancer: her agent, nobody else's")
check(ask(A, agent_id=AG, doc_id=FD).status_code == 404, "freelancer: another person's request for her document 404")
J6 = ask(Fr, agent_id=FAG, doc_id=FD).json().get("id")
check(J6 and answer(FAGS, J6, {"supplier": "Hotel Beispiel", "invoice_no": "4711", "date": "2026-09-10", "gross": "240.00", "vat_pct": "7", "category": "Reise"}).status_code == 201,
      "freelancer: request + answer")
check(Fr.post(B + f"/api/proposals/{J6}/apply", json={"select": ["0"]}).ok and dget(Fr, FD).get("amount") == "240.00" and rc(Fr, FD).get("vat_pct") == "7",
      "freelancer: taken over (amount, VAT rate)")
check(Fr.post(B + f"/api/proposals/{J6}/undo").ok and rc(Fr, FD).get("vat_pct") in (None, ""), "freelancer: undo")
check(Fr.post(B + f"/api/proposals/{J6}/redo").ok and rc(Fr, FD).get("vat_pct") == "7", "freelancer: redo (a receipt of 10.09.2026 again)")
# a locked month: taking over 409, nothing changed (the lock has no way back: the freelancer's own office, at the very end)
J7 = ask(Fr, agent_id=FAG, doc_id=FD).json().get("id")
check(J7 and answer(FAGS, J7, {"gross": "250.00", "date": "2026-09-11"}).status_code == 201, "freelancer: a second answer")
r = Fr.post(B + O + "/periods/lock", json={"through": "2026-09", "confirm": "09/2026"})
check(r.ok, "setup: September 2026 locked " + r.text[:200])
r = Fr.post(B + f"/api/proposals/{J7}/apply", json={"select": ["0"]})
check(r.status_code == 409 and dget(Fr, FD).get("amount") == "240.00" and dget(Fr, FD).get("date") == "2026-09-10",
      f"a locked month: taking over 409, nothing changed {r.status_code}")
J8 = ask(Fr, agent_id=FAG, doc_id=FD).json().get("id")
check(J8 and answer(FAGS, J8, {"invoice_no": "4711-B"}).status_code == 201, "freelancer: an answer with the invoice number only")
r = Fr.post(B + f"/api/proposals/{J8}/apply", json={"select": ["0"]})
check(r.status_code == 409 and (dget(Fr, FD).get("extracted") or {}).get("invoice_no") == "4711",
      f"a locked month: not even the read values change (409) {r.status_code}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
