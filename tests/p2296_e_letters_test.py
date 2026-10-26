#!/usr/bin/env python3
"""2.296.0 E (#3170): letters with a long address and a company name of three lines. Own container (start.sh). Invented data only.
freelancer-matrix: office
 - a recipient of eleven address lines: every line is printed (was: the first wrapped part of the first nine lines), the letter
   text starts below the last of them, the layout is clean; the letter's JSON carries a warning (more lines than the address
   field holds); a short address: no warning
 - a company name of three lines with an extra address line: the sender line above the address field keeps street and town
   and fits the field (was: cut from the back, street and town lost)
 - a person without organisation (personal office): the same
usage: p2296_e_letters_test.py <datadir>      (P2296E_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import base64
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import pdfcheck  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, done, fresh, setup  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
fresh({"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2296E")
O = "/api/office"
MM = 72 / 25.4
CO = {"name": "Studio Nordlicht GmbH\nFilm · Foto · Motion Design\nNiederlassung Hamburg-Altona", "street": "Große Elbstraße 145b",
      "address_extra": "Hinterhaus, 3. OG", "zip": "20457", "city": "Hamburg", "country": "DE", "email": "hallo@studio-nordlicht.example",
      "register_court": "Amtsgericht Hamburg", "register_no": "HRB 123456", "iban": "DE89370400440532013000"}

A = setup("alice", "Alice Admin", lang="en")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs,files", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office

ADDR = [f"Adresszeile {i}" for i in range(1, 11)]
for who, s in (("org", A), ("freelancer", Fr)):
    r = s.put(B + O + "/settings", json={"lang": "de", "company_fields": dict(CO)})
    check(r.ok, f"{who}: company data saved {r.text[:200]}")
    r = s.post(B + O + "/letters", json={"rcpt_name": "Beispielkunde AG", "rcpt_address": "\n".join(ADDR), "subject": "Lange Anschrift",
                                         "body": "Sehr geehrte Damen und Herren,\n\ndies ist der Brieftext."})
    check(r.status_code == 201, f"{who}: letter created {r.status_code} {r.text[:200]}")
    lid = r.json().get("id")
    w = r.json().get("warnings")
    check(isinstance(w, list) and len(w) == 1 and "11" in w[0], f"#3170 {who}: eleven address lines -> a warning in the letter {w}")
    check(len(s.get(B + O + f"/letters/{lid}").json().get("warnings") or []) == 1, f"#3170 {who}: the warning also when the letter is read again")
    r = s.get(B + O + f"/letters/{lid}/pdf")
    check(r.ok and r.content.startswith(b"%PDF"), f"{who}: letter PDF {r.status_code}")
    pr = pdfcheck.problems(r.content)
    check(not pr, f"#3170 {who}: letter layout clean {pr[:4]}")
    p = pdfcheck.layout(r.content)[0]
    allt = [t["s"] for t in p["texts"]]
    check(all(a in allt for a in ADDR), f"#3170 {who}: every address line printed")
    last = max(t["y"] for t in p["texts"] if t["s"] in ADDR)
    body = [t for t in p["texts"] if t["s"].startswith("Sehr geehrte")]
    check(body and body[0]["y"] > last + 10, f"#3170 {who}: the letter text starts below the address")
    snd = [t["s"] for t in p["texts"] if t["size"] == 7 and t["s"].count(" · ") >= 2]
    check(len(snd) == 1 and "Große Elbstraße 145b" in snd[0] and "20457 Hamburg" in snd[0], f"#3170 {who}: the sender line keeps street and town {snd}")
    check(snd and snd[0].startswith("Studio Nordlicht GmbH"), f"#3170 {who}: the sender line starts with the company name {snd}")
    check(not [x for x in pdfcheck.problems(r.content) if "side margins" in x], f"#3170 {who}: the sender line fits the page")
    r = s.post(B + O + "/letters", json={"rcpt_name": "Beispielkunde AG", "rcpt_address": "Marktplatz 2\n54321 Beispielort", "subject": "Kurz", "body": "Text."})
    check(r.status_code == 201 and r.json().get("warnings") == [], f"#3170 {who}: a short address, no warning {r.json().get('warnings')}")

sys.exit(done("p2296_e_letters"))  # bundle 2.305: the exit code (was 0 with failures)
