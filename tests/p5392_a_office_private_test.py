#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.794.0 (#5392): Settings > Modules > Office & finance > "Also private". Invented companies, people and figures only.
freelancer-matrix: office
 - off (the module "office" in the setting ws_mods_off "private", the same entry a private module card writes): the routes of
   the own personal office answer 403 with a readable text (workspace Private, and under "All" with the header / ?_osp of
   Private); the office of the organisation answers as before
 - its bell (docoverdue) does not show while off; nothing is deleted: switched on again, the private office answers with the
   same invoice and the bell item shows again
 - a person without an organisation: her own office as before (the switch is not offered to her, the default stays on)
usage: p5392_a_office_private_test.py <datadir>"""
import json
import os
import subprocess
import sys
from datetime import date, timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, setup  # noqa: E402

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
O = "/api/office"
D = O + "/docs"
HS = "X-Kalmido-Office-Space"
FEAT = "cal,comments,collab,clients,office,docs,files,contacts"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "email": "hallo@beispiel.example", "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
           "bank_name": "Beispielbank"}
OFF_TEXT = "switched off in the workspace Private"

fresh({"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P5392A")
A = setup()
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ALICE = A.get(B + "/api/me").json()["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]


def tick():
    code = ("import app\nfrom kalmido.core.db import connect\nfrom kalmido.office import dunning as x\n"
            "x._DUN_LAST['at'] = -1e12\nc = connect()\nx.dun_tick(c)\nc.close()")
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def ws(v):
    assert A.patch(B + "/api/settings", json={"workspace": v}).ok


def ofs(hd=None, params=None):
    r = A.get(B + O + "/settings", headers=hd or {}, params=params or {})
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return r.status_code, j.get("org_id"), bool(j.get("personal")), str(j.get("error") or j.get("message") or "")


def overdue(s):
    return [x for x in s.get(B + "/api/news").json()["items"] if x["kind"] == "docoverdue"]


def priv_off(on_off):
    o = {"private": ["office"]} if on_off else {}
    r = A.patch(B + "/api/settings", json={"ws_mods_off": json.dumps(o)})
    assert r.ok, r.text


# ---------------------------------------------------------------- the private office with an invoice, and the organisation's
ws("private")
assert A.put(B + O + "/settings", json={"lang": "de", "dunning_suggest": 0, "company_fields": COMPANY}).ok
r = A.post(B + "/api/clients", json={"name": "Privatkunde GmbH", "street": "Marktweg 5", "zip": "50667", "city": "Koeln", "country": "DE"})
assert r.status_code in (200, 201), r.text
CL = r.json()["id"]
r = A.post(B + D, json={"kind": "invoice", "lang": "de", "client_id": CL, "project_title": "Schnitt", "service_from": "2026-05-01",
                        "items": [{"title": "Schnitt", "qty": 1, "rate": 500}]})
assert r.status_code == 201, r.text
INV = r.json()["id"]
assert A.post(B + f"{D}/{INV}/finalize").ok
dbx("UPDATE office_docs SET due_date=? WHERE id=?", ((date.today() - timedelta(days=5)).isoformat(), INV))
st = ofs()
PRIV = st[1]
check(st[0] == 200 and st[2], f"switch on (default): the private office answers {st}")
tick()
check(len(overdue(A)) == 1, f"switch on: the private office rings the bell for its overdue invoice {overdue(A)}")
ws(f"org:{ORG}")
check(A.put(B + O + "/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "country": "de"}, "lang": "en", "currency": "EUR"}).ok,
      "setup: the organisation's office")

# ---------------------------------------------------------------- off: no private office, the organisation's stays
priv_off(True)
ws("private")
st = ofs()
check(st[0] == 403 and OFF_TEXT in st[3], f"off, workspace Private: 403 with the hint where to switch it on {st}")
r = A.get(B + D, params={"kind": "invoice"})
check(r.status_code == 403, f"off: the private invoices are refused too {r.status_code}")
check(not overdue(A), f"off: the private office's bell item does not show {overdue(A)}")
ws(f"org:{ORG}")
st = ofs()
check(st[0] == 200 and st[1] == ORG, f"off: the organisation's office answers as before {st}")
ws("all")
check(ofs({HS: "private"})[0] == 403, f"off, under All with the header Private: 403 {ofs({HS: 'private'})}")
check(ofs(params={"_osp": "private"})[0] == 403, "off, under All with ?_osp=private: 403")
check(ofs({HS: f"org:{ORG}"})[:2] == (200, ORG), f"off, under All with the header of the organisation: its office {ofs({HS: f'org:{ORG}'})}")
check(A.get(B + "/api/settings").json().get("features", "").split(",").count("office") == 1, "off: the module switch itself stays on")

# ---------------------------------------------------------------- on again: everything as before
priv_off(False)
ws("private")
st = ofs()
check(st[0] == 200 and st[1] == PRIV, f"on again: the same private office {st}")
r = A.get(B + D, params={"kind": "invoice"})
ids = [x.get("id") for x in (r.json().get("docs") or [])] if r.ok else []
check(INV in ids, f"on again: the invoice is still there {r.status_code} {ids}")
check(len(overdue(A)) == 1, f"on again: the bell item shows again {overdue(A)}")

# ---------------------------------------------------------------- freelancer-matrix: office
FID, Fr = freelancer(B, A)
r = Fr.get(B + O + "/settings")
check(r.ok and r.json().get("personal"), f"a person without an organisation: her own office as before {r.status_code}")

sys.exit(done("p5392_a_office_private"))
