#!/usr/bin/env python3
"""2.138.2 API tests, part A (office documents), own container (start.sh). Invented names, services and amounts only.
 - #2393: every PDF of a document that is not finalised is marked: DRAFT / ENTWURF (the document's language) at the number
   and on every page (a quotation over several pages), also ?inline=1 and the agents' GET /api/v1/office/docs/<id>/pdf;
   the finalised quotation / invoice and a quotation sent without finalising carry no mark; a draft invoice has no e-invoice (XML 409, a ZUGFeRD draft PDF
   without an embedded file), the finalised one has both
 - #2391: the building block {isodate} (yyyy-mm-dd): {client}_{project}_KV{seq:02}_{isodate}_{initials} counted per
   project gives DAF_Beteiligung_KV04_2026-04-15_MG; {date} stays 20260415; underscores and umlauts of a project stay;
   the preview knows it, an unknown block names it; an invoice scheme with {isodate}
 - freelancer-matrix: office (a person without an organisation: the same, English documents = DRAFT)
usage: p21381_a_api_test.py <datadir>      (P21381A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import io
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
TEST_IBAN = "DE02120300000000202051"
COMPANY = {"name": "Studio Beispiel GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hallo@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
           "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
SCHEME = "{client}_{project}_KV{seq:02}_{isodate}_{initials}"


def pages_text(data):
    """the text of every page, white space removed"""
    return [re.sub(r"\s+", "", p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages]


def pdf(S, did, inline=False):
    r = S.get(B + f"{D}/{did}/pdf" + ("?inline=1" if inline else ""))
    check(r.ok and r.content.startswith(b"%PDF"), f"PDF of {did}: {r.status_code} {r.text[:200] if not r.ok else ''}")
    return r.content if r.ok else b""


def offer(S, tag, project, day="2026-04-15", **kw):
    r = S.post(B + D, json={"client_id": kw.pop("client"), "project_title": project, "date": day, **kw})
    check(r.status_code == 201, f"{tag}: a quotation " + r.text[:200])
    return r.json().get("id"), r.json().get("number") or ""


def run(S, tag, initials, word, other_word, agent_org=None):
    # ---------------------------------------------------------------- #2391 {isodate}
    S.get(B + O + "/settings")
    r = S.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "de" if word == "ENTWURF" else "en", "currency": "EUR",
                                         "offer_counter": "project", "offer_scheme": SCHEME, "einvoice_format": "zugferd"})
    check(r.ok, f"{tag}: settings with {{isodate}} saved " + r.text[:200])
    r = S.post(B + "/api/clients", json={"name": "DAF", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
                                         "email_invoice": "rechnung@kunde.example"})
    check(r.status_code in (200, 201), f"{tag}: client " + r.text[:200])
    CL = r.json().get("id")
    nums = [offer(S, tag, "Beteiligung", client=CL) for _ in range(4)]
    want = f"DAF_Beteiligung_KV04_2026-04-15_{initials}"
    check(nums[3][1] == want, f"{tag}: the 4th quotation of the project is {want}: {[n for _, n in nums]}")
    _, n = offer(S, tag, "Über_Mut Film", client=CL)
    check(n == f"DAF_Über_Mut-Film_KV01_2026-04-15_{initials}", f"{tag}: underscore and umlaut of the project stay, a space becomes - : {n}")
    check(S.put(B + O + "/settings", json={"offer_scheme": "{client}_{date}_{seq:02}"}).ok, f"{tag}: scheme with {{date}}")
    _, n = offer(S, tag, "Datum", client=CL)
    check(n == "DAF_20260415_01", f"{tag}: {{date}} stays yyyymmdd: {n}")
    S.put(B + O + "/settings", json={"offer_scheme": SCHEME})
    j = S.get(B + O + "/number-preview", params={"kind": "offer", "scheme": "KV-{isodate}-{seq:02}"}).json()
    check(j.get("valid") and re.fullmatch(r"KV-\d{4}-\d\d-\d\d-01", j.get("preview") or ""), f"{tag}: the preview knows {{isodate}} {j}")
    j = S.get(B + O + "/number-preview", params={"kind": "offer", "scheme": "KV-{isodat}-{seq}"}).json()
    check(not j.get("valid") and "{isodate}" in (j.get("error") or ""), f"{tag}: an unknown block names {{isodate}} {j}")
    r = S.put(B + O + "/settings", json={"invoice_scheme": "RE-{isodate}-{seq:03}"})
    check(r.ok, f"{tag}: invoice scheme with {{isodate}} " + r.text[:200])

    # ---------------------------------------------------------------- #2393 a draft quotation over several pages
    QID, QN = nums[3]
    r = S.put(B + f"{D}/{QID}/items", json={"items": [{"title": f"Leistung {i}", "detail": "Beschreibung der Leistung", "qty": 1, "rate": 100 + i}
                                                      for i in range(70)]})
    check(r.ok, f"{tag}: 70 positions " + r.text[:200])
    for inline in (False, True):
        t = pages_text(pdf(S, QID, inline))
        check(len(t) >= 2 and all(word in x for x in t), f"{tag}: draft PDF (inline={inline}): {word} on every one of {len(t)} pages")
        check(t and (QN.replace(" ", "") + "·" + word) in t[0], f"{tag}: {word} in bold at the number on page 1")
        check(not any(other_word in x for x in t), f"{tag}: the document's language only ({other_word} nowhere)")
    if agent_org is not False:
        S.put(B + O + "/settings", json={"agents_read": 1})
        r = S.post(B + "/api/my/agents", json={"username": f"{tag}bot", "display_name": "Office Bot", "scopes": ["read", "office"],
                                               **({"org_id": agent_org} if agent_org else {})})
        check(r.status_code == 201, f"{tag}: an agent " + r.text[:200])
        AG, AGT = r.json().get("id"), r.json().get("token")
        check(S.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True}).ok, f"{tag}: the agent's office switch")
        r = requests.get(B + f"/api/v1/office/docs/{QID}/pdf", headers={**H, "Authorization": "Bearer " + AGT})
        t = pages_text(r.content) if r.ok else []
        check(len(t) >= 2 and all(word in x for x in t), f"{tag}: the agent's draft PDF is marked on every page {r.status_code}")
    # a quotation set to sent without finalising: locked since 2.39.0, its customer link serves this PDF -> unmarked
    SID = nums[2][0]
    S.put(B + f"{D}/{SID}/items", json={"items": [{"title": "Konzept", "qty": 1, "rate": 500}]})
    check(S.post(B + f"{D}/{SID}/status", json={"status": "sent"}).ok, f"{tag}: a quotation sent without finalising")
    t = pages_text(pdf(S, SID))
    check(t and not any(word in x for x in t), f"{tag}: the sent, not finalised quotation carries no {word}")
    r = S.post(B + f"{D}/{QID}/finalize")
    check(r.ok and r.json().get("locked") is True, f"{tag}: the quotation is finalised " + r.text[:200])
    t = pages_text(pdf(S, QID))
    check(t and not any(word in x for x in t), f"{tag}: the finalised quotation carries no {word}")

    # ---------------------------------------------------------------- #2393 a draft invoice: no e-invoice
    r = S.post(B + D, json={"kind": "invoice", "client_id": CL, "project_title": "Beteiligung", "service_from": "2026-04-01",
                            "service_to": "2026-04-30", "payment_days": 14, "date": "2026-05-08"})
    check(r.status_code == 201, f"{tag}: an invoice " + r.text[:200])
    INV = r.json().get("id")
    S.put(B + f"{D}/{INV}/items", json={"items": [{"title": "Filmherstellung", "qty": 1, "rate": 1200}]})
    data = pdf(S, INV)
    t = pages_text(data)
    check(t and all(word in x for x in t), f"{tag}: draft invoice PDF marked {word}")
    check(b"/EmbeddedFile" not in data, f"{tag}: the ZUGFeRD draft PDF has no XML inside")
    r = S.get(B + f"{D}/{INV}/xml")
    check(r.status_code == 409 and "finalised" in r.text, f"{tag}: draft invoice XML 409 with a reason {r.status_code} {r.text[:120]}")
    r = S.post(B + f"{D}/{INV}/finalize")
    check(r.ok and r.json().get("number") == "RE-2026-05-08-001", f"{tag}: the invoice finalised with RE-2026-05-08-001 " + r.text[:200])
    data = pdf(S, INV)
    t = pages_text(data)
    check(t and not any(word in x for x in t) and b"/EmbeddedFile" in data, f"{tag}: the finalised invoice: no mark, XML inside")
    check(S.get(B + f"{D}/{INV}/xml").ok, f"{tag}: the finalised invoice's XML")


if not os.environ.get("P21381A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "mara", "display_name": "Mara Gruber", "password": "password123"}).ok
A = sess("mara")
A.post(B + "/api/admin/setup", json={"org_name": "Beispiel Studio", "lang": "en", "modules": ["cal", "comments"]})
FEAT = "cal,comments,collab,clients,office"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
run(A, "org", "MG", "ENTWURF", "DRAFT", agent_org=ORG)

# ---------------------------------------------------------------- freelancer-matrix: office (a person without an organisation, its own admin)
FID, Fr = freelancer(B, A, "frida")
run(Fr, "freelancer", "F", "DRAFT", "ENTWURF", agent_org=None)

print(f"p21381_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
