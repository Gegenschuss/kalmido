#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.616.0 part C (#2473): the direct bank fetch over FinTS (kalmido/office/fints.py), own container, the stand-in bank of the
test containers (KALMIDO_TEST_FINTS_FAKE=1: no network, no real bank). Invented companies, accounts and figures only.
 - off without a product registration: GET says off with code no_product_id, a start is refused (503 no_product_id)
 - with one (restart, same data): the account of the company is listed (German IBAN, its bank code); a server address must be
   https on the internet (http / user:password / no address refused)
 - decoupled: start -> state decoupled -> the first status question still waits -> the second is approved -> the preview of
   the file import (2 new) -> the import (201, 2 bookings) -> a second fetch finds both again (duplicates, 0 new) -> the
   take-back of the first import works like the file import's
 - TAN typed in: right TAN -> preview; a wrong one ends the dialog (409 pin, the dialog is gone: 404); the TAN method is
   chosen first when the bank offers two
 - refusals: a wrong PIN (409 pin) twice -> the third start of that account is refused (429 wait) without asking the bank
 - the dialog belongs to its person and office area: another organisation's admin and a person without organisation 404,
   a member 403, an agent 403; cancel ends it; expiry through the test switch (no waiting): 404 expired
 - the PIN never shows: in no answer, the server log, nor any table; the remembered sign-in name is sealed at rest
 - 2.616.0 (#2473, Fable findings): an expired dialog goes by the background sweep alone (no FinTS request); the bank
   connection stops after FNT_STEP_HOPS requests / FNT_STEP_BYTES bytes / the time of a step; the library's log is silent;
   a JSON array as body 400 (no 500); the sign-in name and the server are kept only once the bank sent the statements, a new
   server address goes into the office log (never the login name) and the other admins see who changed it; the inner parts
   of the installed python-fints that the bank code uses are there
 - freelancer-matrix: office (a person without organisation fetches into her personal office)  tenant-matrix: office
usage: p2616_c_fints_test.py <datadir>"""
import base64
import os
import subprocess
import sys

import requests

import kt
from kt import B, CT, H, check, sess
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
PIN = "Pin-7Qx-" + base64.b32encode(os.urandom(5)).decode()  # unique: found again only if it leaked
TAN = "123456"
ENV = {"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY, "KALMIDO_TEST_FINTS_FAKE": "1"}
SRV = "https://fints.example.com/fints"
SEEN = []  # every answer text (the PIN must be in none)


def keep(r):
    SEEN.append(r.text)
    return r


kt.fresh(env=ENV, prefix="P2616C")
A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A)
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
for s, name in ((A, "Beispiel Film GmbH"), (Ca, "Andere Firma GmbH"), (Fr, "Frida Film")):
    r = s.put(B + "/api/office/settings", json={"company_fields": {"name": name, **COMPANY}})
    assert r.ok, r.text

# ---------------------------------------------------------------- off without the product registration
st = keep(A.get(B + "/api/office/bank/fints")).json()
check(st.get("on") is False and st.get("code") == "no_product_id" and st.get("message"), f"off: GET says off, code no_product_id ({st.get('code')})")
ACC = (st.get("accounts") or [{}])[0]
r = keep(A.post(B + "/api/office/bank/fints/start", json={"account_id": ACC.get("id"), "login": "decoupled", "pin": PIN, "server": SRV}))
check(r.status_code == 503 and r.json().get("code") == "no_product_id", f"off: a start is refused (503 no_product_id): {r.status_code}")

# ---------------------------------------------------------------- on (restart with the registration, same data)
kt.fresh(env={**ENV, "KALMIDO_FINTS_PRODUCT_ID": "TESTPRODUCT0000000000", "KALMIDO_TEST_FINTS_SWEEP": "1"}, prefix="P2616C", keep=True)
kt.docker_logs_on_first_fail()
st = keep(A.get(B + "/api/office/bank/fints")).json()
ACC = (st.get("accounts") or [{}])[0]
check(st.get("on") is True and st.get("code") is None, "on: GET says on with the product registration")
check(ACC.get("ok") is True and ACC.get("blz") == "12030000" and ACC.get("iban_tail") == "2051", f"on: the company's account with its bank code: {ACC}")
AID = ACC["id"]

# ---------------------------------------------------------------- 2.616.0 (#2473, Fable findings 3 + 6 + 2): library, log, limits
lib = A.get(B + "/api/test/fints/lib").json()
check(lib.get("missing") == [], f"finding 6: the inner parts of python-fints the bank code uses are there: {lib.get('missing')}")
check((lib.get("level") or 0) > 50, f"finding 3: the library's log is silent from the start (level above CRITICAL): {lib.get('level')}")
r = A.post(B + "/api/test/fints/conn", json={"size": 8, "count": 3}).json()
check(r.get("sent") == 3 and r.get("code") is None, f"finding 2: three small answers pass: {r}")
r = A.post(B + "/api/test/fints/conn", json={"size": 8, "count": 80}).json()
check(r.get("sent") == 50 and r.get("code") == "too_large", f"finding 2: at most 50 requests to the bank within one step (endless touchdowns): {r}")
r = A.post(B + "/api/test/fints/conn", json={"size": 20 * 1024 * 1024, "count": 5}).json()
check(r.get("sent") == 3 and r.get("code") == "too_large", f"finding 2: at most 60 MB of answers within one step: {r.get('sent')} {r.get('code')}")
r = A.post(B + "/api/test/fints/conn", json={"size": 8, "count": 1, "late": True}).json()
check(r.get("sent") == 0 and r.get("code") == "connection", f"finding 2: the time of a step is up -> no further request: {r}")


def start(s, login, pin=PIN, **more):
    aid = more.pop("aid", AID)
    return keep(s.post(B + "/api/office/bank/fints/start", json={"account_id": aid, "login": login, "pin": pin, "server": SRV, **more}))


for bad in ("http://fints.example.com/x", "https://user:pw@fints.example.com/x", "ftp://fints.example.com", "https://"):
    r = keep(A.post(B + "/api/office/bank/fints/start", json={"account_id": AID, "login": "decoupled", "pin": PIN, "server": bad}))
    check(r.status_code == 400, f"server: {bad!r} is refused (400): {r.status_code}")

# ---------------------------------------------------------------- decoupled -> preview -> import -> duplicates -> take-back
r = start(A, "decoupled")
d = r.json().get("dialog") or {}
check(r.status_code == 201 and d.get("state") == "decoupled" and d.get("challenge"), f"decoupled: the start waits for the approval in the app: {r.status_code} {d.get('state')}")
DID = d.get("id", "x")
a0 = keep(A.get(B + "/api/office/bank/fints")).json()["accounts"][0]
check(a0.get("login") == "" and a0.get("server") == "", f"finding 4: nothing is kept before the bank has sent the statements: {a0.get('login')!r} {a0.get('server')!r}")
check(keep(Bo.post(B + f"/api/office/bank/fints/{DID}/poll", json={})).status_code == 403, "rights: a member of the organisation 403")
check(keep(Ca.post(B + f"/api/office/bank/fints/{DID}/poll", json={})).status_code == 404, "rights: the admin of another organisation cannot go on with the dialog (404)")
check(keep(Fr.post(B + f"/api/office/bank/fints/{DID}/poll", json={})).status_code == 404, "rights: a person without organisation cannot go on with it (404)")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "fintsbot", "display_name": "Fints Bot"})
AG = {**H, "Authorization": "Bearer " + r.json()["token"]}
check(all(x.status_code in (401, 403) for x in (requests.get(B + "/api/office/bank/fints", headers=AG), requests.post(B + "/api/office/bank/fints/start", headers=AG, json={"account_id": AID, "login": "x", "pin": PIN, "server": SRV}),
                                                 requests.post(B + f"/api/office/bank/fints/{DID}/poll", headers=AG, json={}))), "rights: an agent gets 403 (an agent never handles a PIN)")
d1 = keep(A.post(B + f"/api/office/bank/fints/{DID}/poll", json={})).json().get("dialog") or {}
check(d1.get("state") == "decoupled", f"decoupled: the first status question still waits ({d1.get('state')})")
d2 = kt.until(lambda: (lambda x: x if x.get("state") != "decoupled" else None)(keep(A.post(B + f"/api/office/bank/fints/{DID}/poll", json={})).json().get("dialog") or {}), 20)
p = (d2 or {}).get("preview") or {}
check((d2 or {}).get("state") == "preview" and p.get("count") == 2 and p.get("dup_count") == 0 and p.get("fmt") == "camt", f"decoupled: approved -> the preview of the import, 2 new: {p.get('count')} {p.get('fmt')}")
r = keep(A.post(B + f"/api/office/bank/fints/{DID}/import", json={}))
j = r.json()
IID = (j.get("import") or {}).get("id")
check(r.status_code == 201 and j.get("count") == 2 and IID, f"import: 201 with 2 bookings: {r.status_code} {j.get('count')}")
tx = A.get(B + "/api/office/bank/tx?state=all").json().get("items") or []
check(sorted(t.get("counterpart") for t in tx) == ["Fake Customer GmbH", "Fake Supplier AG"], f"import: the bookings are in the bank list: {[t.get('counterpart') for t in tx]}")
check(keep(A.post(B + f"/api/office/bank/fints/{DID}/poll", json={})).status_code == 404, "import: the dialog has ended")
st = A.get(B + "/api/office/bank/fints").json()
check(st["accounts"][0].get("login") == "decoupled" and st["accounts"][0].get("server") == SRV, "remember: the sign-in name and the server stay with the account")
enc = kt.dbx("SELECT fints_login FROM office_bank_accounts WHERE id=?", (AID,))
check(enc and str(enc[0][0]).startswith("kenc1:"), "remember: the sign-in name is sealed at rest")
lg = [e for e in A.get(B + "/api/office/log?limit=500").json().get("log") or [] if e.get("target") == "bank_account" and "fints_server" in (e.get("detail") or {})]
check(len(lg) == 1 and lg[0]["detail"]["fints_server"] == {"before": "", "after": SRV} and "decoupled" not in str(lg[0]["detail"]) and lg[0].get("user_id") == ALICE,
      f"finding 4: the new server address is in the office log, with who, never the sign-in name: {[e.get('detail') for e in lg]}")
r = start(A, "plain")
d = r.json().get("dialog") or {}
check(r.status_code == 201 and d.get("state") == "preview" and d["preview"].get("count") == 0 and d["preview"].get("dup_count") == 2, f"duplicates: a second fetch finds both again: {d.get('preview', {}).get('count')} / {d.get('preview', {}).get('dup_count')}")
check(keep(A.delete(B + f"/api/office/bank/fints/{d.get('id', 'x')}")).ok and keep(A.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/import", json={})).status_code == 404, "cancel: the dialog ends, its import is gone (404)")
r = A.post(B + f"/api/office/bank/imports/{IID}/undo")
check(r.ok and not [t for t in A.get(B + "/api/office/bank/tx?state=all").json().get("items") or []], f"take-back: the fetched import goes back like a file import: {r.status_code}")

# ---------------------------------------------------------------- TAN typed in, the TAN method
r = start(A, "tan")
d = r.json().get("dialog") or {}
check(d.get("state") == "tan" and d.get("challenge"), f"tan: the bank asks for a TAN ({d.get('state')})")
r = keep(A.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/tan", json=[TAN]))
check(r.status_code == 400, f"finding 5: a JSON array as the TAN body 400 (no 500): {r.status_code}")
d = keep(A.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/tan", json={"tan": TAN})).json().get("dialog") or {}
check(d.get("state") == "preview" and d["preview"].get("count") == 2, "tan: the right TAN -> the preview (the take-back made both new again)")
A.delete(B + f"/api/office/bank/fints/{d.get('id', 'x')}")
d = start(A, "tan").json().get("dialog") or {}
r = keep(A.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/tan", json={"tan": "000000"}))
check(r.status_code == 409 and r.json().get("code") == "pin", f"tan: a wrong TAN ends the dialog (409 pin): {r.status_code}")
check(keep(A.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/tan", json={"tan": TAN})).status_code == 404, "tan: after the refusal the dialog is gone (no second try)")
d = start(A, "mech").json().get("dialog") or {}
check(d.get("state") == "mechanism" and [m["id"] for m in d.get("mechanisms") or []] == ["921", "942"], f"mechanism: two TAN methods to choose first: {d.get('state')}")
check(keep(A.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/mechanism", json={"id": "999"})).status_code == 400, "mechanism: an unknown one 400")
r = keep(A.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/mechanism", json=["942"]))
check(r.status_code == 400, f"finding 5: a JSON array as the mechanism body 400 (no 500): {r.status_code}")
check(keep(A.post(B + "/api/office/bank/fints/start", json=[AID])).status_code == 400, "finding 5: a JSON array as the start body 400")
d = keep(A.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/mechanism", json={"id": "942"})).json().get("dialog") or {}
check(d.get("state") == "preview", f"mechanism: chosen -> on to the statement ({d.get('state')})")
A.delete(B + f"/api/office/bank/fints/{d.get('id', 'x')}")

# ---------------------------------------------------------------- expiry (the test switch, no waiting)
d = start(A, "decoupled").json().get("dialog") or {}
check(A.post(B + "/api/test/fints/age", json={"seconds": 301}).ok, "expiry: the test clock runs on")
r = keep(A.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/poll", json={}))
check(r.status_code == 404 and r.json().get("code") == "expired", f"expiry: after 5 minutes without a step the dialog is gone (404 expired): {r.status_code}")
d = start(A, "decoupled").json().get("dialog") or {}
o = A.get(B + "/api/test/fints/open").json()
check(d.get("state") == "decoupled" and o.get("open", 0) >= 1 and o.get("armed") is True, f"finding 1: an open dialog arms the background sweep: {o}")
check(A.post(B + "/api/test/fints/age", json={"seconds": 901}).ok, "finding 1: the test clock runs past 15 minutes")
o = kt.until(lambda: (lambda x: x if x.get("open") == 0 else None)(A.get(B + "/api/test/fints/open").json()), 20) or {}
check(o.get("open") == 0 and o.get("armed") is False, f"finding 1: without any FinTS request the expired dialog is gone (and the sweep rests): {o}")
# 2.616.0 (#2473, Fable re-check): the sweep leaves a dialog in a running step alone (no "bank" mid-step), the next sweep takes it
d = start(A, "decoupled").json().get("dialog") or {}
A.post(B + "/api/test/fints/hold", json={"id": d.get("id"), "on": True})
A.post(B + "/api/test/fints/age", json={"seconds": 901})
o = A.post(B + "/api/test/fints/hold", json={"sweep": True}).json()
check(o.get("open") == 1, f"re-check: an expired dialog in a running step stays until the step is over: {o}")
o = A.post(B + "/api/test/fints/hold", json={"id": d.get("id"), "on": False, "sweep": True}).json()
check(o.get("open") == 0, f"re-check: after the step the sweep takes it: {o}")

# ---------------------------------------------------------------- the person without organisation (personal office)
fs = keep(Fr.get(B + "/api/office/bank/fints")).json()
FA = (fs.get("accounts") or [{}])[0].get("id")
check(fs.get("on") is True and FA and FA != AID, "freelancer: her personal office lists its own account")
r = start(Fr, "plain", aid=FA)
d = r.json().get("dialog") or {}
check(r.status_code == 201 and d.get("state") == "preview" and d["preview"].get("count") == 2, f"freelancer: the fetch into her personal office: {r.status_code}")
check(keep(A.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/import", json={})).status_code == 404, "freelancer: another person cannot import her dialog (404)")
r = keep(Fr.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/import", json={}))
check(r.status_code == 201 and r.json().get("count") == 2, f"freelancer: her import (201, 2): {r.status_code}")
check(keep(A.post(B + "/api/office/bank/fints/start", json={"account_id": FA, "login": "plain", "pin": PIN, "server": SRV})).status_code == 404, "freelancer: her account is not another office's (404)")
d = start(Fr, "tan", aid=FA).json().get("dialog") or {}
check(keep(Fr.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/tan", json={"tan": TAN})).json().get("dialog", {}).get("state") == "preview", "freelancer: TAN step")
check(keep(Fr.delete(B + f"/api/office/bank/fints/{d.get('id', 'x')}")).ok, "freelancer: cancel")
d = start(Fr, "mech", aid=FA).json().get("dialog") or {}
check(keep(Fr.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/mechanism", json={"id": "921"})).json().get("dialog", {}).get("state") == "preview", "freelancer: TAN method step")
d = start(Fr, "decoupled", aid=FA).json().get("dialog") or {}
check(keep(Fr.post(B + f"/api/office/bank/fints/{d.get('id', 'x')}/poll", json={})).json().get("dialog", {}).get("state") == "decoupled", "freelancer: status question")
Fr.delete(B + f"/api/office/bank/fints/{d.get('id', 'x')}")

# ---------------------------------------------------------------- refusals of the bank: no third try (a second account of Alpha)
r = A.post(B + "/api/office/settings/bank-accounts", json={"label": "Zweitkonto", "iban": "DE89370400440532013000", "bic": "COBADEFFXXX", "bank_name": "Zweitbank"})
A2 = (r.json().get("account") or {}).get("id")
check(r.status_code == 201 and A2, f"refusal: a second account ({r.status_code})")
for n in (1, 2):
    r = start(A, "plain", pin="wrong", aid=A2)
    check(r.status_code == 409 and r.json().get("code") == "pin", f"refusal {n}: a wrong PIN 409 pin: {r.status_code}")
a2 = next((x for x in A.get(B + "/api/office/bank/fints").json()["accounts"] if x["id"] == A2), {})
check(a2.get("login") == "" and a2.get("server") == "", f"finding 4: a refused sign-in keeps neither the sign-in name nor the server: {a2.get('login')!r} {a2.get('server')!r}")
r = start(A, "plain", aid=A2)
check(r.status_code == 429 and r.json().get("code") == "wait", f"refusal: after two the account waits (429 wait), even with the right PIN: {r.status_code}")
r = start(A, "plain")
check(r.status_code == 201, f"refusal: the other account of the office is not held up: {r.status_code}")
A.delete(B + f"/api/office/bank/fints/{(r.json().get('dialog') or {}).get('id', 'x')}")

# ---------------------------------------------------------------- 2.616.0 (#2473, Fable finding 4): another admin changes the server
assert A.post(B + "/api/users", json={"username": "dave", "display_name": "Dave Admin", "password": "password123", "email": "dave@example.com"}).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "dave@example.com", "role": "admin"}).ok
Da = sess("dave")
Da.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
SRV2 = "https://fints2.example.com/fints"
r = start(Da, "plain", server=SRV2)
check(r.status_code == 201 and (r.json().get("dialog") or {}).get("state") == "preview", f"server change: Dave's fetch with another server address: {r.status_code}")
Da.delete(B + f"/api/office/bank/fints/{(r.json().get('dialog') or {}).get('id', 'x')}")
mine = keep(A.get(B + "/api/office/bank/fints")).json()["accounts"][0]
sc = mine.get("server_changed") or {}
check(mine.get("server") == SRV2 and sc.get("by") == "Dave Admin" and sc.get("at", "")[:4].isdigit(), f"server change: Alice's dialog names who changed the address and when: {sc}")
check(not keep(Da.get(B + "/api/office/bank/fints")).json()["accounts"][0].get("server_changed"), "server change: Dave himself sees no note")
lg = [e for e in A.get(B + "/api/office/log?limit=500").json().get("log") or [] if e.get("target") == "bank_account" and "fints_server" in (e.get("detail") or {})]
check(lg and lg[0]["detail"]["fints_server"] == {"before": SRV, "after": SRV2} and "plain" not in str(lg[0]["detail"]), f"server change: in the office log ({len(lg)} entries)")
r = start(A, "plain")
A.delete(B + f"/api/office/bank/fints/{(r.json().get('dialog') or {}).get('id', 'x')}")
check(not keep(A.get(B + "/api/office/bank/fints")).json()["accounts"][0].get("server_changed"), "server change: Alice fetches with her address again -> no note")

# ---------------------------------------------------------------- the PIN never shows
check(not [t for t in SEEN if PIN in t], "PIN: in no answer")
log = subprocess.run(["docker", "logs", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
check(log and PIN not in log, "PIN: not in the server log")
cols = kt.dbx("SELECT DISTINCT table_name FROM information_schema.columns WHERE table_schema=current_schema() AND data_type IN ('text', 'character varying', 'jsonb', 'json')")
tables = sorted({c[0] for c in cols})
q = " UNION ALL ".join(f"SELECT '{t}' FROM \"{t}\" x WHERE x::text LIKE ?" for t in tables)
hits = kt.dbx(q, tuple(f"%{PIN}%" for _ in tables)) if tables else [["no tables"]]
check(len(tables) > 50 and not hits, f"PIN: in no table of the database ({len(tables)} tables read): {hits[:3]}")

sys.exit(kt.done("p2616_c_fints"))
