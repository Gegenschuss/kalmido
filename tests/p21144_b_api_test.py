#!/usr/bin/env python3
"""2.114.4 API tests, part B (#2270): the order confirmation block of a quotation PDF can be switched off.
Invented names and amounts only.
 - the office setting accept_on is on by default; a new quotation follows it (accept_on null, accept_print 1) and its PDF
   carries the order confirmation; setting off = no block; per quotation 1 / 0 wins over the setting either way
 - the reference line to the rights appendix stands exactly once, with and without the block, when the appendix has a page of
   its own; 2.357.0 C (#3182): an appendix that fits on the last page stands there without the reference line
 - a finalised quotation keeps the value it was finalised with: changing the setting later changes its PDF not; a
   finalised quotation cannot be switched (409)
 - a member without office admin rights cannot change the setting (403, unchanged)
 - a person without an organisation (own personal office) alike
usage: p21144_b_api_test.py <datadir>      (a fresh container; P21144B_NOSTART=1 = the server already runs)"""
import io
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer, login  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
D = "/api/office/docs"
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)
ACCEPT, SEE = "ORDERCONFIRMATION", "Transferofrightsseeappendix"
RIGHTS = {"time": "in perpetuity", "territory": "worldwide", "media": "internal use, web", "exceptions": "", "exclusive": 0,
          "note": "Otherwise, our terms apply."}
CLIENT = {"name": "Example Client AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Cologne", "country": "DE",
          "email_invoice": "billing@client.example", "payment_terms_days": 14}


def squash(s):
    return re.sub(r"\s+", "", s or "")


def pdf_text(S, did):
    r = S.get(B + f"{D}/{did}/pdf")
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        return None
    return squash("\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages))


def see_ok(S, did):
    """The reference line once when the rights appendix has a page of its own, none when it stands inline (2.357.0 C, #3182)."""
    r = S.get(B + f"{D}/{did}/pdf")
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        return False
    pages = [squash(p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages]
    app = [t for t in pages if "inperpetuity" in t]  # the page with the appendix (its rights text)
    own = len(app) == 1 and "Concept" not in app[0]  # not on the page with the positions
    return len(app) == 1 and "".join(pages).count(SEE) == (1 if own else 0)


def has_accept(S, did):
    t = pdf_text(S, did)
    return None if t is None else ACCEPT in t.upper()


def setting(S, v):
    r = S.put(B + "/api/office/settings", json={"accept_on": v})
    check(r.ok and r.json()["settings"]["accept_on"] == v, f"setting accept_on={v} {r.text[:200]}")


if not os.environ.get("P21144B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123",
                                   "email": "bob@example.com"})
assert r.ok, r.text
Bo = login(B, "bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done", "workspace": f"org:{ORG}"})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})


def scenario(S, who):
    r = S.put(B + "/api/office/settings", json={"lang": "en", "currency": "EUR"})
    check(r.ok and r.json()["settings"].get("accept_on") == 1, f"{who}: the setting is on by default {r.text[:200]}")
    cl = S.post(B + "/api/clients", json=CLIENT).json().get("id")

    def offer(title):
        r = S.post(B + D, json={"kind": "offer", "lang": "en", "project_title": title, "client_id": cl,
                                "items": [{"title": "Concept", "qty": 1, "rate": 800}]})
        check(r.status_code == 201, f"{who}: quotation {title} {r.text[:200]}")
        did = r.json()["id"]
        S.patch(B + f"{D}/{did}", json={"rights": RIGHTS, "closing": "We look forward to working with you."})
        return did

    q = offer("Default")
    d = S.get(B + f"{D}/{q}").json()
    check(d.get("accept_on") is None and d.get("accept_print") == 1, f"{who}: a new quotation follows the setting {d.get('accept_on')} {d.get('accept_print')}")
    t = pdf_text(S, q)
    check(t is not None and ACCEPT in t.upper(), f"{who}: setting on = order confirmation in the PDF")
    check(see_ok(S, q), f"{who}: with the block the reference line stands once (none with the appendix inline)")
    setting(S, 0)
    t = pdf_text(S, q)
    check(t is not None and ACCEPT not in t.upper(), f"{who}: setting off = no order confirmation")
    check(see_ok(S, q), f"{who}: without the block the reference line still stands once (none with the appendix inline)")
    check(S.get(B + f"{D}/{q}").json().get("accept_print") == 0, f"{who}: accept_print follows the setting")
    r = S.patch(B + f"{D}/{q}", json={"accept_on": 1})
    check(r.ok and r.json().get("accept_on") == 1 and r.json().get("accept_print") == 1, f"{who}: quotation on {r.text[:200]}")
    check(has_accept(S, q) is True, f"{who}: quotation on wins over the setting off")
    setting(S, 1)
    r = S.patch(B + f"{D}/{q}", json={"accept_on": 0})
    check(r.ok and r.json().get("accept_on") == 0, f"{who}: quotation off {r.text[:200]}")
    check(has_accept(S, q) is False, f"{who}: quotation off wins over the setting on")
    r = S.patch(B + f"{D}/{q}", json={"accept_on": None})
    check(r.ok and r.json().get("accept_on") is None and has_accept(S, q) is True, f"{who}: back to like the setting")
    # finalised: the value is frozen
    f1 = offer("Frozen off")
    setting(S, 0)
    r = S.post(B + f"{D}/{f1}/finalize")
    check(r.ok and r.json().get("locked") is True, f"{who}: finalised {r.text[:200]}")
    setting(S, 1)
    check(has_accept(S, f1) is False and S.get(B + f"{D}/{f1}").json().get("accept_print") == 0,
          f"{who}: finalised with the setting off stays without the block after switching on")
    f2 = offer("Frozen on")
    check(S.post(B + f"{D}/{f2}/finalize").ok, f"{who}: second finalised")
    setting(S, 0)
    check(has_accept(S, f2) is True, f"{who}: finalised with the setting on keeps the block after switching off")
    check(S.patch(B + f"{D}/{f2}", json={"accept_on": 0}).status_code == 409, f"{who}: a finalised quotation cannot be switched")
    setting(S, 1)


# ---------------------------------------------------------------- an organisation's office
scenario(A, "org")
# a member without office admin rights cannot change the organisation's setting
r = Bo.put(B + "/api/office/settings", json={"accept_on": 0})
check(r.status_code == 403, f"member: setting 403 ({r.status_code})")
check(A.get(B + "/api/office/settings").json()["settings"]["accept_on"] == 1, "member: the setting is unchanged")
# ---------------------------------------------------------------- a person without an organisation
FID, F = freelancer(B, A)
# freelancer-matrix: office
scenario(F, "freelancer")
check(A.get(B + "/api/office/settings").json()["settings"]["accept_on"] == 1, "the freelancer's setting does not touch the organisation's")

print(f"p21144_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
