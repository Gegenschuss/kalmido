#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.470.0 (#3596, part A) API tests: the bank accounts of an office as master data, own container (start.sh, org encryption on).
Invented companies and test IBANs only. tenant-matrix: office  freelancer-matrix: office
 - the first look makes the default account out of the company's bank fields, once; the fields stay stored
 - several accounts, exactly one default (a new one only when asked, set as default, archive hands it on, the last one stays)
 - IBAN and BIC checked on the server, nothing stored on a wrong value; encrypted at rest; the log keeps no whole IBAN
 - the printed lines, the payment data and the GiroCode of a draft read the default account; a finished document keeps its own
 - a write to the company's fields (an older client) goes on to the default account
 - DATEV: the ledger account of the default account, else the DATEV settings as before; wrong digits 400
 - rights: a member 403 and no bank data in the settings, another organisation 404 and nothing in its list
 - organisation export / import: the accounts come along into a new office; an office with its own company keeps its accounts
 - a person without an organisation: the same in the personal office
usage: pr2470_a_bankacc_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
from kt import FAILS, OKS, check, sess, su_get, B, H, DATA  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
O, D, BA = "/api/office", "/api/office/docs", "/api/office/settings/bank-accounts"
IBAN1, IBAN2, IBAN3 = "DE02120300000000202051", "DE89370400440532013000", "DE75512108001245126199"


def sql(q, args=()):
    c = dbxm.connect(DATA)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


if not os.environ.get("KMT_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ids = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
A.patch(B + f"/api/users/{ids['alice']}", json={"email": "alice@example.com"})
for u in ("bob", "carol"):
    ids[u] = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"}).json()["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["alice"]}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
ORG3 = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ids["carol"]}).json()["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = {"features": "cal,comments,collab,office,clients,docs", "lang": "en", "tour": "done"}
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    assert s.patch(B + "/api/settings", json={**FEAT, "workspace": f"org:{o}"}).ok


def company(s, iban=IBAN1, bic="BYLADEM1001", bank="Beispielbank"):
    r = s.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel"}, "currency": "EUR", "lang": "de",
                                         "company_fields": {"name": "Studio Beispiel", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg", "country": "DE",
                                                            "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": iban, "bic": bic, "bank_name": bank}})
    assert r.ok, r.text


def items(s, q=""):
    r = s.get(B + BA + q)
    assert r.ok, r.text
    return r.json()["items"]


def new(s, iban, label="", **kw):
    r = s.post(B + BA, json={"iban": iban, "label": label, **kw})
    assert r.status_code == 201, r.text
    return r.json()["account"]


def invoice(s):
    cl = s.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]
    r = s.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": "2026-03-01", "service_to": "2026-03-15", "items": [{"title": "Schnitt", "qty": 1, "rate": 1000}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def render(s, did):
    r = s.get(B + f"{D}/{did}/render")
    assert r.ok, r.text
    return r.json()


# ---------------------------------------------------------------- the first look
company(A)
acc = items(A)
check(len(acc) == 1 and acc[0]["is_default"] and acc[0]["iban"] == IBAN1 and acc[0]["bic"] == "BYLADEM1001" and acc[0]["label"] == "Beispielbank",
      f"the first look makes the default account from the company fields {acc}")
check(len(items(A)) == 1 and A.get(B + O + "/settings").json()["bank_accounts"] == 1, "made once")
check(sql("SELECT COUNT(*) FROM office_company WHERE org_id=? AND iban<>''", (ORG,))[0][0] == 1, "the company fields stay stored")
FIRST = acc[0]["id"]

# ---------------------------------------------------------------- wrong values, encryption
n0 = sql("SELECT COUNT(*) FROM office_bank_accounts WHERE org_id=?", (ORG,))[0][0]
for bad in ({"iban": "DE00120300000000202051"}, {"iban": ""}, {"iban": IBAN2, "bic": "x"}, {"iban": IBAN2, "datev_account": "12a"}, {"iban": IBAN2, "datev_account": "123456"}, {"iban": IBAN2, "label": 5}):
    r = A.post(B + BA, json=bad)
    check(r.status_code == 400, f"refused {bad}: {r.status_code}")
check(sql("SELECT COUNT(*) FROM office_bank_accounts WHERE org_id=?", (ORG,))[0][0] == n0, "nothing stored on a wrong value")
check(A.put(B + BA + f"/{FIRST}", json={"iban": "DE00"}).status_code == 400 and A.put(B + BA + f"/{FIRST}", json={"iban": ""}).status_code == 400, "the IBAN checked on a change too")
row = sql("SELECT iban, bic, bank_name FROM office_bank_accounts WHERE id=?", (FIRST,))[0]
check(IBAN1 not in row[0] and "BYLADEM" not in row[1] and "Beispielbank" not in row[2], "IBAN, BIC and bank encrypted at rest")

# ---------------------------------------------------------------- several accounts, exactly one default
second = new(A, "de89 3704 0044 0532 0130 00", bic="COBADEFFXXX", bank_name="Musterbank")
check(not second["is_default"] and second["iban"] == IBAN2 and second["label"] == "Musterbank", f"a new account: normalised, its name from the bank, not the default {second}")
third = new(A, IBAN3, "Rücklagen", default=True)
check(third["is_default"] and [x["id"] for x in items(A) if x["is_default"]] == [third["id"]], "default on request: exactly one")
r = A.post(B + BA + f"/{FIRST}/default")
check(r.ok and r.json()["account"]["is_default"] and sum(x["is_default"] for x in items(A)) == 1, "set as default: exactly one")
check(A.post(B + BA + "/999999/default").status_code == 404, "an unknown account 404")

# ---------------------------------------------------------------- print, payment, GiroCode, the frozen document
DRAFT = invoice(A)
rd = render(A, DRAFT)
check(rd["payment"]["iban"] == IBAN1 and IBAN1 in (rd["payment"].get("girocode") or ""), "the draft reads the default account")
FIN = invoice(A)
r = A.post(B + f"{D}/{FIN}/finalize")
check(r.ok, "finalised " + r.text[:200])
fin = render(A, FIN)
check(A.post(B + BA + f"/{second['id']}/default").ok, "another default")
rd = render(A, DRAFT)
check(any("3704" in x for x in rd["company"]["bank_lines"]) and "Musterbank" in rd["company"]["bank_lines"], f"the printed lines follow the default {rd['company']['bank_lines']}")
check(rd["payment"]["iban"] == IBAN2 and rd["payment"]["bic"] == "COBADEFFXXX" and rd["payment"]["bank_name"] == "Musterbank", f"the payment data follow the default {rd['payment']}")
gc = rd["payment"].get("girocode") or ""
check(IBAN2 in gc and "COBADEFFXXX" in gc and IBAN1 not in gc, f"the GiroCode follows the default {gc!r}")
check(A.get(B + f"{D}/{DRAFT}/pdf").content[:5] == b"%PDF-", "the PDF of the draft")
again = render(A, FIN)
check(again["payment"]["iban"] == IBAN1 and again["payment"].get("girocode") == fin["payment"].get("girocode"), "a finished document keeps the account it was made with")
x = A.get(B + f"{D}/{FIN}/xml")
check(x.ok and IBAN1.encode() in x.content and IBAN2.encode() not in x.content, "its e-invoice too")

# ---------------------------------------------------------------- the company's fields, an older client
cf = A.get(B + O + "/settings").json()["company_fields"]
check(cf["iban"] == IBAN2 and cf["bank_name"] == "Musterbank", f"the settings show the default account {cf['iban']}")
company(A, IBAN3, "COBADEFFXXX", "Neue Bank")
d = [x for x in items(A) if x["is_default"]][0]
check(d["id"] == second["id"] and d["iban"] == IBAN3 and d["bank_name"] == "Neue Bank", f"a write to the company fields reaches the default account {d}")
r = A.put(B + O + "/settings", json={"company_fields": {"phone": "+49 40 000000"}})
check(r.ok and [x for x in items(A) if x["is_default"]][0]["iban"] == IBAN3, "another company field leaves it alone")
check(A.put(B + BA + f"/{second['id']}", json={"iban": IBAN2, "bank_name": "Musterbank"}).ok, "back")

# ---------------------------------------------------------------- DATEV
assert A.put(B + O + "/settings", json={"datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03", "bank": "1210"}}).ok
sql_d = dbxm.connect(DATA)
sql_d.execute("UPDATE office_docs SET date='2026-03-05' WHERE id=?", (FIN,))
sql_d.commit()
sql_d.close()
# 2.523.0 (#4082): the invoice is dated first (was after the payment): a payment before the invoice date is refused now
assert A.post(B + f"{D}/{FIN}/payments", json={"date": "2026-03-20", "amount": "100.00", "method": "transfer"}).status_code == 201


def konto():
    r = A.get(B + O + "/datev/extf?from=2026-03-01&to=2026-03-31&in=0")
    assert r.ok, r.text
    rows = [x.split(";") for x in r.content.decode("cp1252").split("\r\n")[2:-1]]
    return [x[6] for x in rows if '"Zahlung' in ";".join(x)]


check(konto() == ["1210"], f"without its own account: the DATEV settings {konto()}")
check(A.put(B + BA + f"/{second['id']}", json={"datev_account": "1220"}).json()["account"]["datev_account"] == "1220", "the DATEV account stored")
check(konto() == ["1220"], f"the ledger account of the default account {konto()}")
check(A.post(B + BA + f"/{FIRST}/default").ok and konto() == ["1210"], "a default without one: the DATEV settings again")
check(A.post(B + BA + f"/{second['id']}/default").ok, "back")

# ---------------------------------------------------------------- archive, restore
r = A.post(B + BA + f"/{second['id']}/archive")
j = r.json()
check(r.ok and j["was_default"] and j["default_id"] == FIRST, f"archiving the default hands it on {j}")
check([x["id"] for x in items(A, "?archived=1")] == [second["id"]] and second["id"] not in [x["id"] for x in items(A)], "archived: out of the list, in the archive")
check(A.post(B + BA + f"/{second['id']}/default").status_code == 409, "an archived account is no default")
check(render(A, DRAFT)["payment"]["iban"] == IBAN1, "the draft follows")
r = A.post(B + BA + f"/{second['id']}/restore")
check(r.ok and not r.json()["account"]["is_default"] and sum(x["is_default"] for x in items(A)) == 1, "restored, the default stays")
for x in (third, second):
    A.post(B + BA + f"/{x['id']}/archive")
r = A.post(B + BA + f"/{FIRST}/archive")
check(r.status_code == 409 and "only bank account" in r.json().get("error", ""), f"the last account stays {r.status_code}")
A.post(B + BA + f"/{second['id']}/restore")

# ---------------------------------------------------------------- the log
log = [x for x in A.get(B + O + "/log?limit=200").json()["log"] if x.get("target") == "bank_account"]
check(len(log) >= 5 and IBAN2 not in str(log) and IBAN3 not in str(log), f"changes are in the office log, without a whole IBAN ({len(log)})")

# ---------------------------------------------------------------- rights, tenancy
for m, url, b in (("get", BA, None), ("post", BA, {"iban": IBAN2}), ("put", BA + f"/{FIRST}", {"label": "x"}), ("post", BA + f"/{FIRST}/default", None),
                  ("post", BA + f"/{FIRST}/archive", None), ("post", BA + f"/{FIRST}/restore", None)):
    r = getattr(Bo, m)(B + url, json=b)
    check(r.status_code == 403 and IBAN1 not in r.text, f"member {m} {url}: {r.status_code}")
j = Bo.get(B + O + "/settings").json()
check(j["bank_accounts"] == 0 and j["company_fields"]["iban"] == "" and j["company_fields"]["bank_name"] == "", "a member gets no bank data in the settings")
check(render(Bo, DRAFT)["payment"]["iban"] == IBAN1, "the document still prints it for a member")
company(Ca, IBAN3, "", "Betabank")
check([x["iban"] for x in items(Ca)] == [IBAN3], "another organisation sees only its own")
for m, url, b in (("put", BA + f"/{FIRST}", {"label": "x"}), ("post", BA + f"/{FIRST}/default", None), ("post", BA + f"/{FIRST}/archive", None), ("post", BA + f"/{FIRST}/restore", None)):
    check(getattr(Ca, m)(B + url, json=b).status_code == 404, f"another organisation: {url} 404")
check(render(A, DRAFT)["payment"]["iban"] == IBAN1, "Alpha's default untouched")

# ---------------------------------------------------------------- organisation export / import
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, f"export started {r.status_code}")
for _ in range(480):
    if A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running":
        break
    time.sleep(0.25)
DATA_X = su_get(A, B + f"/api/orgs/{ORG}/export/file").content
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")


def wait(s, iid):
    j = {}
    for _ in range(720):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def org_import(s, target):
    r = s.post(B + "/api/account/import", json={"size": len(DATA_X), "name": "alpha.kalmido-export"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(DATA_X):
        part = DATA_X[off:off + (1 << 20)]
        assert s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"}).ok
        off += len(part)
    wait(s, iid)
    assert s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": RK}).status_code == 202
    j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    return wait(s, iid)


j = org_import(Ca, ORG2)
check(j.get("state") == "done", f"import into an office with its own company {j.get('state')} {j.get('error')}")
check([x["iban"] for x in items(Ca)] == [IBAN3], f"it keeps its own accounts {[x['iban'] for x in items(Ca)]}")
W = (j.get("result") or {}).get("warnings") or []
check(any("bank accounts" in str(x) for x in W), f"the import names the left-out accounts {W}")  # review: not silent
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG3}"})
j = org_import(Ca, ORG3)
check(j.get("state") == "done", f"import into a new office {j.get('state')} {j.get('error')}")
got = items(Ca)
want = {x["iban"]: x["is_default"] for x in items(A)}
check({x["iban"]: x["is_default"] for x in got} == want and sum(x["is_default"] for x in got) == 1, f"the accounts came along, one default {got}")
check(IBAN1 not in sql("SELECT iban FROM office_bank_accounts WHERE org_id=? LIMIT 1", (ORG3,))[0][0], "sealed in the target")

# ---------------------------------------------------------------- a person without an organisation
FID, Fr = freelancer(B, A)
check(items(Fr) == [], "a new personal office: no account, none invented")
assert Fr.put(B + O + "/settings", json={"company": {"name": "Frida", "bank_lines": ["Freie Zeile"]}, "lang": "de", "currency": "EUR"}).ok
d = invoice(Fr)
check(render(Fr, d)["company"]["bank_lines"] == ["Freie Zeile"], "no account, no company fields: the free lines as before")
company(Fr, IBAN2, "", "Privatbank")
check([x["iban"] for x in items(Fr)] == [IBAN2], "the personal office: the first look")
acc = new(Fr, IBAN3, "Zweitkonto", default=True)
rd = render(Fr, d)
check(rd["payment"]["iban"] == IBAN3 and acc["is_default"] and not any("Freie" in x for x in rd["company"]["bank_lines"]), "the personal office: documents read the default account, before the free lines")
check(Fr.post(B + BA + f"/{FIRST}/archive").status_code == 404, "the personal office never reaches Alpha's")
aid = acc["id"]
r = Fr.post(B + "/api/office/settings/bank-accounts", json={"iban": IBAN1})
check(r.status_code == 201, "the personal office: a third account")
r = Fr.put(B + f"/api/office/settings/bank-accounts/{aid}", json={"label": "Hauptkonto"})
check(r.ok and r.json()["account"]["label"] == "Hauptkonto", "the personal office: edit")
r = Fr.post(B + f"/api/office/settings/bank-accounts/{aid}/archive")
check(r.ok and r.json()["was_default"], "the personal office: archive")
r = Fr.post(B + f"/api/office/settings/bank-accounts/{aid}/restore")
check(r.ok, "the personal office: restore")
r = Fr.post(B + f"/api/office/settings/bank-accounts/{aid}/default")
check(r.ok and r.json()["account"]["is_default"], "the personal office: set as default")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
