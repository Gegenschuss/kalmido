#!/usr/bin/env python3
"""2.154.0 API tests, part B (#1960): e-invoices over the Peppol network through the office's own provider account. Own container
(start.sh) with a stand-in provider inside (stub_peppol.py, port 8098: no real provider is called); invented names only.
 - Peppol ids: the client field peppol_id is checked (unknown scheme, wrong check digit of 0208 / 0088 -> 400) and normalised
   (spaces, the participant prefix iso6523-actorid-upis::); the own id is suggested from the company's VAT id (9930:DE...)
 - the connection (GET / PUT /api/office/peppol, POST .../check): a member reads but cannot change (403); the API key is never
   in an answer (key_set only) nor in plain text in the database; a wrong key -> check_state auth, the right one ok; a new
   provider without a new key drops the stored one; an http address of a host that is not allowed -> 400
 - a draft has no UBL (409); the finalised invoice's UBL carries the Peppol BIS 3.0 profile and both EndpointIDs
 - Storecove face: send -> 201, status sent, the document went with the legal entity, the routing scheme BE:EN, the raw UBL to
   parse and the key as bearer; the invoice becomes "sent", the office log has peppol_send, the document answer (and an agent's
   v1 answer) carries peppol.status; sending twice -> 409; refresh -> still sent, then delivered (log peppol_status)
 - an unreachable recipient -> 409 and nothing recorded; missing pieces are named (no client id, no setup)
 - own endpoint (organisation Beta): send -> sent, refresh -> rejected with the provider's message, without "again" 409, with
   again a new send; a provider failure (500) -> 502, the send recorded as error with the text
 - the organisation boundary (tenant-matrix: office): Beta does not see / send Alpha's document (404), an agent token gets 403
 - a person without an organisation (freelancer-matrix: office) sets up the connection in the personal office and sends
usage: p2154_b_peppol_test.py <datadir>      (P2154B_NOSTART=1 = the server already runs, with the stub on port 8098)"""
import base64
import json
import os
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
O = "/api/office"
D = O + "/docs"
FEAT = "cal,comments,collab,office,clients"
STUB = "http://127.0.0.1:8098"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "email": "hallo@beispiel.example",
           "phone": "+49 30 000000", "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
BE_ID = "0208:0123456749"


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


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def stub_log():
    p = os.path.join(DATA, "peppol.log")
    return [json.loads(x) for x in open(p).read().splitlines()] if os.path.exists(p) else []


def stub_file(name, content):
    subprocess.run(["docker", "exec", CT, "sh", "-c", f"cat > /data/{name}"], input=content.encode(), check=True)


if os.environ.get("P2154B_NOSTART") != "1":
    extra = ["-e KALMIDO_INSTANCE_MODE=workspaces", "-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098",
             f"-e KALMIDO_PEPPOL_STORECOVE_URL={STUB}/sc/api/v2"]
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(extra)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "cp", os.path.join(N, "stub_peppol.py"), f"{CT}:/tmp/stub_peppol.py"], check=True)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/tmp/stub_peppol.py"], check=True)
    time.sleep(1.2)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
assert A.put(B + O + "/settings", json={"lang": "de", "company_fields": COMPANY}).ok
assert Ca.put(B + O + "/settings", json={"lang": "de", "company_fields": dict(COMPANY, name="Andere Firma AG", vat_id="DE987654321")}).ok


def client(s, name, **kw):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Marktstraat 5", "zip": "1000", "city": "Brussel", "country": "BE",
                                         "vat_id": "BE0123456749", "customer_no": "K-7", **kw})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def invoice(s, cl, finalise=True):
    r = s.post(B + D, json={"kind": "invoice", "lang": "de", "client_id": cl, "project_title": "Schnitt", "service_from": "2026-05-01",
                            "items": [{"title": "Schnitt", "qty": 2, "rate": 450}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if finalise:
        f = s.post(B + f"{D}/{did}/finalize")
        assert f.ok, f.text
    return did


def view(s, did, refresh=False):
    return s.get(B + f"{D}/{did}/peppol" + ("?refresh=1" if refresh else ""))


# ---------------------------------------------------------------- Peppol ids at the client
CL = client(A, "Beispielkunde NV")
for bad in ("1234:abc", "0208:0123456748", "0088:4000001000004", "DE123456789", "9930:DE12345"):
    check(A.patch(B + f"/api/clients/{CL}", json={"peppol_id": bad}).status_code == 400, f"invalid Peppol id refused: {bad}")
r = A.patch(B + f"/api/clients/{CL}", json={"peppol_id": "iso6523-actorid-upis::0208:0123 456 749"})
check(r.ok and r.json()["billing"]["peppol_id"] == BE_ID, f"Peppol id normalised: {r.text[:200]}")
check(A.patch(B + f"/api/clients/{CL}", json={"peppol_id": "9930:de123456789"}).json()["billing"]["peppol_id"] == "9930:DE123456789", "VAT-based id upper case")
A.patch(B + f"/api/clients/{CL}", json={"peppol_id": BE_ID})

# ---------------------------------------------------------------- the connection
g = A.get(B + O + "/peppol").json()
check(g["provider"] == "" and not g["key_set"] and g["can_edit"] and g["sender_suggest"] == "9930:DE123456789", f"defaults + suggestion: {g}")
check({p["id"] for p in g["providers"]} == {"storecove", "custom"}, "providers: Storecove and an own endpoint")
DID = invoice(A, CL)
v = view(A, DID).json()
check(not v["can_send"] and "setup" in [m["key"] for m in v["missing"]] and "sender" in [m["key"] for m in v["missing"]], f"missing pieces named: {v['missing']}")
check(Bo.get(B + O + "/peppol").json()["can_edit"] is False, "a member reads the connection without edit")
check(Bo.put(B + O + "/peppol", json={"provider": "storecove"}).status_code == 403, "a member cannot set it up")
check(A.put(B + O + "/peppol", json={"sender_id": "0208:0000000000"}).status_code == 400, "own id checked")
check(A.put(B + O + "/peppol", json={"nope": 1}).status_code == 400, "unknown field refused")
r = A.put(B + O + "/peppol", json={"provider": "storecove", "account": "1234", "api_key": "bad-key", "sender_id": "9930:DE123456789", "sandbox": 1})
check(r.ok and r.json()["key_set"] and "bad-key" not in r.text and r.json()["ready"], f"set up, key never answered: {r.text[:200]}")
sec = dbx("SELECT secret FROM office_peppol WHERE org_id=?", (ORG,))
check(sec and sec[0][0] and "bad-key" not in sec[0][0], "the key is sealed in the database")
r = A.post(B + O + "/peppol/check")
check(r.ok and not r.json()["ok"] and r.json()["check_state"] == "auth", f"a wrong key: auth: {r.text[:200]}")
A.put(B + O + "/peppol", json={"api_key": "good-key"})
r = A.post(B + O + "/peppol/check")
check(r.ok and r.json()["ok"] and r.json()["check_state"] == "ok", f"the right key: ok: {r.text[:200]}")
check(any(x["path"] == "/sc/api/v2/legal_entities/1234" and x["auth"] == "Bearer good-key" for x in stub_log()), "the check asks for the legal entity with the key")
check(A.put(B + O + "/peppol", json={"provider": "custom", "endpoint_url": "http://example.com/peppol"}).status_code == 400, "http only for an allowed host")
r = A.put(B + O + "/peppol", json={"provider": "custom", "endpoint_url": "https://ap.example.com/peppol"})
check(r.ok and not r.json()["key_set"], "another provider without a new key drops the stored key")
A.put(B + O + "/peppol", json={"provider": "storecove", "account": "1234", "api_key": "good-key"})

# ---------------------------------------------------------------- UBL + send (Storecove face)
DRAFT = invoice(A, CL, finalise=False)
check(A.get(B + f"{D}/{DRAFT}/ubl").status_code == 409, "a draft has no UBL")
check("kind" in [m["key"] for m in view(A, DRAFT).json()["missing"]], "a draft is not sendable")
r = A.get(B + f"{D}/{DID}/ubl")
x = r.text
check(r.ok and "urn:fdc:peppol.eu:2017:poacc:billing:3.0" in x and 'schemeID="9930">DE123456789<' in x and 'schemeID="0208">0123456749<' in x,
      f"UBL with the Peppol profile and both ids: {x[:300]}")
v = view(A, DID).json()
check(v["can_send"] and not v["missing"] and v["receiver_id"] == BE_ID and v["sandbox"] == 1, f"ready to send: {v}")
r = A.post(B + f"{D}/{DID}/peppol/lookup")
check(r.ok and r.json()["reachable"] is True, "lookup: reachable")
n0 = len(stub_log())
r = A.post(B + f"{D}/{DID}/peppol", json={})
check(r.status_code == 201 and r.json()["sends"][0]["status"] == "sent" and r.json()["sends"][0]["provider_ref"] == "g-1", f"sent: {r.text[:300]}")
sub = [x for x in stub_log()[n0:] if x["path"] == "/sc/api/v2/document_submissions"]
if sub:
    body = json.loads(base64.b64decode(sub[0]["body"]))
    raw = base64.b64decode(body["document"]["rawDocumentData"]["document"]).decode()
    check(body["legalEntityId"] == 1234 and body["routing"]["eIdentifiers"] == [{"scheme": "BE:EN", "id": "0123456749"}]
          and body["document"]["rawDocumentData"]["parseStrategy"] == "ubl" and sub[0]["auth"] == "Bearer good-key" and len(body["idempotencyGuid"]) == 36,
          f"the submission: {body.get('routing')} {body.get('legalEntityId')}")
    check("<cbc:ID>" in raw and "urn:fdc:peppol.eu:2017:poacc:billing:3.0" in raw, "the raw document is the UBL")
else:
    check(False, "the provider got the submission")
check(any(x["path"] == "/sc/api/v2/discovery/receives" for x in stub_log()[n0:]), "the recipient was looked up before sending")
doc = A.get(B + f"{D}/{DID}").json()
check(doc["status"] == "sent" and (doc.get("peppol") or {}).get("status") == "sent", f"the invoice is sent, the answer carries peppol: {doc.get('status')} {doc.get('peppol')}")
acts = [r[0] for r in dbx("SELECT action FROM office_doc_log WHERE doc_id=?", (DID,))]
check("peppol_send" in acts, f"office log peppol_send: {acts}")
check(A.post(B + f"{D}/{DID}/peppol", json={}).status_code == 409 and A.post(B + f"{D}/{DID}/peppol", json={"again": 1}).status_code == 409, "never twice")
v = view(A, DID, refresh=True).json()
check(v["sends"][0]["status"] == "sent" and v["sends"][0]["checked_at"], "refresh: still on its way")
stub_file("peppol_delivered", "1")
v = view(A, DID, refresh=True).json()
check(v["sends"][0]["status"] == "delivered" and not v["can_send"], f"refresh: delivered: {v['sends'][0]}")
check(dbx("SELECT COUNT(*) FROM office_doc_log WHERE doc_id=? AND action='peppol_status'", (DID,))[0][0] == 1, "office log peppol_status")

# unreachable recipient, missing client id
CLG = client(A, "Glas GmbH", peppol_id="0088:4000001000005")
DG = invoice(A, CLG)
n1 = dbx("SELECT COUNT(*) FROM office_peppol_sends")[0][0]
r = A.post(B + f"{D}/{DG}/peppol", json={})
check(r.status_code == 409 and "0088:4000001000005" in r.text, f"an unreachable recipient: 409: {r.text[:200]}")
check(dbx("SELECT COUNT(*) FROM office_peppol_sends")[0][0] == n1, "nothing recorded for an unreachable recipient")
CLN = client(A, "Ohne ID AG", vat_id="BE0987654321")
DN = invoice(A, CLN)
v = view(A, DN).json()
check("receiver" in [m["key"] for m in v["missing"]] and A.post(B + f"{D}/{DN}/peppol", json={}).status_code == 409, "the client without a Peppol id is named")

# ---------------------------------------------------------------- the organisation boundary (tenant-matrix: office) + agents
check(Ca.get(B + f"{D}/{DID}/peppol").status_code == 404 and Ca.post(B + f"{D}/{DID}/peppol", json={"again": 1}).status_code == 404
      and Ca.get(B + f"{D}/{DID}/ubl").status_code == 404 and Ca.post(B + f"{D}/{DID}/peppol/lookup").status_code == 404, "another organisation: 404")
check(Ca.get(B + O + "/peppol").json()["provider"] == "", "another organisation has its own (empty) connection")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "pepbot", "display_name": "Pep Bot", "scopes": ["read", "office"], "org_id": ORG})
if r.status_code == 201:
    AH = {**H, "Authorization": "Bearer " + r.json()["token"]}
    check(requests.post(B + f"{D}/{DID}/peppol", json={"again": 1}, headers=AH).status_code in (401, 403), "an agent never sends")
    check(requests.put(B + O + "/peppol", json={"provider": ""}, headers=AH).status_code in (401, 403), "an agent never sets up")
else:
    check(False, "setup: an agent " + r.text[:200])

# ---------------------------------------------------------------- own endpoint (Beta): rejected, again, provider failure
r = Ca.put(B + O + "/peppol", json={"provider": "custom", "endpoint_url": STUB + "/own", "api_key": "good-key", "sender_id": "9930:DE987654321", "sandbox": 0})
check(r.ok and r.json()["ready"], f"own endpoint set up: {r.text[:200]}")
check(Ca.post(B + O + "/peppol/check").json()["ok"], "own endpoint: check ok")
CL2 = client(Ca, "Kunde Beta NV", peppol_id=BE_ID)
D2 = invoice(Ca, CL2)
n2 = len(stub_log())
r = Ca.post(B + f"{D}/{D2}/peppol", json={})
check(r.status_code == 201 and r.json()["sends"][0]["status"] == "sent", f"own endpoint: sent: {r.text[:200]}")
post = [x for x in stub_log()[n2:] if x["path"] == "/own/documents"]
check(post and post[0]["sender"] == "9930:DE987654321" and post[0]["receiver"] == BE_ID and post[0]["test"] == "0" and post[0]["idem"]
      and b"<Invoice" in base64.b64decode(post[0]["body"]), "own endpoint: the UBL with sender / receiver headers")
v = view(Ca, D2, refresh=True).json()
check(v["sends"][0]["status"] == "rejected" and "Buyer rejected" in v["sends"][0]["message"] and v["can_retry"], f"rejected with the message: {v['sends'][0]}")
check(Ca.post(B + f"{D}/{D2}/peppol", json={}).status_code == 409, "after a rejection only on purpose")
r = Ca.post(B + f"{D}/{D2}/peppol", json={"again": 1})
check(r.status_code == 201 and len(r.json()["sends"]) == 2 and r.json()["sends"][0]["status"] == "sent", "send again: a new send")
CL3 = client(Ca, "Fehler GmbH", country="DE", vat_id="DE111111111", peppol_id="9930:DE111111111")
D3 = invoice(Ca, CL3)
r = Ca.post(B + f"{D}/{D3}/peppol", json={})
check(r.status_code == 502, f"provider failure: 502: {r.status_code} {r.text[:200]}")
v = view(Ca, D3).json()
check(v["sends"] and v["sends"][0]["status"] == "error" and v["sends"][0]["message"] and v["can_retry"], f"recorded as error: {v['sends']}")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
Fr.get(B + O + "/settings")
assert Fr.put(B + O + "/settings", json={"lang": "de", "company_fields": dict(COMPANY, name="Frida Film", vat_id="DE222222222")}).ok
g = Fr.get(B + O + "/peppol").json()
check(g["can_edit"] and g["sender_suggest"] == "9930:DE222222222", "freelancer: own admin, own suggestion")
r = Fr.put(B + O + "/peppol", json={"provider": "custom", "endpoint_url": STUB + "/own", "api_key": "good-key", "sender_id": g["sender_suggest"]})
check(r.ok and r.json()["ready"], "freelancer: set up")
FCL = client(Fr, "Frida Kunde NV", peppol_id=BE_ID)
FD = invoice(Fr, FCL)
r = Fr.post(B + f"{D}/{FD}/peppol", json={})
check(r.status_code == 201 and r.json()["sends"][0]["status"] == "sent", f"freelancer: sent: {r.text[:200]}")
check(Fr.get(B + f"{D}/{FD}/ubl").ok, "freelancer: UBL download")
check(A.get(B + f"{D}/{FD}/peppol").status_code == 404, "the freelancer's document is not Alpha's")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
