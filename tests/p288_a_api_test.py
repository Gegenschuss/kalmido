#!/usr/bin/env python3
"""2.88.0 API tests, part A (#1915): quotations with versions in the cash flow plan. Invented names only.
 - duplicating a quotation sets version_of to the chain's first quotation (a copy of a copy too); a copy for another
   client is a quotation of its own
 - auto: only the newest sent / accepted version of a chain counts, declined ones and drafts never; a sent one is an open
   quotation (open_offer), an accepted one is not
 - cashflow yes: exactly the yes versions count; no: never; a finalised invoice of any version takes the whole chain out
   (a draft invoice not yet)
 - POST /api/office/docs/{id}/cashflow: members of the office area (the right that edits a quotation), also for a sent
   quotation; 400 for a bad value / an invoice; 404 for another organisation; 403 without the office; logged
 - a personal office (person without organisation) the same; another person reaches nothing
 - agents: version_of / cashflow in the v1 list and document; PATCH of the own draft sets cashflow (bad value 400)
usage: p288_a_api_test.py <datadir>      (a fresh container; P288A_NOSTART=1 = the server already runs)"""
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


def ym_add(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


if not os.environ.get("P288A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("erin", "Erin Nooffice"), ("dora", "Dora Frei"), ("erik", "Erik Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Er, Do, Ek = sess("bob"), sess("carol"), sess("erin"), sess("dora"), sess("erik")
FEAT = "comments,collab,office,clients"
for s in (A, Bo, Ca, Do, Ek):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Er.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
for u in ("bob", "erin"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Er, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
O = "/api/office"
D = O + "/docs"
TODAY = testclock.today().isoformat()
M0 = TODAY[:7]
M1 = ym_add(M0, 1)
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
A.put(B + O + "/settings", json={"company_fields": COMPANY})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH"}).json()["id"]
CLB = A.post(B + "/api/clients", json={"name": "Kunde Zwei GmbH"}).json()["id"]


def quote(s, title, client, rate):
    q = s.post(B + D, json={"project_title": title, "client_id": client, "service_from": M1 + "-02", "service_to": M1 + "-20"}).json()
    s.put(B + f"{D}/{q['id']}/items", json={"items": [{"kind": "service", "title": "Dreh", "qty": 1, "unit": "day", "rate": rate}]})
    return q["id"]


def status(s, did, st):
    r = s.post(B + f"{D}/{did}/status", json={"status": st})
    assert r.ok, (did, st, r.text)


def dup(s, did):
    r = s.post(B + f"{D}/{did}/duplicate")
    assert r.status_code == 201, r.text
    return r.json()


def offers(s):
    """{doc_id: entry} of the quotations in the plan (this month + 5)."""
    cf = s.get(B + O + f"/cashflow?from={M0}&months=6").json()
    return {e["doc_id"]: e for e in cf["entries"] if e["kind"] == "offer"}


def setcf(s, did, v):
    return s.post(B + f"{D}/{did}/cashflow", json={"cashflow": v})


# ---------------------------------------------------------------- the chain
Q1 = quote(A, "Imagefilm", CL, 1000)
status(A, Q1, "sent")
d2 = dup(A, Q1)
Q2 = d2["id"]
check(d2["version_of"] == Q1 and d2["cashflow"] == "auto" and d2["status"] == "draft", f"#1915: a copy is the next version {d2.get('version_of')} {d2.get('cashflow')}")
status(A, Q2, "sent")
d3 = dup(A, Q2)
Q3 = d3["id"]
check(d3["version_of"] == Q1, f"#1915: a copy of a copy points at the first quotation too {d3.get('version_of')}")
check(A.get(B + f"{D}/{Q1}").json()["version_of"] is None, "#1915: the first quotation has no version_of")
of = offers(A)
check(set(of) == {Q2} and of[Q2]["open_offer"] is True and of[Q2]["month"] == M1, f"#1915: auto = only the newest sent version counts, as an open quotation {of}")
ch = A.get(B + f"{D}/{Q1}").json()["cf_chain"]
check(ch["cashflow"] == "auto" and not ch["counts"] and ch["counting"] == [Q2] and [v["id"] for v in ch["versions"]] == [Q1, Q2, Q3] and not ch["invoiced"],
      f"#1915: the chain in the editor says which version counts {ch}")
status(A, Q2, "declined")
check(set(offers(A)) == {Q1}, "#1915: a declined version is skipped, the one before counts")
status(A, Q3, "sent")
check(set(offers(A)) == {Q3}, "#1915: the newest sent version counts")

# ---------------------------------------------------------------- yes / no
r = setcf(A, Q1, "yes")
check(r.ok and r.json()["cashflow"] == "yes" and r.json()["cf_chain"]["counting"] == [Q1], "#1915: yes on a sent quotation " + r.text[:200])
check(set(offers(A)) == {Q1}, "#1915: a yes version counts instead of the newest")
setcf(A, Q3, "yes")
check(set(offers(A)) == {Q1, Q3}, "#1915: several yes versions count together")
setcf(A, Q3, "no")
setcf(A, Q1, "auto")
check(set(offers(A)) == {Q1}, "#1915: no never counts, auto takes the newest of the rest")
setcf(A, Q2, "yes")
check(set(offers(A)) == {Q1}, "#1915: yes on a declined version does not make it count")
setcf(A, Q2, "auto")
status(A, Q1, "accepted")
of = offers(A)
check(set(of) == {Q1} and of[Q1]["open_offer"] is False and of[Q1]["month"] == M1, f"#1915: an accepted quotation is no open quotation {of}")
check(A.post(B + f"{D}/{Q1}/cashflow", json={"cashflow": "maybe"}).status_code == 400 and A.post(B + f"{D}/{Q1}/cashflow", json={}).status_code == 400,
      "#1915: only auto / yes / no")
rows = A.get(B + O + "/log?limit=200").json()["log"]
check(any(x.get("action") == "cashflow" and x.get("doc_id") == Q1 for x in rows), "#1915: the change is in the office log")

# ---------------------------------------------------------------- rights
check(setcf(Bo, Q1, "no").ok and offers(A) == {}, "#1915: a member of the office (the right to edit quotations) may set it")
setcf(A, Q1, "auto")
check(setcf(Ca, Q1, "no").status_code == 404 and Ca.get(B + O + f"/cashflow?from={M0}&months=6").json()["entries"] == [],
      "#1915: another organisation: 404, sees nothing")
check(setcf(Er, Q1, "no").status_code == 403, "#1915: a person without the office: 403")
check(requests.post(B + f"{D}/{Q1}/cashflow", headers=H, json={"cashflow": "no"}).status_code == 401, "#1915: signed out: 401")
check(A.get(B + f"{D}/{Q1}").json()["cashflow"] == "auto", "#1915: the refused changes left it as it was")

# ---------------------------------------------------------------- an invoice takes the chain out
check(set(offers(A)) == {Q1}, "setup: Q1 counts")
setcf(A, Q3, "auto")
check(set(offers(A)) == {Q3}, "#1915: the newer sent version counts again")
INV = A.post(B + f"{D}/{Q1}/invoice").json()
check(set(offers(A)) == {Q3}, "#1915: a draft invoice does not take the chain out yet")
A.patch(B + f"{D}/{INV['id']}", json={"recipient": {"name": "Kunde Eins GmbH", "lines": ["Weg 2", "10115 Berlin"]}, "service_from": M0 + "-01", "service_to": M0 + "-02"})
r = A.post(B + f"{D}/{INV['id']}/finalize")
check(r.ok, "setup: the invoice is finalised " + r.text[:200])
check(offers(A) == {}, "#1915: an invoice of one version takes the whole chain out")
ch = A.get(B + f"{D}/{Q3}").json()["cf_chain"]
check(ch["invoiced"] and ch["counting"] == [] and not ch["counts"], f"#1915: the editor of another version says so {ch}")
check(setcf(A, Q3, "yes").ok and offers(A) == {}, "#1915: yes does not bring an invoiced chain back")
# a copy for another client is a quotation of its own
d4 = dup(A, Q3)
check(A.patch(B + f"{D}/{d4['id']}", json={"client_id": CLB}).ok, "setup: the copy goes to another client")
status(A, d4["id"], "sent")
check(set(offers(A)) == {d4["id"]}, "#1915: a copy for another client counts by itself")
# the field is planning, not content: the approval hash and the frozen document stay
r = setcf(A, d4["id"], "no")
check(r.ok and A.get(B + f"{D}/{d4['id']}").json()["status"] == "sent", "#1915: a sent quotation takes the choice")

# ---------------------------------------------------------------- a personal office (no organisation)
# freelancer-matrix: office
Do.put(B + O + "/settings", json={"company_fields": {**COMPANY, "name": "Dora Film"}})
CLP = Do.post(B + "/api/clients", json={"name": "Privatkunde Eins"}).json()["id"]
P1 = quote(Do, "Privatfilm", CLP, 500)
status(Do, P1, "sent")
P2 = dup(Do, P1)["id"]
status(Do, P2, "accepted")
check(set(offers(Do)) == {P2} and offers(Do)[P2]["open_offer"] is False, "#1915: personal office: the newest version counts")
check(setcf(Do, P2, "no").ok and set(offers(Do)) == {P1} and offers(Do)[P1]["open_offer"] is True, "#1915: personal office: no on the newest, the sent one before counts")
check(setcf(Ek, P1, "no").status_code == 404 and setcf(A, P1, "no").status_code == 404, "#1915: nobody else reaches the personal quotation (404)")
check(not any(e.get("doc_id") in (P1, P2) for e in A.get(B + O + f"/cashflow?from={M0}&months=6").json()["entries"]), "#1915: the organisation's plan has none of them")

# ---------------------------------------------------------------- agents
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "office"], "org_id": ORG})
check(r.status_code == 201, "setup: a personal agent " + r.text[:200])
AG = r.json()["id"]
AH = {**H, "Authorization": "Bearer " + r.json()["token"]}
A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True})
A.put(B + O + "/settings", json={"agents_read": 1})
V = B + "/api/v1/office"
r = requests.get(V + "/docs", headers=AH, params={"kind": "offer"})
row = [x for x in r.json().get("data", []) if x["id"] == Q3] if r.ok else []
check(row and row[0]["version_of"] == Q1 and row[0]["cashflow"] == "yes", "#1915: v1 list of quotations with version_of / cashflow " + r.text[:200])
r = requests.get(V + f"/docs/{Q2}", headers=AH)
check(r.ok and r.json()["version_of"] == Q1 and r.json()["cashflow"] == "auto" and "cf_chain" in r.json(), "#1915: v1 document with the chain " + r.text[:200])
r = requests.post(V + "/offers", headers=AH, json={"client_id": CL, "title": "Agentenentwurf", "items": [{"text": "Schnitt", "qty": 1, "unit": "flat", "price": 300}]})
check(r.status_code == 201, "setup: an agent's draft " + r.text[:200])
AQ = r.json()["doc"]["id"]
r = requests.patch(V + f"/offers/{AQ}", headers=AH, json={"cashflow": "no"})
check(r.ok and r.json()["doc"]["cashflow"] == "no", "#1915: the agent sets cashflow of its own draft " + r.text[:200])
check(requests.patch(V + f"/offers/{AQ}", headers=AH, json={"cashflow": "always"}).status_code == 400, "#1915: agent: a bad value 400")
check(requests.patch(V + f"/offers/{Q3}", headers=AH, json={"cashflow": "no"}).status_code in (403, 409), "#1915: agent: not a person's quotation")
check(requests.post(B + f"{D}/{Q3}/cashflow", headers=AH, json={"cashflow": "no"}).status_code in (401, 403), "#1915: an agent token never reaches the app route")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
