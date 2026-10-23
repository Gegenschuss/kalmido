#!/usr/bin/env python3
"""2.118.0 API tests, part A (#2265): the quotation counter per organisation / client / project and the building block
{version} (decision of 2026-10-19, test case KV-{client}-{yyyy}-{seq:02}). Own container (start.sh), invented companies
and people only (@example.com / .example).
 - settings key offer_counter: org (default) | client | project, anything else 400; a member may not change it (403)
 - per client: two clients count apart, a new year starts again at 1, a new client counter continues from the highest
   running number the client's quotations already carry; without a client the recipient's name counts; a quotation
   counted per client without one gets its number once the client is set
 - back to the organisation's counter: it continues where it stood (taken numbers are skipped)
 - per project (project title)
 - {version}: a duplicate keeps the first quotation's running number, only the version grows (V2, V3), the counter stays;
   a deleted version is not counted
 - invoices keep one counter; {version} in the invoice scheme is refused (settings and preview)
 - the preview shows the example (per client from 1, with V1)
 - a person without an organisation (freelancer-matrix: office) does the same in the personal office
usage: p2118_a_api_test.py <datadir>      (a fresh container; P2118A_NOSTART=1 = the server already runs)"""
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)
TEST_IBAN = "DE02120300000000202051"


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


if not os.environ.get("P2118A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,clients,office"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123",
                               "email": "bob@example.com"})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT, "workspace": f"org:{ORG}"})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
D = "/api/office/docs"
SET = "/api/office/settings"
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
KV = "KV-{client}-{yyyy}-{seq:02}"


def client(s, name):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
                                         "email_invoice": f"billing@{name.lower()}.example", "payment_terms_days": 14})
    check(r.status_code in (200, 201), "a client " + r.text[:200])
    return r.json().get("id")


def settings(s, **kw):
    r = s.put(B + SET, json=kw)
    check(r.ok, f"settings {kw} " + r.text[:200])
    return r


def offer(s, cl=None, day="2030-03-01", **kw):
    body = {"date": day, **({"client_id": cl} if cl else {}), **kw}
    r = s.post(B + D, json=body)
    check(r.status_code == 201, "a quotation " + r.text[:200])
    return r.json().get("id"), r.json().get("number") or ""


def counter(oid, kind, period):
    r = dbx("SELECT last FROM office_numbers WHERE org_id=? AND kind=? AND period=?", (oid, kind, period))
    return r[0][0] if r else None


def number(s, did):
    return s.get(B + f"{D}/{did}").json().get("number") or ""


settings(A, company_fields=COMPANY, lang="en", currency="EUR", offer_scheme=KV)
ACME, BETA, GAMMA = client(A, "ACME"), client(A, "BETA"), client(A, "GAMMA")
check(A.get(B + SET).json()["settings"].get("offer_counter") == "org", "default: one counter for the organisation")
check(A.put(B + SET, json={"offer_counter": "team"}).status_code == 400, "an unknown counter: 400")
check(Bo.put(B + SET, json={"offer_counter": "client"}).status_code == 403, "a member may not change the counter")

# ================================================================== per organisation (as before)
check(offer(A, ACME)[1] == "KV-ACME-2030-01", "org counter: ACME 01")
check(offer(A, BETA)[1] == "KV-BETA-2030-02", "org counter: BETA 02")
check(offer(A, ACME)[1] == "KV-ACME-2030-03", "org counter: ACME 03")
check(counter(ORG, "offer", "2030") == 3, "the organisation's counter stands at 3")

# ================================================================== per client
settings(A, offer_counter="client")
check(A.get(B + SET).json()["settings"]["offer_counter"] == "client", "saved: per client")
check(offer(A, ACME)[1] == "KV-ACME-2030-04", "per client: ACME continues from its highest number (03)")
check(offer(A, BETA)[1] == "KV-BETA-2030-03", "per client: BETA continues from its highest number (02)")
check(offer(A, GAMMA)[1] == "KV-GAMMA-2030-01", "per client: a new client starts at 01")
check(offer(A, ACME)[1] == "KV-ACME-2030-05", "per client: ACME 05, apart from BETA")
check(offer(A, BETA)[1] == "KV-BETA-2030-04", "per client: BETA 04")
check(offer(A, ACME, "2031-01-10")[1] == "KV-ACME-2031-01", "per client: a new year starts again at 01")
check(counter(ORG, f"offer:c{ACME}", "2030") == 5 and counter(ORG, f"offer:c{BETA}", "2030") == 4, "the client counters")
check(counter(ORG, "offer", "2030") == 3, "the organisation's counter did not move")
# without a client: the recipient's name counts; no name at all = no number until the client is set
rid, rnum = offer(A, recipient={"name": "Delta Example", "lines": ["Weg 1"]})
check(rnum == "KV-Delta-Example-2030-01", "without a client: the recipient's name counts " + rnum)
nid, nnum = offer(A)
check(nnum == "", "per client, no client yet: no number yet " + nnum)
r = A.patch(B + f"{D}/{nid}", json={"client_id": ACME})
check(r.ok and r.json().get("number") == "KV-ACME-2030-06", "the client set: the number comes " + r.text[:200])
check(A.patch(B + f"{D}/{nid}", json={"project_title": "Spot"}).json().get("number") == "KV-ACME-2030-06", "a later change keeps it")
nid2, _ = offer(A)
A.put(B + f"{D}/{nid2}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 900}]})
A.patch(B + f"{D}/{nid2}", json={"recipient": {"name": "", "lines": []}})
r = A.post(B + f"{D}/{nid2}/finalize")
# 2.144.9 (#2575): the empty client block takes its separator along (was "KV--2030-04")
check(r.ok and r.json().get("number") == "KV-2030-04", "finalised without a client: the organisation's counter " + r.text[:200])

# ================================================================== back to the organisation's counter
settings(A, offer_counter="org")
_, n = offer(A, ACME)
check(n == "KV-ACME-2030-07", "org again: continues from its counter (4), the taken 05 / 06 skipped " + n)
check(len({x[0] for x in dbx("SELECT number FROM office_docs WHERE org_id=? AND number<>''", (ORG,))})
      == len(dbx("SELECT number FROM office_docs WHERE org_id=? AND number<>''", (ORG,))), "no number twice")

# ================================================================== per project
settings(A, offer_counter="project", offer_scheme="KV-{project}-{seq:02}")
check(offer(A, ACME, project_title="Spot one")[1] == "KV-Spot-one-01", "per project: Spot one 01")
check(offer(A, BETA, project_title="Docu")[1] == "KV-Docu-01", "per project: Docu 01")
check(offer(A, GAMMA, project_title="Spot one")[1] == "KV-Spot-one-02", "per project: Spot one 02 (whatever the client)")

# ================================================================== {version}
settings(A, offer_counter="client", offer_scheme=KV + "-V{version}")
root, rn = offer(A, GAMMA)
m = re.fullmatch(r"KV-GAMMA-2030-(\d\d)-V1", rn)
check(bool(m), "the first version: V1 " + rn)
seq = m.group(1) if m else "??"
last = counter(ORG, f"offer:c{GAMMA}", "2030")
r = A.post(B + f"{D}/{root}/duplicate")
check(r.status_code == 201 and r.json()["number"] == f"KV-GAMMA-2030-{seq}-V2", "a duplicate: same number, V2 " + r.text[:200])
v2 = r.json().get("id")
r = A.post(B + f"{D}/{v2}/duplicate")
check(r.status_code == 201 and r.json()["number"] == f"KV-GAMMA-2030-{seq}-V3", "a duplicate of the duplicate: V3 " + r.text[:200])
v3 = r.json().get("id")
check(counter(ORG, f"offer:c{GAMMA}", "2030") == last, "the counter did not move")
check(A.delete(B + f"{D}/{v3}").ok, "V3 deleted (a draft)")
r = A.post(B + f"{D}/{root}/duplicate")
check(r.status_code == 201 and r.json()["number"] == f"KV-GAMMA-2030-{seq}-V3", "the next one after a deleted V3: V3 again " + r.text[:200])
check(offer(A, GAMMA)[1] == f"KV-GAMMA-2030-{int(seq) + 1:02d}-V1", "the next new quotation: the next running number, V1")
# a chain from before the block: the first quotation's number does not follow the scheme -> the next number
settings(A, offer_scheme=KV)
old, _ = offer(A, BETA)
settings(A, offer_scheme=KV + "-V{version}")
r = A.post(B + f"{D}/{old}/duplicate")
check(r.status_code == 201 and re.fullmatch(r"KV-BETA-\d{4}-\d\d-V2", r.json()["number"] or ""),  # (a duplicate is dated today)
      "an older first quotation: next number, V2 " + (r.json().get("number") or r.text[:200]))

# ================================================================== the preview
j = A.get(B + "/api/office/number-preview", params={"kind": "offer", "scheme": KV + "-V{version}", "counter": "client"}).json()
check(j.get("valid") and re.fullmatch(r"KV-Client-\d{4}-01-V1", j.get("preview") or ""), f"preview per client: example from 01, V1 {j}")
j = A.get(B + "/api/office/number-preview", params={"kind": "offer", "scheme": "KV-{foo}-{seq}"}).json()
check(not j.get("valid") and "{version}" in (j.get("error") or ""), f"an unknown block names {{version}} {j}")
check(re.fullmatch(r"KV-.*-01-V1", A.get(B + SET).json().get("number_preview") or ""), "the settings' preview per client")

# ================================================================== invoices keep one counter, no {version}
r = A.put(B + SET, json={"invoice_scheme": "RE-{yyyy}-{seq:03}-V{version}"})
check(r.status_code == 400 and "{version}" in r.text, "{version} in the invoice scheme: 400 " + r.text[:200])
j = A.get(B + "/api/office/number-preview", params={"kind": "invoice", "scheme": "RE-{yyyy}-{seq:03}-V{version}"}).json()
check(not j.get("valid") and "{version}" in (j.get("error") or ""), f"invoice preview refuses {{version}} {j}")
A.put(B + f"{D}/{root}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 900}]})
A.patch(B + f"{D}/{root}", json={"service_from": "2030-02-01", "service_to": "2030-02-28"})
check(A.post(B + f"{D}/{root}/finalize").ok, "the quotation finalised")
r = A.post(B + f"{D}/{root}/invoice")
check(r.status_code == 201, "an invoice from it " + r.text[:200])
inv = r.json().get("id")
r = A.post(B + f"{D}/{inv}/finalize")
check(r.ok and r.json().get("number"), "the invoice finalised " + r.text[:300])
kinds = {x[0] for x in dbx("SELECT kind FROM office_numbers WHERE org_id=? AND kind NOT LIKE 'offer%'", (ORG,))}
check(kinds == {"invoice"}, f"invoices: one counter for the organisation {kinds}")

# ================================================================== a person without an organisation
# freelancer-matrix: office
FID, F = freelancer(B, A)
settings(F, company_fields=COMPANY, lang="en", currency="EUR", offer_scheme=KV + "-V{version}", offer_counter="client")
FA, FB = client(F, "ACME"), client(F, "BETA")
f1, n1 = offer(F, FA)
check(n1 == "KV-ACME-2030-01-V1", "freelancer: ACME 01 V1 " + n1)
check(offer(F, FB)[1] == "KV-BETA-2030-01-V1", "freelancer: BETA counts apart")
check(offer(F, FA)[1] == "KV-ACME-2030-02-V1", "freelancer: ACME 02")
r = F.post(B + f"{D}/{f1}/duplicate")
check(r.status_code == 201 and r.json()["number"] == "KV-ACME-2030-01-V2", "freelancer: duplicate V2 " + r.text[:200])
check(F.put(B + SET, json={"credit_scheme": "GS-{seq}-{version}"}).status_code == 400, "freelancer: no {version} for credit notes")
check(A.get(B + f"{D}/{f1}").status_code in (403, 404), "the organisation's admin does not see the freelancer's quotation")

print(f"p2118_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
