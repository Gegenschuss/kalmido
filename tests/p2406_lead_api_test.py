#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.406.0 (#3501): the logo frame of the office PDFs (office settings "logo_size": "s" | "m" | "l", "logo_pos": "l" | "r")
through the API. Own container (start.sh). Invented companies and figures only; the logo is made here.
freelancer-matrix: office
 - the settings: default medium + right, every value saved and read back, anything else 400
 - a draft invoice and a letter print the logo in the chosen frame and side; a finalised invoice keeps the frame it was
   finalised with when the setting changes later
 - a person without organisation (personal office): the same settings and PDFs
usage: p2406_lead_api_test.py <datadir>      (P2406L_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import io
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, done, fresh, setup  # noqa: E402
from pypdf import PdfReader  # noqa: E402

fresh(prefix="P2406L")
O = "/api/office"
D = O + "/docs"
MM = 72 / 25.4
A4_W = 595.28
CO = {"name": "Beispielstudio GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
      "email": "kontakt@example.com", "phone": "+49 30 000000", "tax_number": "12/345/67890", "vat_id": "DE999999999",
      "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
LOGO_RE = re.compile(rb"q ([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm /Logo Do Q")

A = setup("alice", "Alice Admin", lang="en")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs,files", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office


def picture():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (1600, 400), (47, 93, 138)).save(out, "PNG")  # wide: fills the frame's width
    return out.getvalue()


def logo(s, url, what):
    """(width mm, x pt) of the logo on page 1 of the PDF at url."""
    r = s.get(B + url)
    check(r.ok and r.content.startswith(b"%PDF"), f"{what}: PDF {r.status_code} {r.text[:120] if not r.ok else ''}")
    if not r.ok:
        return None
    m = LOGO_RE.search(PdfReader(io.BytesIO(r.content)).pages[0].get_contents().get_data())
    return (round(float(m.group(1)) / MM, 1), float(m.group(3))) if m else None


def at(got, mm, left):
    return bool(got) and abs(got[0] - mm) < 0.2 and (abs(got[1] - 25 * MM) < 0.1 if left else abs(got[1] + got[0] * MM - (A4_W - 20 * MM)) < 0.2)


for who, s, name in (("org", A, "Beispielstudio GmbH"), ("freelancer", Fr, "Frida Film")):
    r = s.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": dict(CO, name=name)})
    check(r.ok, f"{who}: company data saved {r.text[:200]}")
    r = s.post(B + O + "/logo", files={"file": ("logo.png", picture(), "image/png")})
    check(r.ok, f"{who}: logo uploaded {r.status_code} {r.text[:200]}")
    st = s.get(B + O + "/settings").json()["settings"]
    check(st.get("logo_size") == "m" and st.get("logo_pos") == "r", f"#3501 {who}: default medium + right ({st.get('logo_size')!r}, {st.get('logo_pos')!r})")
    for body in ({"logo_size": "xl"}, {"logo_pos": "c"}, {"logo_size": 1}):
        r = s.put(B + O + "/settings", json=body)
        check(r.status_code == 400, f"#3501 {who}: {body} is refused {r.status_code}")
    cl = s.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktplatz 2", "zip": "54321", "city": "Beispielort",
                                          "country": "DE"}).json().get("id")

    def invoice():
        r = s.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": "2026-10-01", "service_to": "2026-10-20",
                                "items": [{"title": "Leistung", "qty": 1, "rate": 100}]})
        check(r.status_code == 201, f"{who}: invoice created {r.status_code} {r.text[:200]}")
        return r.json().get("id")

    inv = invoice()
    check(at(logo(s, f"{D}/{inv}/pdf", who), 45, False), f"#3501 {who}: the draft prints 45 mm on the right by default")
    for size, mm in (("s", 30), ("l", 60)):
        for pos in ("l", "r"):
            r = s.put(B + O + "/settings", json={"logo_size": size, "logo_pos": pos})
            st = s.get(B + O + "/settings").json()["settings"]
            check(r.ok and st.get("logo_size") == size and st.get("logo_pos") == pos, f"#3501 {who}: {size}/{pos} saved and read back {r.text[:120]}")
            got = logo(s, f"{D}/{inv}/pdf", f"{who} {size}/{pos}")
            check(at(got, mm, pos == "l"), f"#3501 {who}: the draft invoice prints {size}/{pos} ({got})")
    # large left: a letter and a finalised invoice
    r = s.put(B + O + "/settings", json={"logo_size": "l", "logo_pos": "l"})
    r = s.post(B + O + "/letters", json={"rcpt_name": "Amt für Beispiele", "rcpt_address": "Musterweg 1\n12345 Musterstadt", "rcpt_email": "amt@example.com",
                                         "subject": "Antrag 7/2026", "body": "Sehr geehrte Damen und Herren, ein kurzer Brief."})
    check(r.status_code == 201, f"{who}: letter created {r.status_code} {r.text[:200]}")
    got = logo(s, O + f"/letters/{r.json().get('id')}/pdf", f"{who} letter")
    check(at(got, 60, True), f"#3501 {who}: the letter prints large on the left ({got})")
    fin = invoice()
    r = s.post(B + f"{D}/{fin}/finalize")
    check(r.ok and r.json().get("locked"), f"{who}: invoice finalised {r.text[:200]}")
    s.put(B + O + "/settings", json={"logo_size": "s", "logo_pos": "r"})
    got = logo(s, f"{D}/{fin}/pdf", f"{who} finalised")
    check(at(got, 60, True), f"#3501 {who}: the finalised invoice keeps large + left after the change ({got})")
    got = logo(s, f"{D}/{inv}/pdf", f"{who} draft after the change")
    check(at(got, 30, False), f"#3501 {who}: a draft follows the new setting small + right ({got})")
    s.put(B + O + "/settings", json={"logo_size": "m", "logo_pos": "r"})

sys.exit(done("p2406_lead_api"))
