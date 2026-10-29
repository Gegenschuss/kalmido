#!/usr/bin/env python3
# kalmido-suite:
"""2.431.0 B API tests (#3595, #3594, #3605): the office documents' correction name, subject and finalise preview, own
container (start.sh). Invented companies and figures only. freelancer-matrix: office
 - #3595 the default credit note scheme is RK-{yyyy}-{seq:03} (was GS-); a credit note is finalised as RK-...
 - #3594 the subject (project_title) keeps its line breaks (CR LF -> LF), up to 1000 characters (was 200); the PDF prints
   both lines, the e-invoice XML carries it on one line
 - #3605 GET /api/office/docs/<id>/number-preview: the number finalising gives (invoice, credit note, reminder, delivery
   note; a quotation's own number), the counter does not move (two previews alike, the counter row unchanged), a finalised
   document names its number (given); another office's document: 404
 - each for an organisation's admin and for a person without organisation (personal office)
usage: p2431_b_api_test.py <datadir>      (KMT_NOSTART=1 / P2431B_NOSTART=1: a running server)"""
import io
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check, done, fresh, setup  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

fresh({"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2431B")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, F = freelancer(B, A)
O = "/api/office"
D = O + "/docs"
TEST_IBAN = "DE02120300000000202051"
REC = {"name": "Beispielkunde AG", "lines": ["Marktplatz 2", "54321 Beispielort"]}
DOCS = {}


def pv(S, did):
    r = S.get(B + f"{D}/{did}/number-preview")
    return r.json() if r.ok else {"http": r.status_code}


def counters():
    return sorted(tuple(x) for x in dbxm.q(DATA, "SELECT org_id, kind, period, last FROM office_numbers"))


def preview_then_finalize(who, S, did, what):
    """The preview twice (alike, no counter moved), then finalising gives exactly that number; afterwards it is 'given'."""
    before = counters()
    p1, p2 = pv(S, did), pv(S, did)
    check(p1.get("number") and p1.get("given") is False and p1 == p2, f"{who}: #3605 {what}: the preview names the next number {p1} {p2}")
    check(counters() == before, f"{who}: #3605 {what}: the preview moves no counter")
    r = S.post(B + f"{D}/{did}/finalize")
    check(r.ok and r.json().get("number") == p1.get("number"), f"{who}: #3605 {what}: finalised as the previewed number {p1.get('number')} " + r.text[:160])
    p3 = pv(S, did)
    check(p3.get("number") == p1.get("number") and p3.get("given") is True, f"{who}: #3605 {what}: finalised = its own number {p3}")
    return p1.get("number") or ""


for who, S in (("org admin", A), ("freelancer", F)):
    r = S.put(B + O + "/settings", json={"lang": "de", "currency": "EUR",
                                         "company_fields": {"name": "Beispiel Studio GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt",
                                                            "country": "DE", "email": "kontakt@example.com", "tax_number": "12/345/67890",
                                                            "vat_id": "DE999999999", "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
    check(r.ok, f"{who}: office settings " + r.text[:160])
    # ---- #3595 the default scheme of credit notes
    st = S.get(B + O + "/settings").json()
    st = st.get("settings", st)
    check(st.get("credit_scheme") == "RK-{yyyy}-{seq:03}", f"{who}: #3595 the default credit note scheme is RK- ({st.get('credit_scheme')})")

    # ---- #3594 the subject: line breaks kept, up to 1000 characters
    r = S.post(B + D, json={"kind": "invoice", "project_title": "Imagefilm Hafen\r\nDreh und Schnitt", "recipient": REC, "service_from": "2026-05-01",
                            "items": [{"title": "Kamera", "qty": 1, "rate": 500}]})
    check(r.status_code == 201 and r.json()["project_title"] == "Imagefilm Hafen\nDreh und Schnitt", f"{who}: #3594 the subject keeps its line break " + r.text[:200])
    IID = r.json()["id"]
    for n, want in ((1000, 1000), (1001, 1000)):
        r = S.patch(B + f"{D}/{IID}", json={"project_title": "x" * n})
        check(r.ok and len(r.json()["project_title"]) == want, f"{who}: #3594 a subject of {n} characters is stored with {want} ({len(r.json().get('project_title') or '')})")
    S.patch(B + f"{D}/{IID}", json={"project_title": "Imagefilm Hafen\nDreh und Schnitt"})

    # ---- #3605 invoice: preview = the number it gets
    inv_no = preview_then_finalize(who, S, IID, "invoice")
    check(inv_no.startswith("RE-"), f"{who}: the invoice series {inv_no}")
    # a second invoice: the next number
    r = S.post(B + D, json={"kind": "invoice", "project_title": "Werbespot", "recipient": REC, "service_from": "2026-05-02",
                            "items": [{"title": "Schnitt", "qty": 2, "rate": 400}]})
    I2 = r.json()["id"]
    n2 = preview_then_finalize(who, S, I2, "second invoice")
    check(n2 != inv_no and n2.startswith("RE-"), f"{who}: #3605 the second invoice previews the following number {inv_no} -> {n2}")

    # ---- #3594 the PDF prints both lines, the e-invoice and the export carry one line
    pdf = S.get(B + f"{D}/{IID}/pdf")
    t = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf.content)).pages) if pdf.ok else ""
    check("Imagefilm Hafen\nDreh und Schnitt" in t, f"{who}: #3594 the PDF prints the subject on two lines")
    x = S.get(B + f"{D}/{IID}/xml")
    xt = x.content.decode("utf-8", "replace") if x.ok else ""
    check(x.ok and "Imagefilm Hafen Dreh und Schnitt" in xt and "Imagefilm Hafen\nDreh" not in xt, f"{who}: #3594 the e-invoice note on one line {x.status_code}")

    # ---- #3595 / #3605 credit note: RK- and its preview
    r = S.post(B + f"{D}/{I2}/credit")
    check(r.status_code == 201, f"{who}: credit note draft " + r.text[:160])
    cr_no = preview_then_finalize(who, S, r.json()["id"], "credit note")
    check(cr_no.startswith("RK-"), f"{who}: #3595 the credit note is numbered RK- ({cr_no})")

    # ---- #3605 reminder
    dbxm.overdue(DATA, [IID])
    r = S.post(B + f"{D}/reminder", json={"doc_ids": [IID], "level": 1})
    check(r.status_code == 201, f"{who}: reminder draft " + r.text[:160])
    preview_then_finalize(who, S, r.json()["id"], "reminder")

    # ---- #3605 quotation (numbered when made): its own number; delivery note from it
    r = S.post(B + D, json={"kind": "offer", "project_title": "Imagefilm Hafen", "recipient": REC, "items": [{"title": "Kamera", "qty": 1, "rate": 500}]})
    Q = r.json()
    p = pv(S, Q["id"])
    check(Q.get("number") and p.get("number") == Q["number"] and p.get("given") is True, f"{who}: #3605 a quotation names its own number {p} {Q.get('number')}")
    r = S.post(B + f"{D}/{Q['id']}/delivery")
    check(r.status_code == 201, f"{who}: delivery note draft " + r.text[:160])
    if r.status_code == 201:
        preview_then_finalize(who, S, r.json()["id"], "delivery note")
    DOCS[who] = IID

# ---- #3605 another office's document: not found (the organisation's doc for the freelancer and back)
check(F.get(B + f"{D}/{DOCS['org admin']}/number-preview").status_code in (403, 404), "#3605: the freelancer cannot preview the organisation's document")
check(A.get(B + f"{D}/{DOCS['freelancer']}/number-preview").status_code in (403, 404), "#3605: the organisation cannot preview the freelancer's document")

sys.exit(done("p2431_b_api"))
