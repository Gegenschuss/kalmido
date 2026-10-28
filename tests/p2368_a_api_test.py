#!/usr/bin/env python3
# kalmido-suite:
"""2.368.0 (#2979, #2987) API tests: English workspaces get English office documents and English file store folders, own
container (start.sh). Invented companies and people only. freelancer-matrix: office
 - #2979 a new office that picks the International (base) pack writes its documents in English with QUO-… numbers and the
   English cover letter; a language the admin chose stays on a pack switch, a number scheme set by hand stays too
 - each for an organisation's admin and for a person without organisation (personal office)
usage: p2368_a_api_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, done, sess, B, H, DATA  # noqa: E402,F401

if not os.environ.get("KMT_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs,files", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, F = freelancer(B, A)
F.patch(B + "/api/settings", json={"lang": "en"})
O = "/api/office"
D = O + "/docs"
YEAR = time.localtime().tm_year

for who, S in (("org admin", A), ("freelancer", F)):
    # ---- #2979 the International pack chosen in a new office: English documents, QUO-… numbers
    r = S.put(B + O + "/settings", json={"pack": "XX"})
    st = r.json().get("settings") or {} if r.ok else {}
    check(r.ok and st.get("lang") == "en" and st.get("offer_scheme") == "QUO-{yyyy}-{seq:03}" and st.get("invoice_scheme") == "INV-{yyyy}-{seq:03}",
          f"{who}: #2979 base pack: language en, the pack's schemes {r.text[:300]}")
    r = S.post(B + D, json={"kind": "offer", "project_title": "Harbour film", "recipient": {"name": "Example Ltd", "lines": ["High Street 1"]}})
    j = r.json() if r.status_code == 201 else {}
    check(j.get("number") == f"QUO-{YEAR}-001", f"{who}: #2979 new quotation numbered QUO-… {r.text[:200]}")
    doc = S.get(B + f"{D}/{j.get('id')}").json() if j.get("id") else {}
    check(doc.get("lang") == "en" and "Dear Sir or Madam" in str(doc) and "Sehr geehrte" not in str(doc),
          f"{who}: #2979 the quotation is English with the English cover letter ({doc.get('lang')})")
    r = S.post(B + D, json={"kind": "invoice", "recipient": {"name": "Example Ltd", "lines": ["High Street 1"]}, "items": [{"title": "Edit", "qty": 1, "rate": 100}]})
    check(r.status_code == 201 and S.get(B + f"{D}/{r.json()['id']}").json().get("lang") == "en", f"{who}: #2979 new invoice in English {r.text[:160]}")
    # ---- a scheme set by hand stays on a switch; the pack's scheme follows the pack
    S.put(B + O + "/settings", json={"invoice_scheme": "B-{seq:03}"})
    st = S.put(B + O + "/settings", json={"pack": "DE"}).json().get("settings") or {}
    check(st.get("offer_scheme") == "KVA-{yyyy}-{seq:03}" and st.get("invoice_scheme") == "B-{seq:03}" and st.get("lang") == "de",
          f"{who}: #2979 back to DE: the pack's quotation scheme and language, the own invoice scheme stays {st.get('offer_scheme')} {st.get('invoice_scheme')} {st.get('lang')}")
    # ---- a language the admin chose stays on a switch
    S.put(B + O + "/settings", json={"lang": "de"})
    st = S.put(B + O + "/settings", json={"pack": "XX"}).json().get("settings") or {}
    check(st.get("lang") == "de" and st.get("offer_scheme") == "QUO-{yyyy}-{seq:03}",
          f"{who}: #2979 a chosen language stays, the scheme follows the pack {st.get('lang')} {st.get('offer_scheme')}")

sys.exit(done("p2368_a_api"))
