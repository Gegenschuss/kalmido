#!/usr/bin/env python3
"""2.121.0 API tests, part A (#2092): supplier, VAT, net / gross and the invoice number read off a receipt -- a suggestion a
person takes over. Invented companies, people and figures only. freelancer-matrix: files  tenant-matrix: document
 - unit (pure Python, docs/extract.py ex_details): eleven invented receipt texts (fuel receipt, an English software
   subscription with reverse charge, a craftsman's invoice with 19 % and 7 %, a small business under section 19, an EU
   reverse charge, a bakery receipt without a number, an invoice with customer, order AND invoice number, an English hotel
   bill at 20 %, a table layout, figures that do not add up, a date where the number should be); extract() unchanged
   without details
 - a person without an organisation (private documents, org encryption on): an uploaded invoice is recognised, the
   document carries "extracted" (supplier, number, net, VAT, gross, rate), nothing of it is set on its own (no sender,
   no VAT rate), the stored JSON is sealed; Take over sets sender, VAT rate and amount, the answer's "before" puts them back
   (one undo step); Discard hides it, Show brings it back; a second invoice of the same company (another legal-form
   spelling) finds the same sender; a letter gets no suggestion
 - rights: another person 404, an agent sees the values through the API v1 (shared document) but gets 403 on Take over;
   an organisation's document: the values sealed, a member of another organisation 404
usage: p2121_a_api_test.py <datadir>   (P2121A_NOSTART=1 / KMT_NOSTART=1: the container runs already;
KALMIDO_SRC=<dir with kalmido/> for the unit part)"""
import base64
import importlib.util
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


# ---- unit: the rules ------------------------------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location("p2121a_extract", os.path.join(SRC, "kalmido", "docs", "extract.py"))
X = importlib.util.module_from_spec(spec)
spec.loader.exec_module(X)

S = []
S.append(("fuel", """Tankstelle Beispiel
Hauptstraße 5
12345 Musterstadt
Tel. 0123 456789
Quittung Nr. 4711
Datum 03.10.2026 14:22
Super E10  42,15 l x 1,799
Betrag EUR 75,83
Summe EUR 75,83
enthaltene MwSt 19 %  12,11
Netto 63,72
Vielen Dank für Ihren Besuch
St.-Nr. 12/345/67890
""", {"supplier": "Tankstelle Beispiel", "invoice_no": "4711", "vat_pct": "19", "net": "63.72", "vat": "12.11", "gross": "75.83", "tax_no": "12/345/67890"}))
S.append(("saas_en", """Example Cloud Inc.
100 Market Street, Suite 300
San Francisco, CA 94105
VAT ID: IE1234567X
Bill to:
Muster GmbH
Beispielweg 1
10115 Berlin
Germany
Invoice number INV-2026-0042
Invoice date October 1, 2026
Pro plan (monthly)     $49.00
Subtotal               $49.00
VAT (0%) reverse charge  $0.00
Total                  $49.00
Amount due             $49.00
""", {"supplier": "Example Cloud Inc.", "invoice_no": "INV-2026-0042", "vat_pct": "0", "gross": "49.00", "currency": "USD"}))
S.append(("craft_mixed", """Muster Bau GmbH · Werkstraße 12 · 54321 Beispielort
Herrn
Max Kunde
Am Feld 3
54320 Kundendorf
Rechnung
Rechnungs-Nr.: RE-2026-118
Kundennummer: K-5521
Auftragsnummer: A-778
Datum: 06.10.2026
Arbeitszeit 4 Std.   240,00 €
Material              60,00 €
Fachbuch              20,00 €
Nettobetrag          320,00 €
zzgl. 19 % MwSt. auf 300,00 €   57,00 €
zzgl. 7 % MwSt. auf 20,00 €      1,40 €
Gesamtbetrag         378,40 €
Zahlbar bis 20.10.2026
USt-IdNr. DE123456789
""", {"supplier": "Muster Bau GmbH", "invoice_no": "RE-2026-118", "vat_pct": "19", "net": "320.00", "vat": "58.40", "gross": "378.40", "vat_id": "DE123456789",
      "rates": {"19": "57.00", "7": "1.40"}}))
S.append(("small_business", """Grafikbüro Beispiel
Inhaberin Erika Muster
Lindenweg 7
80331 München
An
Muster GmbH
Beispielweg 1
10115 Berlin
Rechnung Nr. 2026-07
Datum 02.10.2026
Logo-Entwurf  450,00 EUR
Gesamtbetrag  450,00 EUR
Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.
Steuernummer 143/123/45678
""", {"supplier": "Grafikbüro Beispiel", "invoice_no": "2026-07", "vat_pct": "0", "gross": "450.00", "tax_no": "143/123/45678"}))
S.append(("reverse_eu", """Beispiel Software B.V.
Keizersgracht 1
1015 CJ Amsterdam
BTW: NL123456789B01
Invoice No. 98765
Customer: Muster GmbH, VAT ID DE987654321
Date 30/09/2026
Licence  1.200,00 EUR
Total EUR 1.200,00
VAT reverse charge – Steuerschuldnerschaft des Leistungsempfängers
""", {"supplier": "Beispiel Software B.V.", "invoice_no": "98765", "vat_pct": "0", "gross": "1200.00", "vat_id": "NL123456789B01"}))
S.append(("receipt_no_number", """Bäckerei Musterkorn
Brotgasse 2
12345 Musterstadt
05.10.2026  08:12
2x Brötchen   1,20
1x Kaffee     2,50
Summe EUR     3,70
MwSt 7%  0,24
""", {"supplier": "Bäckerei Musterkorn", "invoice_no": None, "vat_pct": "7", "net": "3.46", "vat": "0.24", "gross": "3.70"}))
S.append(("cust_and_inv", """Beispiel Elektro e.K.
Ringstraße 4, 33333 Beispielhausen
Kunden-Nr. 100234
Bestellnummer 4500012345
Rechnungsnummer 20260915
Rechnungsdatum 15.09.2026
Netto 1.000,00 EUR
MwSt 19 % 190,00 EUR
Rechnungsbetrag 1.190,00 EUR
IBAN DE02 1203 0000 0000 2020 51
""", {"supplier": "Beispiel Elektro e.K.", "invoice_no": "20260915", "vat_pct": "19", "net": "1000.00", "vat": "190.00", "gross": "1190.00"}))
S.append(("hotel_en", """Hotel Example Ltd
1 Example Road, London
Receipt No: R-5531
Date: 12 October 2026
Room 2 nights          GBP 180.00
Net amount             GBP 150.00
VAT 20%                GBP 30.00
Total                  GBP 180.00
""", {"supplier": "Hotel Example Ltd", "invoice_no": "R-5531", "vat_pct": None, "net": "150.00", "vat": "30.00", "gross": "180.00", "currency": "GBP"}))
S.append(("table_layout", """Muster Druck GmbH
Gewerbepark 9
60311 Frankfurt
Rechnungsnummer   Datum
D-0815            08.10.2026
Pos  Menge  Text   Betrag
1    500    Flyer  100,00
Summe netto        100,00
19 % USt           19,00
Gesamt             119,00 EUR
""", {"supplier": "Muster Druck GmbH", "invoice_no": "D-0815", "vat_pct": "19", "net": "100.00", "vat": "19.00", "gross": "119.00"}))
S.append(("mismatch", """Muster Handel GmbH
Rechnung Nr. 55
Netto 100,00 EUR
MwSt 19 % 19,00 EUR
Gesamtbetrag 150,00 EUR
""", {"supplier": "Muster Handel GmbH", "invoice_no": "55", "vat_pct": "19", "net": None, "vat": None, "gross": "150.00"}))
S.append(("letter_date_label", """Beispiel Service UG (haftungsbeschränkt)
Rechnungsnummer: 01.10.2026
Gesamt 10,00 EUR
""", {"supplier": "Beispiel Service UG (haftungsbeschränkt)", "invoice_no": None, "gross": "10.00"}))

for name, text, want in S:
    d = X.ex_details(text)
    for k, v in want.items():
        if k == "rates":
            got = {r["pct"]: r["vat"] for r in d["vat_rates"]}
            check(got == v, f"{name}: VAT rates {got} (want {v})")
        else:
            check(d.get(k) == v, f"{name}: {k} = {d.get(k)!r} (want {v!r})")
r = X.extract(S[0][1])
check("details" not in r and r["amount"] == "75.83", f"extract() without details unchanged {r}")
r = X.extract(S[0][1], details=True)
check(r["details"]["supplier"] == "Tankstelle Beispiel", "extract(details=True) carries the details")
check(X.extract(S[0][1], guess=False, details=True)["details"] is None, "no details for a document that is no invoice")
check(X.ex_details("Telefon 030 12345678\n10115 Berlin\nIBAN DE02120300000000202051\n")["supplier"] is None, "an address is no supplier")
check(X.ex_details("")["gross"] is None and X.ex_details(None)["vat_rates"] == [], "empty text: nothing")
if os.environ.get("P2121A_UNIT_ONLY"):
    print(f"p2121_a unit: {OKS[0]} ok, {len(FAILS)} failed")
    sys.exit(1 if FAILS else 0)


# ---- the server ---------------------------------------------------------------------------------------------------------
def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def upload(s, name, text, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, text.encode(), "text/plain")})
    assert r.ok, r.text
    j = r.json()
    return (j.get("ids") or [x["id"] for x in j.get("docs") or j.get("items") or []])[0]


def done(s, nid, secs=60):
    end = time.time() + secs
    while time.time() < end:
        r = s.get(B + f"/api/docs/{nid}")
        if r.ok and r.json()["state"] in ("done", "failed"):
            return r.json()
        time.sleep(0.4)
    return None


def ex(s, nid, body):
    return s.post(B + f"/api/docs/{nid}/extracted", json=body)


def rc(s, nid):
    return s.get(B + f"/api/docs/{nid}/receipt").json()["receipt"]


if not (os.environ.get("P2121A_NOSTART") or os.environ.get("KMT_NOSTART")):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
assert A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com"}).ok
Ca = sess("carol")
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
FEAT = "cal,comments,collab,office,clients,docs,files"
for s in (A, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
FID, Fr = freelancer(B, A)  # freelancer-matrix: files (private documents, the own receipts)

# ---- schema: one new column, nothing renamed
cols = {r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_name='doc_meta' AND column_name='extracted'")}
check(cols == {"extracted"}, f"doc_meta.extracted added ({cols})")

# ---- the freelancer: recognise -> suggestion -> take over -> undo
CRAFT = S[2][1]
D1 = upload(Fr, "rechnung-bau.txt", CRAFT)
d = done(Fr, D1)
x = (d or {}).get("extracted") or {}
check(d and d["state"] == "done", f"recognised {d and d['state']}")
check(x.get("supplier") == "Muster Bau GmbH" and x.get("invoice_no") == "RE-2026-118" and x.get("net") == "320.00"
      and x.get("vat") == "58.40" and x.get("gross") == "378.40" and x.get("vat_pct") == "19" and x.get("vat_id") == "DE123456789",
      f"the document carries the recognised values {x}")
check(d and d["amount"] == "378.40", f"the amount as before (the total line) {d and d['amount']}")
check(d and d["sender"] is None and rc(Fr, D1)["vat_pct"] is None, f"nothing set on its own (sender {d and d['sender']})")
check(set(x.get("new") or []) == {"vat_pct", "sender"} and x.get("hidden") is False, f"take over would change rate + sender {x.get('new')}")
raw = dbx("SELECT extracted FROM doc_meta WHERE node_id=?", (D1,))[0][0]
check(raw.startswith("kenc1:") and "Muster" not in raw, f"stored sealed ({raw[:12]})")

Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
check(ex(Ca, D1, {"do": "apply"}).status_code == 404, "another person: 404")
check(ex(Fr, D1, {"do": "nonsense"}).status_code == 400, "an unknown action: 400")
check(ex(Fr, D1, {"do": "apply", "fields": ["name"]}).status_code == 400, "an unknown field: 400")

r = ex(Fr, D1, {"do": "apply"})
j = r.json() if r.ok else {}
doc = j.get("doc") or {}
check(r.ok and (doc.get("sender") or {}).get("name") == "Muster Bau GmbH" and doc.get("amount") == "378.40", f"taken over: sender {r.text[:300]}")
check(rc(Fr, D1)["vat_pct"] == "19", "taken over: the VAT rate of the receipt")
check(j.get("before") == {"amount": "378.40", "currency": "EUR", "sender": None, "vat_pct": None, "is_receipt": False}, f"the values before {j.get('before')}")
check((doc.get("extracted") or {}).get("new") == [], f"same values: no line any more {(doc.get('extracted') or {}).get('new')}")
SENDER = (doc.get("sender") or {}).get("id")

r = ex(Fr, D1, {"do": "restore", "before": j.get("before")})
doc = r.json().get("doc") if r.ok else {}
check(r.ok and doc.get("sender") is None and rc(Fr, D1)["is_receipt"] is False, f"undo: sender and receipt back {r.text[:200]}")
check(set((doc.get("extracted") or {}).get("new") or []) == {"vat_pct", "sender"}, "undo: the suggestion is back")
check(ex(Fr, D1, {"do": "restore", "before": {"sender": "x"}}).status_code == 400, "undo with a bad sender: 400")
check(ex(Fr, D1, {"do": "restore", "before": {"vat_pct": "16"}}).status_code == 400, "undo with a bad rate: 400")
r = ex(Fr, D1, {"do": "apply", "fields": ["vat_pct"]})
check(r.ok and rc(Fr, D1)["vat_pct"] == "19" and r.json()["doc"]["sender"] is None, "take over one field only")
ex(Fr, D1, {"do": "apply"})

r = ex(Fr, D1, {"do": "dismiss"})
check(r.ok and r.json()["doc"]["extracted"]["hidden"] is True, "discard: hidden")
r = ex(Fr, D1, {"do": "show"})
check(r.ok and r.json()["doc"]["extracted"]["hidden"] is False, "undo of discard: shown again")

# a second invoice of the same company (another spelling) finds the same sender
D2 = upload(Fr, "rechnung-bau-2.txt", CRAFT.replace("Muster Bau GmbH ·", "Muster Bau GmbH & Co. KG ·").replace("RE-2026-118", "RE-2026-140"))
d2 = done(Fr, D2)
r = ex(Fr, D2, {"do": "apply"})
check(r.ok and (r.json()["doc"].get("sender") or {}).get("id") == SENDER, f"the same sender found again {r.text[:200]}")

# a letter: no suggestion
D3 = upload(Fr, "brief.txt", "Liebe Frau Beispiel,\nanbei der Plan fuer 2027.\nViele Gruesse\n")
d3 = done(Fr, D3)
check(d3 and d3.get("extracted") is None, f"a letter: no suggestion {d3 and d3.get('extracted')}")
check(ex(Fr, D3, {"do": "apply"}).status_code == 404, "take over without a suggestion: 404")

# ---- an agent: reads the values of a shared document, never takes them over
r = A.post(B + "/api/admin/agents", json={"username": "fridabot", "display_name": "Fridabot"})
assert r.status_code == 201, r.text
AG, AGS = r.json()["id"], tok(r.json().get("token") or "")
dbx("DELETE FROM org_members WHERE user_id=?", (AG,), write=True)
dbx("UPDATE agents SET org_id=NULL, owner_id=? WHERE user_id=?", (FID, AG), write=True)
check(Fr.post(B + f"/api/files/nodes/{D1}/shares", json={"agent_id": AG, "role": "edit"}).ok, "setup: shared with the agent")
r = AGS.get(B + f"/api/v1/documents/{D1}")
check(r.ok and (r.json().get("extracted") or {}).get("invoice_no") == "RE-2026-118", f"the agent reads the values {r.status_code} {r.text[:200]}")
check(AGS.get(B + f"/api/v1/documents/{D3}").status_code == 404, "not shared: 404 for the agent")
check(AGS.post(B + f"/api/docs/{D1}/extracted", json={"do": "apply"}).status_code == 403, "the agent cannot take over (403)")
spec_ = A.get(B + "/api/v1/openapi.json")
check(spec_.ok and "extracted" in spec_.json()["components"]["schemas"]["Document"]["properties"], "OpenAPI: Document.extracted")

# ---- an organisation's document: sealed, another organisation 404
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
D4 = upload(A, "rechnung-druck.txt", S[8][1], ws=f"org:{ORG}")
d4 = done(A, D4)
check(d4 and (d4.get("extracted") or {}).get("invoice_no") == "D-0815", f"org document recognised {d4 and d4.get('extracted')}")
raw = dbx("SELECT extracted FROM doc_meta WHERE node_id=?", (D4,))[0][0]
check(raw.startswith("kenc1:") and "Druck" not in raw, "org: stored sealed")
check(ex(Ca, D4, {"do": "apply"}).status_code == 404 and Ca.get(B + f"/api/docs/{D4}").status_code == 404, "another organisation: 404")
r = ex(A, D4, {"do": "apply"})
check(r.ok and rc(A, D4)["vat_pct"] == "19" and (r.json()["doc"].get("sender") or {}).get("name") == "Muster Druck GmbH", "org admin takes over")
# the document into the private space: the values move along (sealed for the new workspace)
r = A.post(B + "/api/files/move-space", json={"ids": [D4], "to": "private", "parent": None})
check(r.ok, f"move into the private space {r.status_code} {r.text[:200]}")
A.patch(B + "/api/settings", json={"workspace": "private"})
d4 = A.get(B + f"/api/docs/{D4}").json()
raw2 = dbx("SELECT extracted FROM doc_meta WHERE node_id=?", (D4,))[0][0]
check((d4.get("extracted") or {}).get("invoice_no") == "D-0815" and raw2.startswith("kenc1:") and raw2 != raw, f"moved: the values open in the new workspace {d4.get('extracted')}")

print(f"p2121_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
