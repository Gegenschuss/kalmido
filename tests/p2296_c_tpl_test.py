#!/usr/bin/env python3
"""2.296.0 C (#3165): document templates / letters from a template - empty variables are left out cleanly and named,
own container (start.sh). Invented companies, people and figures only.
freelancer-matrix: office
 - the order confirmation sample (de) for a client without quotation / project / contact: the finished text has no
   double space, no " ." / " ,", the optional parts [[ ... ]] are gone, the list lines without a value too
   (was "nach unserem Angebot  vom  für das Projekt ." and "- Auftragssumme:")
 - the preview keeps the empty variables as {{key}} and names them (missing + missing_labels by name)
 - the draft PDF draws a left {{offer.date}} in red, the final PDF carries no {{ at all
 - offer.net / offer.gross (offer.total = the gross alias) of a quotation; the contract sample takes "zzgl. USt" and the
   payment term from the office settings (payment_days) instead of a fixed 14
 - client.address alone on its line keeps its lines, in running text it is "street, zip city"
 - a letter from a template names what the template could not fill (unfilled + unfilled_labels)
 - the same for a person without organisation (personal office, tests/freelancer_fixture.py)
usage: p2296_c_tpl_test.py <datadir>      (P2296C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import re
import subprocess
import sys
import time
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
TP = O + "/doc-templates"
GD = O + "/gen-docs"
RED = "0.776 0.157 0.157 rg"  # doctpl.DT_MISS_COLOR #c62828


def pdf_hex(data):
    out = b""
    for m in re.finditer(rb"stream\r?\n(.*?)\nendstream", data, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out.decode("latin-1")


def hx(text):
    return text.encode("cp1252").hex()


if os.environ.get("P2296C_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})


def run(S, who):
    r = S.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "payment_days": 30,
                                         "company_fields": {"name": "Studio Nordlicht GmbH", "street": "Musterweg 1", "zip": "12345",
                                                            "city": "Musterstadt", "country": "DE"}})
    check(r.ok, f"{who}: office settings {r.status_code} {r.text[:200]}")
    cl = S.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Kundenweg 5", "zip": "20000", "city": "Hamburg",
                                          "country": "DE"}).json()["id"]
    # ---- the order confirmation without quotation / project / contact
    tc = S.post(B + TP, json={"starter": "confirmation", "lang": "de"}).json()
    check("[[" in tc["body"] and "{{offer.net}} zzgl. USt" in tc["body"], f"{who}: the sample uses optional parts and the net total")
    g = S.post(B + GD, json={"template_id": tc["id"], "client_id": cl})
    check(g.status_code == 201, f"{who}: a draft {g.status_code} {g.text[:200]}")
    g = g.json()["id"]
    pv = S.post(B + GD + "/preview", json={"gen_doc_id": g}).json()
    check("{{offer.date}}" in pv["text"] and "offer.date" in pv["missing"] and "offer.net" in pv["missing"]
          and "Quotation date" in pv["missing_labels"], f"{who}: the preview keeps {{{{offer.date}}}} and names it {pv['missing']} {pv.get('missing_labels')}")
    pd = S.get(B + f"{GD}/{g}/pdf")
    h = pdf_hex(pd.content) if pd.ok else ""
    i = h.find("<" + hx("{{offer.date}}") + ">")
    check(pd.ok and i > 0 and RED in h[h.rfind("BT ", 0, i):i], f"{who}: the draft PDF draws {{{{offer.date}}}} red")
    r = S.post(B + f"{GD}/{g}/final")
    check(r.ok, f"{who}: finish {r.status_code} {r.text[:200]}")
    t = S.get(B + f"{GD}/{g}").json()["body"]
    check("  " not in t and " ." not in t and " ," not in t and "[[" not in t and "{{" not in t, f"{who}: no double space / gap before a point {t!r}")
    check("Wir bestätigen den Auftrag." in t and "Angebot" not in t.split("Es gelten")[0], f"{who}: the optional parts are left out {t!r}")
    check("Auftragssumme" not in t and "Ansprechpartner" not in t and "- Auftraggeber: Beispielkunde AG" in t, f"{who}: the list lines without a value go {t!r}")
    pf = S.get(B + f"{GD}/{g}/pdf")
    check(pf.ok and hx("{{offer") not in pdf_hex(pf.content) and RED not in pdf_hex(pf.content), f"{who}: the final PDF carries no {{{{ and no red")
    # ---- with a quotation: net / gross, the contract sample with the payment term of the settings
    of = S.post(B + O + "/docs", json={"kind": "offer", "client_id": cl, "project_title": "Imagefilm",
                                       "items": [{"title": "Schnitt", "qty": 2, "rate": 500}]}).json()["id"]
    pv = S.post(B + GD + "/preview", json={"body": "{{offer.net}}|{{offer.gross}}|{{offer.total}}|{{payment.days}}", "client_id": cl, "doc_id": of}).json()
    check(pv["text"].startswith("1.000,00") and "|1.190,00" in pv["text"] and pv["text"].endswith("|30") and pv["missing"] == [],
          f"{who}: offer.net / offer.gross / offer.total / payment.days {pv['text']!r}")
    ct = S.post(B + TP, json={"starter": "contract", "lang": "de"}).json()
    pv = S.post(B + GD + "/preview", json={"template_id": ct["id"], "client_id": cl, "doc_id": of}).json()
    check("innerhalb von 30 Tagen" in pv["text"] and "zzgl. USt" in pv["text"] and "14 Tagen" not in pv["text"], f"{who}: contract: payment term + net {pv['text'][:500]!r}")
    check("Beispielkunde AG, Kundenweg 5, 20000 Hamburg (Auftraggeber)" in pv["text"], f"{who}: the address in running text with ', ' {pv['text'][:300]!r}")
    pv = S.post(B + GD + "/preview", json={"body": "{{client.address}}\nText", "client_id": cl}).json()
    check(pv["text"] == "Kundenweg 5\n20000 Hamburg\nText", f"{who}: the address alone on its line keeps its lines {pv['text']!r}")
    # 2.296.0 F (#3165): payment.days = the client's own payment term when it has one (was always the office's)
    c10 = S.post(B + "/api/clients", json={"name": "Beispielkunde Zwei AG", "street": "Kundenweg 7", "zip": "20000", "city": "Hamburg",
                                           "country": "DE", "payment_terms_days": 10}).json()["id"]
    pv = S.post(B + GD + "/preview", json={"body": "{{payment.days}}", "client_id": c10}).json()
    check(pv["text"] == "10", f"{who}: F payment.days of the client's payment term {pv['text']!r}")
    # 2.296.0 F (#3165): [[ ... ]] without a variable is the person's own text and stays (was "1" / "Name" without brackets)
    pv = S.post(B + GD + "/preview", json={"body": "Punkt [[1]] für [[Name]][[ in {{project.title}}]].", "client_id": cl}).json()
    check(pv["text"].startswith("Punkt [[1]] für [[Name]]"), f"{who}: F [[ ]] without a variable unchanged {pv['text']!r}")
    # ---- a letter from a template
    tl =S.post(B + TP, json={"kind": "letter", "name": "Brief", "lang": "de", "body": "Zu Angebot {{offer.number}} vom {{offer.date}}: Text.\n{{client.name}}"}).json()
    r = S.post(B + O + "/letters", json={"template_id": tl["id"], "client_id": cl})
    j = r.json() if r.status_code == 201 else {}
    check(r.status_code == 201 and j.get("unfilled") == ["offer.number", "offer.date"] and "Quotation number" in (j.get("unfilled_labels") or [])
          and j.get("body") == "Zu Angebot vom: Text.\nBeispielkunde AG", f"{who}: a letter from a template names the unfilled details {r.status_code} {j.get('body')!r} {j.get('unfilled')}")
    r = S.post(B + O + "/letters", json={"template_id": tl["id"], "client_id": cl, "body": "Eigener Text"})
    check(r.status_code == 201 and "unfilled" not in r.json(), f"{who}: an own text: nothing named")


run(A, "org admin")
FID, Fr = freelancer(B, A)
run(Fr, "freelancer")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
