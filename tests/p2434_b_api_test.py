#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.434.0 B API tests (#3608): delivery notes / proofs of service can be switched off (function docs.delivery).
Invented companies and people only; own container (start.sh).
 - default: docs.delivery is offered and on (DE), listed as a switchable function
 - off: creating a delivery note (POST /docs kind delivery, from a quotation / invoice, a copy of one) answers 404 with the
   same text for a person and an agent; the other kinds are untouched
 - an existing delivery note stays readable (GET, list, PDF) and the saved number scheme / closing texts stay
 - on again: creating works, everything is back
 - a person without an organisation switches it in the personal office (freelancer-matrix: office)
usage: p2434_b_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"

subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en"})
FID, Fr = freelancer(B, A)


def run(S, who):
    P = lambda path, **kw: S.post(B + path, **kw)  # noqa: E731
    r = S.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel"}, "lang": "de", "delivery_scheme": "LS-{yyyy}-{seq:03}",
                                         "delivery_closing_de": "Danke fuer den Auftrag"})
    check(r.ok, f"{who}: office settings " + r.text[:160])
    j = S.get(B + O + "/settings").json()
    check(j["features"].get("docs.delivery") is True and j["pack"]["offers"].get("docs.delivery") == "ready", f"{who}: delivery notes offered and on by default ({j['features']})")
    cl = S.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstrasse 5", "zip": "50000", "city": "Koeln", "country": "DE"}).json()["id"]
    r = P(D, json={"kind": "delivery", "client_id": cl, "items": [{"title": "Kamera", "qty": 1, "rate": 0}]})
    check(r.status_code == 201, f"{who}: a delivery note can be created while on " + r.text[:160])
    ls1 = r.json()["id"]
    inv = P(D, json={"kind": "invoice", "client_id": cl, "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]}).json()["id"]
    off = P(D, json={"kind": "offer", "client_id": cl, "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]}).json()["id"]
    check(P(f"{D}/{inv}/delivery", json={}).status_code == 201, f"{who}: delivery note from an invoice while on")

    r = S.put(B + O + "/settings", json={"features_off": ["docs.delivery"]})
    check(r.ok and r.json()["features"]["docs.delivery"] is False, f"{who}: switched off " + r.text[:160])
    msgs = set()
    for what, r in (("new", P(D, json={"kind": "delivery", "client_id": cl, "items": []})),
                    ("from invoice", P(f"{D}/{inv}/delivery", json={})),
                    ("from quotation", P(f"{D}/{off}/delivery", json={"title": "service"})),
                    ("copy", P(f"{D}/{ls1}/duplicate", json={}))):
        check(r.status_code == 404, f"{who}: off -> {what} answers 404 ({r.status_code}) " + r.text[:120])
        msgs.add(r.json().get("error"))
    check(len(msgs) == 1, f"{who}: one and the same message ({msgs})")
    check(P(D, json={"kind": "invoice", "client_id": cl, "items": []}).status_code == 201, f"{who}: invoices are untouched")
    check(P(f"{D}/{inv}/duplicate", json={}).status_code == 201, f"{who}: copying an invoice is untouched")
    g = S.get(B + f"{D}/{ls1}")
    check(g.ok and g.json()["kind"] == "delivery", f"{who}: the existing delivery note stays readable")
    lst = S.get(B + D + "?kind=delivery").json()
    check(ls1 in [x["id"] for x in lst["docs"]], f"{who}: and in the list")
    st = S.get(B + O + "/settings").json()["settings"]
    check(st.get("delivery_scheme") == "LS-{yyyy}-{seq:03}" and st.get("delivery_closing_de") == "Danke fuer den Auftrag", f"{who}: scheme and closing text are kept")
    r = S.put(B + O + "/settings", json={"features_off": []})
    check(r.ok and r.json()["features"]["docs.delivery"] is True, f"{who}: switched on again")
    check(P(D, json={"kind": "delivery", "client_id": cl, "items": []}).status_code == 201, f"{who}: creating works again")
    check(P(f"{D}/{ls1}/duplicate", json={}).status_code == 201, f"{who}: copy works again")


A.patch(B + "/api/settings", json={"features": "cal,comments,office,clients", "tour": "done"})
run(A, "instance")
run(Fr, "freelancer")

print(f"p2434_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
