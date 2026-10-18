#!/usr/bin/env python3
"""2.94.0 API tests, part A (#1930): leads before the sales pipeline, own container (start.sh, org encryption on).
Invented companies, people and figures only.
 - the stage lead (preset 10 %) with source, next step, follow-up day, company, e-mail, phone (checked, the contact data
   encrypted at rest); leads never count in the open / weighted sums or the forecast, only as leads / leads_due
 - convert: a new client from the lead (stage inquiry, the person as contact person) or an existing one (offered by
   e-mail / company name; another area's client refused); the undo back to lead removes a client made by the conversion
   only while nothing else uses it
 - CSV import: German headers, preview without storing, duplicates by e-mail (pipeline + earlier rows) skipped, rows with
   errors skipped, an unknown source kept in the note; take over + undo (into the bin); no name column / too many rows 400
 - lead_from_booking (part B's hook): a lead with the source booking for an admin of the area, no twin for the same
   e-mail, None for a member, a person of another area or a personal office of somebody else
 - agents (scope office, the switches of the office): list / add / change next step, follow-up day, note; never convert,
   never another field, not for a member, a converted deal 409; every request in the office log
 - rights (tenant-matrix: office): a member 403, a kid 403, another organisation 404 everywhere; a person without
   organisation (freelancer-matrix: office) has leads, convert (a private client) and import in the personal office,
   nobody else reaches them
usage: p294_a_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time
from datetime import timedelta

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
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


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def py_in_app(code):
    """Runs Python inside the app container with the app imported (part B's hook lead_from_booking, a guest's request)."""
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-400:]


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
if not os.environ.get("P294A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Frei"), ("erik", "Erik Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
r = A.post(B + "/api/users", json={"username": "kim", "display_name": "Kim Kid", "password": "password123", "kid": True})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do, Er, Ki = sess("bob"), sess("carol"), sess("dora"), sess("erik"), sess("kim")
FEAT = "cal,comments,collab,office,clients,agents"
for s in (A, Bo, Ca, Do, Er, Ki):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
DORA = Do.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
O = "/api/office"
P = O + "/deals"
T0 = testclock.today()
TODAY = T0.isoformat()
D = lambda n: (T0 + timedelta(days=n)).isoformat()  # noqa: E731

# ---------------------------------------------------------------- tenant-matrix: office -- the stage lead
j = A.get(B + P).json()
check(j["stages"][0] == "lead" and j["probabilities"].get("lead") == 10 and "booking" in j.get("sources", []),
      f"#1930: the stage lead before inquiry, preset 10 %, the sources {j.get('stages')} {j.get('probabilities')}")
r = A.post(B + P, json={"title": "Musterbau GmbH", "stage": "lead", "contact": "Frau Beispiel", "company": "Musterbau GmbH",
                        "email": "lead1@example.com", "phone": "+49 30 1234567", "source": "website", "next_step": "Call back on Monday",
                        "follow_up": D(-1), "value": "5000", "note": "Met at the fair"})
check(r.status_code == 201, f"#1930: a lead added ({r.status_code} {r.text[:200]})")
L1 = r.json()
check(L1["stage"] == "lead" and L1["probability"] == 10 and L1["source"] == "website" and L1["next_step"] == "Call back on Monday"
      and L1["follow_up"] == D(-1) and L1["email"] == "lead1@example.com" and L1["company"] == "Musterbau GmbH", f"#1930: the lead's fields {L1}")
row = sql("SELECT email, phone, company, next_step, source FROM office_deals WHERE id=?", (L1["id"],))[0]
check(all(str(x).startswith("kenc1:") for x in row[:4]) and row[4] == "website", f"#1930: e-mail, phone, company, next step encrypted at rest {row}")
for bad in ({"source": "fax"}, {"email": "not-a-mail"}, {"follow_up": "18.10.2026"}, {"next_step": 5}):
    r = A.post(B + P, json={"title": "Bad", "stage": "lead", **bad})
    check(r.status_code == 400, f"#1930: wrong field {bad}: 400 ({r.status_code})")
L2 = A.post(B + P, json={"title": "Beispiel Werbung", "stage": "lead", "contact": "Herr Muster", "company": "Beispiel Werbung KG",
                         "email": "lead2@example.com", "follow_up": D(5)}).json()
r = A.patch(B + f"{P}/{L2['id']}", json={"next_step": "Send the showreel", "follow_up": D(3)})
check(r.ok and r.json()["next_step"] == "Send the showreel" and r.json()["before"].get("follow_up") == D(5), f"#1930: edit a lead (before = undo) {r.text[:200]}")
s = A.get(B + P).json()["summary"]
check(s["open"] == "0.00" and s["weighted"] == "0.00" and s["count_open"] == 0 and s["leads"] == 2 and s["leads_due"] == 1
      and all(f["weighted"] == "0.00" for f in s["forecast"]), f"#1930: leads never count in the sums or the forecast, only as leads {s}")
check(A.get(B + P + "/summary").json()["summary"]["open"] == "0.00", "#1930: the summary route neither")

# rights
check(Bo.get(B + P).status_code == 403 and Bo.post(B + f"{P}/{L1['id']}/convert", json={}).status_code == 403
      and Bo.post(B + O + "/leads/import", json={"text": "Name\nX"}).status_code == 403, "#1930: a member: 403")
check(Ki.get(B + P).status_code == 403 and Ki.post(B + f"{P}/{L1['id']}/convert", json={}).status_code == 403, "#1930: a kid: 403")
for m, path in (("GET", f"{P}/{L1['id']}/convert"), ("POST", f"{P}/{L1['id']}/convert"), ("POST", f"{P}/{L1['id']}/unconvert"), ("PATCH", f"{P}/{L1['id']}")):
    check(Ca.request(m, B + path, json={}).status_code == 404, f"#1930: another organisation: {m} {path} 404")
check(Ca.post(B + O + "/leads/import/undo", json={"ids": [L1["id"]]}).json().get("count") == 0 and A.get(B + P).json()["summary"]["leads"] == 2,
      "#1930: another organisation's import undo reaches nothing")

# ---------------------------------------------------------------- convert + undo
CL = A.post(B + "/api/clients", json={"name": "Beispiel Werbung KG", "email": "lead2@example.com", "org_id": ORG}).json()["id"]
CLX = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG", "org_id": ORG2}).json()["id"]
m = A.get(B + f"{P}/{L2['id']}/convert").json()["matches"]
check([x["id"] for x in m] == [CL] and m[0]["same_email"] is True, f"#1930: an existing client with the lead's e-mail is offered {m}")
check(A.get(B + f"{P}/{L1['id']}/convert").json()["matches"] == [], "#1930: no fitting client: no offer")
r = A.post(B + f"{P}/{L1['id']}/convert", json={})
check(r.ok and r.json()["client_new"] is True and r.json()["deal"]["stage"] == "inquiry" and r.json()["deal"]["probability"] == 20
      and r.json()["deal"]["client_name"] == "Musterbau GmbH", f"#1930: convert into a new client {r.text[:300]}")
NC = r.json()["client_id"]
cl = A.get(B + f"/api/clients/{NC}").json()
check(cl.get("email") == "lead1@example.com" and cl.get("org_id") == ORG, f"#1930: the client of the organisation with the lead's data {cl.get('email')} {cl.get('org_id')}")
check(sql("SELECT COUNT(*) FROM office_client_contacts WHERE client_id=?", (NC,))[0][0] == 1, "#1930: the lead's person as contact person")
check(A.post(B + f"{P}/{L1['id']}/convert", json={}).status_code == 409, "#1930: a converted deal is no lead any more (409)")
r = A.post(B + f"{P}/{L1['id']}/unconvert", json={"remove_client": True})
check(r.ok and r.json()["client_removed"] is True and r.json()["deal"]["stage"] == "lead" and r.json()["deal"]["client_id"] is None
      and r.json()["deal"]["probability"] == 10, f"#1930: undo: back to lead, the new client removed {r.text[:300]}")
check(A.get(B + f"/api/clients/{NC}").status_code == 404, "#1930: the client made by the conversion is gone")
check(A.post(B + f"{P}/{L1['id']}/unconvert", json={}).status_code == 409, "#1930: undo of a lead: 409")
check(A.post(B + f"{P}/{L2['id']}/convert", json={"client_id": CLX}).status_code == 400, "#1930: another organisation's client refused")
r = A.post(B + f"{P}/{L2['id']}/convert", json={"client_id": CL})
check(r.ok and r.json()["client_new"] is False and r.json()["deal"]["client_id"] == CL, f"#1930: convert with the existing client {r.text[:200]}")
r = A.post(B + f"{P}/{L2['id']}/unconvert", json={"remove_client": True})
check(r.ok and r.json()["client_removed"] is False and A.get(B + f"/api/clients/{CL}").ok, "#1930: an existing client stays on undo")
# a new client used by another deal meanwhile stays on undo
r = A.post(B + f"{P}/{L1['id']}/convert", json={})
NC2 = r.json()["client_id"]
SJ = A.post(B + P, json={"title": "Second job", "client_id": NC2}).json()["id"]
r = A.post(B + f"{P}/{L1['id']}/unconvert", json={"remove_client": True})
check(r.ok and r.json()["client_removed"] is False and A.get(B + f"/api/clients/{NC2}").ok, "#1930: a client in use stays on undo")

# ---------------------------------------------------------------- CSV import
CSV = ("Name;Firma;E-Mail;Telefon;Quelle;Nächster Schritt;Wiedervorlage;Notiz;Wert\n"
       "Anna Beispiel;Beispiel Studio;anna@example.com;+49 40 111;referral;Anrufen;20.11.2026;Kennt uns über Tom;1.200,50\n"
       "Ben Muster;;lead2@example.com;;;;;;\n"
       "Cleo Test;Test AG;cleo@example.com;;Messe 2026;;2026-12-01;;\n"
       "Cleo Zwei;Test AG;CLEO@example.com;;;;;;\n"
       ";;;;;;;;\n"
       "Dan Falsch;;dan(at)example.com;;;;;;\n"
       "Eva Datum;;eva@example.com;;;;31.02.2026;;\n")
r = A.post(B + O + "/leads/import", json={"text": CSV})
pv = r.json()
check(r.ok and pv["count"] == 2 and pv["dup_count"] == 2 and pv["skipped"] == 2 and pv["columns"].get("email") == "E-Mail"
      and pv["columns"].get("follow_up") == "Wiedervorlage", f"#1930: the preview (2 new, 2 duplicates, 2 errors) {r.text[:400]}")
rows = {x["contact"]: x for x in pv.get("rows", [])}
a = rows.get("Anna Beispiel", {})
check(a.get("source") == "referral" and a.get("follow_up") == "2026-11-20" and a.get("value") == "1200.50" and a.get("contact") == "Anna Beispiel",
      f"#1930: a row read (source, German date, German amount) {a}")
c3 = rows.get("Cleo Test", {})
check(c3.get("source") == "import" and "Messe 2026" in c3.get("note", ""), f"#1930: an unknown source kept in the note {c3}")
check(A.get(B + P).json()["summary"]["leads"] == 2, "#1930: the preview stores nothing")
r = A.post(B + O + "/leads/import", json={"text": CSV, "commit": True})
check(r.status_code == 201 and r.json()["count"] == 2 and len(r.json()["ids"]) == 2, f"#1930: take over {r.text[:200]}")
IDS = r.json()["ids"]
its = {x["id"]: x for x in A.get(B + P).json()["items"]}
check(all(its[i]["stage"] == "lead" and its[i]["probability"] == 10 for i in IDS) and its[IDS[0]]["value"] == "1200.50", "#1930: imported as leads")
r = A.post(B + O + "/leads/import", json={"text": CSV, "commit": True})
check(r.status_code == 400, f"#1930: the same file again: nothing new (400) ({r.status_code})")
r = A.post(B + O + "/leads/import/undo", json={"ids": IDS})
check(r.ok and r.json()["count"] == 2 and not any(x["id"] in IDS for x in A.get(B + P).json()["items"]), "#1930: undo = the imported leads into the bin")
check(sql("SELECT COUNT(*) FROM office_deals WHERE id IN (?, ?) AND deleted_at IS NOT NULL", tuple(IDS))[0][0] == 2, "#1930: in the bin, not deleted")
check(A.post(B + O + "/leads/import", json={"text": "Datum;Betrag\n2026-01-01;5"}).status_code == 400, "#1930: no name / company / e-mail column: 400")
check(A.post(B + O + "/leads/import", json={"text": "Name\n" + "\n".join(f"P{i}" for i in range(1001))}).status_code == 400, "#1930: more than 1000 rows: 400")
check(A.post(B + O + "/leads/import", json={"text": ""}).status_code == 400, "#1930: an empty file: 400")
check(A.post(B + O + "/leads/import/undo", json={"ids": "x"}).status_code == 400, "#1930: undo needs ids")

# ---------------------------------------------------------------- part B's hook lead_from_booking (a guest's request)
Do.get(B + P)  # makes Dora's personal office
POID = sql("SELECT id FROM orgs WHERE personal_of=?", (DORA,))[0][0]


def booking(oid, uid, email="guest@example.com", fu=""):
    return py_in_app("from kalmido.core.config import app as F\nfrom kalmido.core.db import db\nfrom kalmido.office.leads import lead_from_booking\n"
                     f"with F.test_request_context('/book/x'):\n    c = db()\n    d = lead_from_booking(c, {oid}, {uid}, 'Gina Gast', {email!r}, '+49 1', 'Wants a film', follow_up={fu!r})\n"
                     "    c.commit()\n    print(json.dumps(d))")


out = booking(ORG, ALICE, fu=D(7))
check(out.isdigit(), f"#1930: lead_from_booking for an admin of the area: a deal id ({out})")
if out.isdigit():
    x = next((i for i in A.get(B + P).json()["items"] if i["id"] == int(out)), {})
    check(x.get("stage") == "lead" and x.get("source") == "booking" and x.get("follow_up") == D(7) and x.get("email") == "guest@example.com"
          and x.get("contact") == "Gina Gast" and x.get("note") == "Wants a film", f"#1930: the booking's lead {x}")
    check(booking(ORG, ALICE) == out, "#1930: the same e-mail again: no twin, the same lead")
check(booking(ORG, BOB, "b2@example.com") == "null", "#1930: lead_from_booking for a member: None")
check(booking(ORG, CAROL, "b3@example.com") == "null", "#1930: for a person of another organisation: None")
check(booking(POID, ALICE, "b4@example.com") == "null", "#1930: for somebody else's personal office: None")
check(booking(0, ALICE) == "null", "#1930: without an office area: None")
out = booking(POID, DORA, "b5@example.com")
check(out.isdigit() and any(i["id"] == int(out) and i["follow_up"] == TODAY for i in Do.get(B + P).json()["items"]),
      f"#1930: a personal office: the owner's lead, follow-up today by default ({out})")

# ---------------------------------------------------------------- agents
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "leadbot", "display_name": "Lead Bot", "scopes": ["read", "office"], "org_id": ORG})
assert r.ok, r.text
AG, AH = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
r = A.post(B + "/api/my/agents", json={"username": "plainbot", "display_name": "Plain Bot", "scopes": ["read"], "org_id": ORG})
PH = {**H, "Authorization": "Bearer " + r.json()["token"]}


def ag(m, path, h=None, **kw):
    return requests.request(m, B + "/api/v1/office" + path, headers=h or AH, **kw)


check(ag("GET", "/leads").status_code == 403, "#1930: agent: its office switch off: 403")
A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True})
check(ag("GET", "/leads").status_code == 403, "#1930: agent: the area's privacy switch off: 403")
A.put(B + O + "/settings", json={"agents_read": 1})
r = ag("GET", "/leads")
data = r.json().get("data", [])
check(r.ok and {L1["id"], L2["id"]} <= {x["id"] for x in data} and all("value" not in x and "probability" not in x for x in data),
      f"#1930: agent lists the leads, without values {r.text[:300]}")
check(all(x["id"] != SJ for x in data) and all(x.get("app_url") == "#office/pipeline" for x in data), "#1930: agent: only leads")
r = ag("GET", "/leads", params={"due": "1"})
check(r.ok and L1["id"] in [x["id"] for x in r.json()["data"]] and L2["id"] not in [x["id"] for x in r.json()["data"]], "#1930: agent: due = the follow-up day has come")
check(ag("GET", "/leads", h=PH).status_code == 403, "#1930: agent without the scope office: 403")
check(ag("GET", "/leads", params={"requested_by": BOB}).status_code in (403, 404), "#1930: agent acting for a member: refused")
r = ag("POST", "/leads", json={"contact": "Hanna Hinweis", "company": "Hinweis GmbH", "email": "hanna@example.com", "next_step": "Ask for a date"})
check(r.status_code == 201 and r.json()["source"] == "agent" and r.json()["title"] == "Hinweis GmbH", f"#1930: agent adds a lead (source agent) {r.text[:200]}")
AL = r.json()["id"]
x = next(i for i in A.get(B + P).json()["items"] if i["id"] == AL)
check(x["stage"] == "lead" and x["probability"] == 10, "#1930: an agent's lead is a lead")
check(ag("POST", "/leads", json={"title": "X", "stage": "won"}).status_code == 400, "#1930: agent: no other stage (unknown field 400)")
check(ag("POST", "/leads", json={"title": "X", "value": 100}).status_code == 400, "#1930: agent: no value")
r = ag("PATCH", f"/leads/{AL}", json={"next_step": "Send the quotation", "follow_up": D(2), "note": "Prefers mail"})
check(r.ok and r.json()["next_step"] == "Send the quotation" and r.json()["follow_up"] == D(2), f"#1930: agent changes next step / follow-up / note {r.text[:200]}")
check(ag("PATCH", f"/leads/{AL}", json={"title": "Renamed"}).status_code == 400, "#1930: agent: no other field")
check(ag("PATCH", "/leads/99999999", json={"note": "x"}).status_code == 404, "#1930: agent: an unknown id 404")
A.post(B + f"{P}/{AL}/convert", json={})
check(ag("PATCH", f"/leads/{AL}", json={"note": "x"}).status_code == 409, "#1930: agent: a converted deal: 409")
check(requests.post(B + f"{P}/{L2['id']}/convert", headers=AH, json={}).status_code in (401, 403)
      and requests.delete(B + f"{P}/{L2['id']}", headers=AH).status_code in (401, 403), "#1930: an agent never converts or deletes")
check(sql("SELECT COUNT(*) FROM office_doc_log WHERE org_id=? AND user_id=? AND target='leads'", (ORG, AG))[0][0] >= 4, "#1930: agent requests in the office log")
r = ag("GET", "/leads")
check(all(x["id"] != AL for x in r.json()["data"]), "#1930: a converted lead is gone from the agent's list")
r = requests.get(B + "/api/v1/openapi.json", headers=AH)
if r.ok:
    pth = r.json().get("paths", {})
    check(pth.get("/office/leads", {}).get("get", {}).get("x-kalmido-scope") == "office" and "/office/leads/{id}" in pth, "#1930: OpenAPI with scope office")

# ---------------------------------------------------------------- freelancer-matrix: office -- a person without organisation
r = Do.post(B + P, json={"title": "Freie Anfrage", "stage": "lead", "contact": "Ida Idee", "email": "ida@example.com", "source": "social"})
check(r.status_code == 201, f"#1930: personal office: a lead ({r.status_code})")
DL = r.json()["id"]
check(A.get(B + f"{P}/{DL}/convert").status_code == 404 and Er.post(B + f"{P}/{DL}/convert", json={}).status_code == 404
      and Er.patch(B + f"{P}/{DL}", json={"title": "x"}).status_code == 404, "#1930: personal office: nobody else reaches the lead")
r = Do.post(B + f"{P}/{DL}/convert", json={})
check(r.ok and r.json()["client_new"], f"#1930: personal office: convert {r.text[:200]}")
DC = r.json()["client_id"]
check(tuple(sql("SELECT org_id, created_by FROM clients WHERE id=?", (DC,))[0]) == (None, DORA),
      "#1930: personal office: a private client")
r = Do.post(B + f"{P}/{DL}/unconvert", json={"remove_client": True})
check(r.ok and r.json()["client_removed"], "#1930: personal office: undo removes the private client")
r = Do.post(B + O + "/leads/import", json={"text": "Name,Email\nJo Jung,jo@example.com\nIda Idee,ida@example.com\n", "commit": True})
check(r.status_code == 201 and r.json()["count"] == 1 and r.json()["dup_count"] == 1, f"#1930: personal office: import (a duplicate skipped) {r.text[:200]}")
check(Er.post(B + O + "/leads/import/undo", json={"ids": r.json()["ids"]}).json().get("count") == 0, "#1930: personal office: another person's undo reaches nothing")
check(all(x["id"] != DL for x in A.get(B + P).json()["items"]) and all(x["id"] != DL for x in Er.get(B + P).json()["items"]),
      "#1930: personal office: the leads show nowhere else")
r = Do.post(B + "/api/my/agents", json={"username": "dorabot", "display_name": "Dora Bot", "scopes": ["read", "office"]})
DH = {**H, "Authorization": "Bearer " + r.json()["token"]}
Do.patch(B + f"{O}/agents/{r.json()['id']}", json={"office_drafts": True})
Do.put(B + O + "/settings", json={"agents_read": 1})
r = ag("GET", "/leads", h=DH)
check(r.ok and DL in [x["id"] for x in r.json()["data"]] and L1["id"] not in [x["id"] for x in r.json()["data"]], f"#1930: personal office: the own agent lists its leads {r.text[:200]}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
