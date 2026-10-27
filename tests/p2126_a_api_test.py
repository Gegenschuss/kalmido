#!/usr/bin/env python3
"""2.126.0 API tests, part A: office and documents (#1966 #1967 #1970 #1971, #1979 F5-F7 L1-L7). Invented names only.
 - #1966: the next number of an invoice / credit note draft comes only at finalising (409), a numbered invoice draft is
   kept (409), an unnumbered one and a quotation draft can be deleted; also in the personal office
 - #1967: an invoice from times sums only the lists the person sees, also in the personal office
 - #1971 / #1970: the document tables in the encryption status, encrypt-all / decrypt-all, the personal space's document
   data on the account key and back (docs-to-server-key)
 - #1979: the duplicate starts a fresh reminder fee, a client with finalised invoices stays in the organisation, broken
   input gives 400 instead of 500
freelancer-matrix: office, files
usage: p2126_a_api_test.py <datadir>      (a fresh container; P2126A_NOSTART=1 = the server already runs)"""
import base64
import json
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,time,docs"
O = "/api/office"
D = O + "/docs"
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
KEY2 = base64.b64encode(os.urandom(32)).decode()


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def item(title, qty, rate, unit="day"):
    return {"kind": "service", "title": title, "qty": qty, "unit": unit, "rate": rate, "tax": "standard", "raw_fee": 0, "producing": 0,
            "intext": "intern", "cost": 0, "discountable": 1}


def start(key=KEY, keep=False):
    extra = ["-e KALMIDO_ORGCRYPT_DELAY=0", "-e KALMIDO_ORGCRYPT_PAUSE=0"] + (["-e KALMIDO_SECRET_KEY=" + key] if key else [])
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(extra), **({"KEEP": "1"} if keep else {}))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)


def cli(*args, stdin=None):
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args], input=stdin,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def status():
    rc, out = cli("status")
    assert rc == 0, out
    return json.JSONDecoder().raw_decode(out[out.index("{"):])[0]


if os.environ.get("P2126A_NOSTART") != "1":
    start(key=None)  # first without a server key (#1979 L5), the documents' part restarts with one
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
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Beispiel Studio GmbH", "street": "Musterweg 1",
                                                                                   "zip": "12345", "city": "Musterstadt", "country": "DE",
                                                                                   "tax_number": "12/345/67890", "iban": "DE02120300000000202051"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Kundenweg 5", "zip": "20000", "city": "Beispielstadt", "country": "DE"}).json()["id"]
FID, Fr = freelancer(B, A)
FC = Fr.post(B + "/api/clients", json={"name": "Privatkunde", "street": "Weg 1", "zip": "20000", "city": "Beispielstadt", "country": "DE"}).json()["id"]


# ================================================================ #1966 numbers of invoice drafts
def numbers_case(S, who, cl):
    inv = S.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": "2026-05-01", "items": [item("Beratung", 1, 100)]}).json()
    check(inv["number"] == "" and inv["number_at_finalize"], f"{who}: an invoice draft has no number yet")
    r = S.post(B + f"{D}/{inv['id']}/number", json={})
    check(r.status_code == 409, f"{who}: the next number of an invoice draft comes at finalising (409) " + r.text[:120])
    check(S.get(B + f"{D}/{inv['id']}").json()["number"] == "", f"{who}: still no number")
    # 2.354.0 (#2838): a credit note only from a finalised invoice (the numbers of its draft: below, after F5)
    check(S.post(B + D, json={"kind": "credit"}).status_code == 409, f"{who}: no credit note without an invoice (409)")
    r = S.post(B + f"{D}/{inv['id']}/number", json={"number": f"RE-{time.localtime().tm_year}-001"})
    check(r.ok, f"{who}: a manual number is still possible " + r.text[:160])
    d = S.get(B + f"{D}/{inv['id']}").json()
    # 2.162.0 A (#2603): test phase (INVOICE_DELETE_TESTPHASE) - the admin may delete it, but only by typing its number
    check(d["can_delete"] is True and d.get("delete_confirm") is True, f"{who}: a numbered invoice draft: delete only with its number (test phase)")
    r = S.delete(B + f"{D}/{inv['id']}")
    check(r.status_code == 409 and r.json().get("error"), f"{who}: a numbered invoice draft is kept without the number (409) " + r.text[:160])
    check(S.get(B + f"{D}/{inv['id']}").ok, f"{who}: and still there")
    off = S.post(B + D, json={"kind": "offer", "client_id": cl, "items": [item("Kamera", 1, 500)]}).json()
    check(bool(off["number"]) and off["can_delete"], f"{who}: a numbered quotation draft can still be deleted")
    check(S.delete(B + f"{D}/{off['id']}").ok, f"{who}: quotation draft deleted")
    return inv["id"]


INV1 = numbers_case(A, "org", CL)
FINV1 = numbers_case(Fr, "freelancer", FC)
check(Bo.delete(B + f"{D}/{INV1}").status_code == 403, "a member still gets 403")


# ================================================================ #1967 invoice from times: only the lists the person sees
def entry(user_id, list_id, start, end, secs, note):
    sql("INSERT INTO time_entries(user_id, list_id, task_title, start, \"end\", seconds, note, source, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user_id, list_id, "Schnitt", start, end, secs, note, "manual", end, end), write=True)


def list_for(S, name, cl):
    lid = S.post(B + "/api/lists", json={"name": name}).json()["id"]
    r = S.patch(B + f"/api/lists/{lid}", json={"client_id": cl})
    assert r.ok, r.text
    return lid


def titles(S, doc):
    return sorted(x["title"] for x in S.get(B + f"{D}/{doc}").json()["items"] if x["kind"] == "service")


LA = list_for(A, "Alices Liste", CL)
LB = list_for(Bo, "Bobs Liste", CL)
entry(ALICE, LA, "2026-05-04T08:00:00Z", "2026-05-04T10:00:00Z", 7200, "Konzept")
entry(BOB, LB, "2026-05-05T08:00:00Z", "2026-05-05T09:00:00Z", 3600, "Schnitt")
check(LA not in [x["id"] for x in Bo.get(B + "/api/state").json()["lists"]], "setup: the member does not see the admin's list")
r = Bo.post(B + D + "/from-time", json={"client_id": CL, "from": "2026-05-01", "to": "2026-05-31"})
check(r.status_code == 201 and titles(Bo, r.json()["id"]) == ["Bobs Liste"], "org: only the lists the member sees are summed " + r.text[:200])
FL = list_for(Fr, "Privatprojekt", FC)
entry(FID, FL, "2026-05-04T08:00:00Z", "2026-05-04T09:30:00Z", 5400, "Konzept")
r = Fr.post(B + D + "/from-time", json={"client_id": FC, "from": "2026-05-01", "to": "2026-05-31"})
check(r.status_code == 201, "freelancer: invoice from times " + r.text[:200])
if r.status_code == 201:
    it = [x for x in Fr.get(B + f"{D}/{r.json()['id']}").json()["items"] if x["kind"] == "service"]
    check([x["title"] for x in it] == ["Privatprojekt"] and float(it[0]["qty"]) == 1.5, f"freelancer: the private list's hours are summed {it}")
check(Fr.post(B + D + "/from-time", json={"client_id": CL, "from": "2026-05-01", "to": "2026-05-31"}).status_code == 404, "freelancer: an organisation's client 404")


# ================================================================ #1979 F5-F7, L1, L4, L5, L7
r = A.post(B + f"{D}/{INV1}/finalize")
check(r.ok and r.json()["locked"], "F5: an invoice with a manual number is finalised " + r.text[:200])
cr = A.post(B + f"{D}/{INV1}/credit").json()  # 2.354.0 (#2838): was a free credit note draft in numbers_case
check(A.post(B + f"{D}/{cr['id']}/number").status_code == 409, "org: a credit note draft has no number before finalising either")
r = A.delete(B + f"{D}/{cr['id']}")
check(r.ok, "org: an unnumbered credit note draft can be deleted " + r.text[:120])
# F6: a copy starts with a fresh reminder fee state and without the agent's marks
sql("UPDATE office_docs SET reminder_fee_state='paid', agent_id=?, list_id=? WHERE id=?", (ALICE, LA, INV1), write=True)
r = A.post(B + f"{D}/{INV1}/duplicate")
check(r.status_code == 201, "F6: duplicate " + r.text[:120])
row = sql("SELECT reminder_fee_state, agent_id, list_id, number FROM office_docs WHERE id=?", (r.json()["id"],))[0]
check(row[0] == "" and row[1] is None and row[2] is None and row[3] == "", f"F6: the copy starts fresh {list(row)}")
A.delete(B + f"{D}/{r.json()['id']}")
# F7: a client with finalised documents stays in the organisation
r = A.patch(B + f"/api/clients/{CL}", json={"org_id": None})
check(r.status_code == 409 and r.json().get("error"), "F7: a client with a finalised invoice is not moved to private (409) " + r.text[:160])
check(sql("SELECT org_id FROM clients WHERE id=?", (CL,))[0][0] == ORG, "F7: it is still in the organisation")
CL2 = A.post(B + "/api/clients", json={"name": "Kunde Zwei GmbH", "city": "Beispielstadt", "country": "DE"}).json()["id"]
r = A.patch(B + f"/api/clients/{CL2}", json={"org_id": None})
check(r.ok and sql("SELECT org_id FROM clients WHERE id=?", (CL2,))[0][0] is None, "F7: a client without finalised documents moves as before " + r.text[:120])
# L4: a rule's position must be a finite number
r = Fr.post(B + "/api/docs/rules", json={"ws": "private", "kind": "any", "match": "Probe", "sender": "Probe"})
RID = r.json()["id"]
for bad in ("Infinity", "NaN", "-Infinity"):
    r = Fr.patch(B + f"/api/docs/rules/{RID}", data='{"pos": %s}' % bad, headers={"Content-Type": "application/json"})
    check(r.status_code == 400, f"L4: pos {bad} = 400 ({r.status_code})")
check(Fr.patch(B + f"/api/docs/rules/{RID}", json={"pos": 3}).ok, "L4: a normal position")
Fr.delete(B + f"/api/docs/rules/{RID}")
# L5: without a server key a file that starts like a sealed one is refused at once (it could never be opened)
FPL = Fr.post(B + "/api/lists", json={"name": "Privat"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"list_id": FPL, "title": "Unterlagen"}).json()["id"]
r = Fr.post(B + f"/api/tasks/{FT}/attachments", files={"file": ("x.bin", b"KENC1\n" + b"\0" * 40, "application/octet-stream")})
check(r.status_code == 400 and r.json().get("error"), "L5: refused with a clear message (400) " + r.text[:160])
r = Fr.post(B + f"/api/tasks/{FT}/attachments", files={"file": ("a.txt", b"plain file\n", "text/plain")})
check(r.ok, "L5: a normal file is stored " + r.text[:120])
# L1: a household receipt the scanner locked is not handed out
r = Fr.post(B + "/api/budget/lists", json={})
BL = r.json()["list_id"]
E = Fr.post(B + f"/api/budget/{BL}/entries", json={"day": "2026-09-03", "amount": 10, "kind": "out", "title": "Bäckerei"}).json()["id"]
r = Fr.post(B + f"/api/budget/entries/{E}/files", files=[("file", ("beleg.txt", b"receipt\n", "text/plain"))])
BF = r.json()["files"][0]["id"]
check(Fr.get(B + f"/api/budget/files/{BF}").content == b"receipt\n", "L1: the receipt downloads")
sql("INSERT INTO upload_scan(kind, ref_id, ver, org_id, state, sig, why, created_at) VALUES('budget', ?, 0, NULL, 'infected', 'Test-Signature', '', '2026-10-20T00:00:00Z')",
    (BF,), write=True)
r = Fr.get(B + f"/api/budget/files/{BF}")
check(r.status_code == 403, f"L1: a locked receipt is not handed out ({r.status_code})")
# L7: a person's list of receipt suggestions (only documents they see)
r = Fr.get(B + "/api/v1/receipt-suggestions?state=all")
check(r.status_code in (200, 401, 403) and (r.status_code != 200 or r.json()["data"] == []), f"L7: the person's list answers ({r.status_code}) " + r.text[:120])

# ================================================================ #1971 / #1970 the documents' values (freelancer-matrix: files)
start(keep=True)  # now with a server key
A, Bo, Fr = sess("alice"), sess("bob"), sess("frida")
def doc_view(S, ws):
    j = S.get(B + "/api/docs/settings", params={"ws": ws}).json()
    return {"rules": [{k: v for k, v in x.items() if k not in ("id", "pos")} for x in j.get("rules") or []],
            "senders": sorted(x["name"] for x in j.get("senders") or [])}


def doc_data(S, ws, tag):
    r = S.post(B + "/api/docs/rules", json={"ws": ws, "kind": "any", "match": f"Rechnung {tag}", "sender": f"Versand {tag}"})
    assert r.status_code == 201, r.text
    r = S.post(B + "/api/docs/labels/sender", json={"ws": ws, "name": f"Absender {tag}", "ids": []})
    assert r.status_code == 201, r.text


def raw_rules(ws_prefix):
    return [x[0] for x in sql("SELECT data FROM doc_rules WHERE ws LIKE ? ORDER BY id", (ws_prefix + "%",))]


doc_data(Fr, "private", "eins")
doc_data(A, f"org:{ORG}", "zwei")
FV, AV = doc_view(Fr, "private"), doc_view(A, f"org:{ORG}")
check(FV["senders"] == ["Absender eins"] and FV["rules"] and FV["rules"][0].get("sender") == "Versand eins", f"freelancer: own rule and sender {FV}")
check(all(v.startswith("kenc1:") for v in raw_rules("u") + raw_rules("o")), "rules are sealed in both workspaces")
st = status()
check(st["docs"]["enc"] >= 4 and st["docs"]["plain"] == 0, f"status: the documents' values are counted {st.get('docs')}")
check(st["docs_account_key"] is True and st["docs"]["private"]["account_key"] >= 2 and st["docs"]["private"]["server_key"] == 0,
      f"#1970: private values on the account key {st['docs'].get('private')}")
rc, out = cli("decrypt-all")
check(rc == 0 and "still encrypted: 0" in out, "decrypt-all: nothing left sealed, also no document value " + out[-300:])
check(not any(v.startswith("kenc1:") for v in raw_rules("")), "decrypt-all: the rules are plain")
check(doc_view(Fr, "private") == FV and doc_view(A, f"org:{ORG}") == AV, "decrypt-all: everything reads the same")
doc_data(Fr, "private", "drei")  # written while the encryption is off
check(status()["docs"]["plain"] >= 6, "status: plain document values counted")
rc, out = cli("encrypt-all")
check(rc == 0, "encrypt-all " + out[-300:])
st = status()
check(st["docs"]["plain"] == 0 and st["docs"]["enc"] >= 6, f"encrypt-all: every document value sealed {st['docs']}")
FV = doc_view(Fr, "private")
check(FV["senders"] == ["Absender drei", "Absender eins"] and len(FV["rules"]) == 2, f"encrypt-all: the freelancer reads everything {FV}")
check(doc_view(A, f"org:{ORG}") == AV, "encrypt-all: the organisation reads everything")
# the way back for an older version and forward again
rc, out = cli("docs-to-server-key")
check(rc == 0 and '"left": 0' in out, "docs-to-server-key " + out[-300:])
st = status()
check(st["docs_account_key"] is False and st["docs"]["private"]["account_key"] == 0 and st["docs"]["private"]["server_key"] >= 4,
      f"docs-to-server-key: private values on the server-derived key {st['docs']['private']}")
check(doc_view(Fr, "private") == FV, "server-derived key: the same content")
doc_data(Fr, "private", "vier")  # sealed in the older form while the switch is off
FV = doc_view(Fr, "private")
check(status()["docs"]["private"]["account_key"] == 0, "switch off: new values in the older form")
rc, out = cli("docs-to-account-key")
check(rc == 0 and '"left": 0' in out, "docs-to-account-key " + out[-300:])
st = status()
check(st["docs_account_key"] is True and st["docs"]["private"]["server_key"] == 0, f"docs-to-account-key {st['docs']['private']}")
check(doc_view(Fr, "private") == FV, "account key: the same content")
# the start-up pass moves values of the older form
cli("docs-to-server-key")
sql("DELETE FROM settings WHERE key='docs_account_key'", write=True)  # as after an update from an older version
start(keep=True)
Fr, A = sess("frida"), sess("alice")
st = {}
for _ in range(40):
    st = status()
    if st["docs"]["private"]["server_key"] == 0:
        break
    time.sleep(0.25)
check(st["docs"]["private"]["server_key"] == 0 and st["docs"]["private"]["account_key"] >= 6, f"start-up pass: private values on the account key {st['docs']['private']}")
check(doc_view(Fr, "private") == FV, "start-up pass: the same content")
# ================================================================ #1979 L2: a damaged key row is a clear key error
sql("UPDATE org_keys SET wrapped='v1.@@@' WHERE org_id=?", (ORG,), write=True)
r = A.get(B + O + "/settings")
check(r.status_code == 500 and (r.headers.get("content-type", "").startswith("application/json") and r.json().get("code") == "orgcrypt"),
      f"L2: the key error with its clear message, no crash ({r.status_code}) " + r.text[:160])
# a new server key: the account keys are stored again (rewrap-accounts), the private documents' values stay readable
start(key=KEY2, keep=True)
rc, out = cli("rewrap-accounts", "--old-key-file", "-", stdin=KEY + "\n")
check(rc == 0, "rewrap-accounts " + out[-300:])
Fr = sess("frida")
check(doc_view(Fr, "private") == FV, "new server key: the freelancer's document values are still there")
check(KEY not in out and KEY2 not in out, "no key in the output")


print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
