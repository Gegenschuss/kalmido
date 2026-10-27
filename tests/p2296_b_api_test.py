#!/usr/bin/env python3
"""2.296.0 B API tests (#3168, #3169, #3173, #3175): invoice print model, finalise checks, GiroCode and e-invoice of the
personal office of a person without an organisation (freelancer fixture; freelancer-matrix: office), own container (start.sh).
Invented companies, people and the test IBAN only.
 - #3169 the setting exempt_reason (one line, trimmed); a taxed invoice with a 0 % position is not finalised without it
   (400 names the reason); with it: the PDF note (totals.exempt_note), the XML line category E with the reason; a
   finalised invoice keeps the reason it was finalised with
 - #3175 the tax rows name their taxable amount ("MwSt. 19 % auf 1.000,00 €"); a credit note prints as
   "Rechnungskorrektur" with the intro "zu der oben genannten Rechnung"; an English document writes "24 October 2026",
   a French one groups with a no-break space
 - #3168 reverse charge: 400 without the client's VAT id; a Dutch client: meta "USt-IdNr. Kunde", the country line
   "NIEDERLANDE", the EU text (Art. 196); a German client with VAT id: section 13b
 - #3173 the buyer reference visible ("Käuferreferenz", "Leitweg-ID" for XRechnung); the GiroCode asks for the open amount
   after a part payment; the credit note carries the invoice's date (cancels.date, BT-26 in the XML)
usage: p2296_b_api_test.py <datadir>      (P2296B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import re
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
TEST_IBAN = "DE02120300000000202051"
NB = " "
REASON = "Steuerfreie Leistung nach § 4 Nr. 21 UStG"

if os.environ.get("P2296B_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en"})
FID, Fr = freelancer(B, A)

# ---------------------------------------------------------------- the personal office (invented data)
r = Fr.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht"}, "lang": "de", "currency": "EUR", "payment_days": 14,
                                      "company_fields": {"name": "Studio Nordlicht", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                         "country": "DE", "email": "hallo@nordlicht.example", "phone": "+49 40 000000",
                                                         "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN, "bic": "BYLADEM1001",
                                                         "bank_name": "Beispielbank"}})
check(r.ok, "freelancer office settings " + r.text[:200])
st = Fr.get(B + O + "/settings").json()["settings"]
check(st.get("exempt_reason") == "", f"#3169: exempt_reason defaults to empty ({st.get('exempt_reason')!r})")
r = Fr.put(B + O + "/settings", json={"exempt_reason": "  Steuerfreie   Leistung\n x  "})
check(r.ok and Fr.get(B + O + "/settings").json()["settings"]["exempt_reason"] == "Steuerfreie Leistung x", "#3169: exempt_reason trimmed to one line")
Fr.put(B + O + "/settings", json={"exempt_reason": ""})


def client(**kw):
    r = Fr.post(B + "/api/clients", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


CDE = client(name="Beispielkunde AG", street="Marktstraße 5", zip="50667", city="Köln", country="DE")
CDV = client(name="Musterbau GmbH", street="Bauweg 1", zip="80331", city="München", country="DE", vat_id="DE123456789")
CNL = client(name="Exempel B.V.", street="Voorbeeldstraat 10", zip="1012 AB", city="Amsterdam", country="NL", vat_id="NL123456789B01",
             buyer_reference="REF-4711", email="factuur@exempel.example")


def invoice(cl, items, **kw):
    r = Fr.post(B + D, json=dict({"kind": "invoice", "client_id": cl, "service_from": "2026-10-01", "service_to": "2026-10-20", "items": items}, **kw))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def render(did):
    r = Fr.get(B + f"{D}/{did}/render")
    assert r.ok, r.text
    return r.json()


def meta(rd):
    return dict((a, b) for a, b in rd.get("meta") or [])


# ---------------------------------------------------------------- #3169 a tax-exempt position needs the reason
EX = invoice(CDE, [{"title": "Regie", "qty": 1, "rate": 1000}, {"title": "Kursgebühr Schulung", "qty": 1, "rate": 380, "tax": "exempt"}])
r = Fr.post(B + f"{D}/{EX}/finalize")
check(r.status_code == 400 and "tax exemption" in r.json().get("error", ""), "#3169: a 0 % position without a reason is not finalised: " + r.text[:200])
Fr.put(B + O + "/settings", json={"exempt_reason": REASON})
rd = render(EX)
rows = [a for a, b in rd["totals"]["rows"]]
check("MwSt. 19 % auf 1.000,00 €" in rows and any(x.startswith("steuerfrei auf 380,00") for x in rows), f"#3175: tax rows with the taxable amount: {rows}")
check(rd["totals"].get("exempt_note") == REASON and rd.get("exempt_reason") == REASON, f"#3169: the reason in the print model: {rd['totals'].get('exempt_note')!r}")
r = Fr.post(B + f"{D}/{EX}/finalize")
check(r.ok and r.json().get("locked"), "#3169: finalised with the reason " + r.text[:160])
Fr.put(B + O + "/settings", json={"exempt_reason": "Ein anderer Grund"})
check(render(EX)["totals"].get("exempt_note") == REASON, "#3169: a finalised invoice keeps its reason (frozen in the sender snapshot)")
x = Fr.get(B + f"{D}/{EX}/xml")
check(x.ok and b"<ram:CategoryCode>E</ram:CategoryCode>" in x.content and REASON.encode() in x.content and b"<ram:CategoryCode>S</ram:CategoryCode>" in x.content,
      "#3169: the XML: line category E with the reason, S for the taxed line")
pdf = Fr.get(B + f"{D}/{EX}/pdf")
check(pdf.ok and pdf.content[:5] == b"%PDF-", "the PDF of the invoice")

# ---------------------------------------------------------------- #3173 GiroCode: the open amount after a part payment
gc = (render(EX).get("payment") or {}).get("girocode") or ""
check("EUR1570.00" in gc, f"#3173: GiroCode before payment = gross 1570.00: {gc!r}")
r = Fr.post(B + f"{D}/{EX}/payments", json={"date": "2026-10-25", "amount": "500.00", "method": "transfer"})
check(r.status_code == 201, "part payment " + r.text[:160])
gc = (render(EX).get("payment") or {}).get("girocode") or ""
check("EUR1070.00" in gc and "EUR1570.00" not in gc, f"#3173: GiroCode after 500 paid = open 1070.00 (was the gross): {gc!r}")

# ---------------------------------------------------------------- #3175 credit note = "Rechnungskorrektur", #3173 BT-26
r = Fr.post(B + f"{D}/{EX}/credit")
check(r.status_code == 201, "credit note from the invoice " + r.text[:160])
CR = r.json()["id"]
rc = render(CR)
inv_date = Fr.get(B + f"{D}/{EX}").json()["date"]
check(rc["title"] == "Rechnungskorrektur" and "Rechnungskorrektur Nr." in meta(rc), f"#3175: title and number label: {rc['title']} {list(meta(rc))}")
check("zu der oben genannten Rechnung" in (rc.get("intro") or ""), f"#3175: the intro names the invoice above: {(rc.get('intro') or '')[:60]!r}")
check((rc.get("cancels") or {}).get("date") == inv_date, f"#3173: cancels.date = the invoice's date (BT-26): {rc.get('cancels')}")
r = Fr.post(B + f"{D}/{CR}/finalize")
check(r.ok, "credit note finalised " + r.text[:160])
x = Fr.get(B + f"{D}/{CR}/xml")
check(x.ok and ('format="102">' + inv_date.replace("-", "")).encode() in x.content and b"InvoiceReferencedDocument" in x.content, "#3173: BT-26 in the credit note's XML")

# ---------------------------------------------------------------- #3168 reverse charge
RV = invoice(CDE, [{"title": "Animation", "qty": 1, "rate": 2000}], vat_mode="novat", vat_note="reverse")
r = Fr.post(B + f"{D}/{RV}/finalize")
check(r.status_code == 400 and "client's VAT ID" in r.json().get("error", ""), "#3168: reverse charge without the client's VAT id: 400 " + r.text[:200])
RN = invoice(CNL, [{"title": "Animation", "qty": 1, "rate": 2000}], vat_mode="novat", vat_note="reverse")
rn = render(RN)
mt = meta(rn)
check(mt.get("USt-IdNr. Kunde") == "NL123456789B01", f"#3168: the client's VAT id in the head: {mt}")
check(mt.get("Leitweg-ID") == "REF-4711" or mt.get("Käuferreferenz") == "REF-4711", f"#3173: the buyer reference in the head: {mt}")
check((rn["recipient"].get("lines") or [""])[-1] == "NIEDERLANDE", f"#3168: the country line in capitals: {rn['recipient'].get('lines')}")
check("Art. 196" in (rn.get("vat_note_text") or ""), f"#3168: EU client: Art. 196 text: {rn.get('vat_note_text')!r}")
r = Fr.post(B + f"{D}/{RN}/finalize")
check(r.ok, "#3168: reverse charge with both VAT ids finalised " + r.text[:200])
x = Fr.get(B + f"{D}/{RN}/xml")
check(x.ok and b"<ram:CategoryCode>AE</ram:CategoryCode>" in x.content and b"NL123456789B01" in x.content and b"DE999999999" in x.content, "#3168: AE with both VAT ids")
RD = invoice(CDV, [{"title": "Montage", "qty": 1, "rate": 800}], vat_mode="novat", vat_note="reverse")
rv = render(RD)
check("13b" in (rv.get("vat_note_text") or "") and not any(re.fullmatch(r"[A-Z]{2}", ln or "") for ln in rv["recipient"].get("lines") or []),
      f"#3168: domestic client: section 13b, no country line: {rv.get('vat_note_text')!r}")
XR = invoice(CNL, [{"title": "Animation", "qty": 1, "rate": 100}], einvoice_format="xrechnung")
check(meta(render(XR)).get("Leitweg-ID") == "REF-4711" and "Käuferreferenz" not in meta(render(XR)),
      f"#3173: XRechnung: the buyer reference as Leitweg-ID: {meta(render(XR))}")
ZG = invoice(CNL, [{"title": "Animation", "qty": 1, "rate": 100}], einvoice_format="zugferd")
check(meta(render(ZG)).get("Käuferreferenz") == "REF-4711" or Fr.get(B + f"{D}/{ZG}").json().get("einvoice_format") != "zugferd",
      f"#3173: ZUGFeRD: the buyer reference as Käuferreferenz: {meta(render(ZG))}")

# ---------------------------------------------------------------- #3175 dates and money in the document's language
EN = invoice(CNL, [{"title": "Editing", "qty": 1, "rate": 1234.5}], lang="en")
re_ = render(EN)
check(re.fullmatch(r"\d{1,2} [A-Z][a-z]+ \d{4}", re_.get("date_text") or "") is not None and "Client VAT ID" in meta(re_),
      f"#3175: English document: '24 October 2026', English head: {re_.get('date_text')!r} {list(meta(re_))}")
FRD = invoice(CNL, [{"title": "Montage", "qty": 1, "rate": 1234.5}], lang="fr")
rf = render(FRD)
check(rf["totals"].get("net_text") == f"1{NB}234,50 €" and re.fullmatch(r"\d{1,2} \S+ \d{4}", rf.get("date_text") or ""),
      f"#3175: French document: money and date of its language: {rf['totals'].get('net_text')!r} {rf.get('date_text')!r}")

# ---------------------------------------------------------------- 2.296.0 F: review fixes (#3168, #3169, #3173, #3175)
# 2.296.0 F (#3168): a taxed invoice with a stale vat_note "reverse" is a normal invoice (was AE / 0 % tax in the XML and a 400)
ST = invoice(CDE, [{"title": "Regie", "qty": 1, "rate": 1000}], vat_note="reverse")
rs = render(ST)
check(rs.get("vat_note_key") == "" and not rs.get("vat_note_text") and not rs["totals"].get("vat_note"), f"F #3168: stale vat_note ignored when taxed: {rs.get('vat_note_key')!r}")
r = Fr.post(B + f"{D}/{ST}/finalize")
check(r.ok, "F #3168: a taxed invoice with a stale vat_note is finalised " + r.text[:200])
x = Fr.get(B + f"{D}/{ST}/xml")
check(x.ok and b"<ram:CategoryCode>S</ram:CategoryCode>" in x.content and b"<ram:CategoryCode>AE</ram:CategoryCode>" not in x.content,
      "F #3168: its XML is category S, not AE")
# 2.296.0 F (#3168): domestic reverse charge (section 13b) without the client's VAT id is fine when no e-invoice is built
CNX = client(name="Exempel Twee B.V.", street="Voorbeeldstraat 12", zip="1012 AB", city="Amsterdam", country="NL")
check(Fr.put(B + O + "/settings", json={"features_off": ["docs.einvoice"]}).ok, "e-invoice switched off")
r = Fr.post(B + f"{D}/{RV}/finalize")
check(r.ok, "F #3168: domestic reverse charge without the client's VAT id, no e-invoice: finalised " + r.text[:200])
RE2 = invoice(CNX, [{"title": "Animation", "qty": 1, "rate": 500}], vat_mode="novat", vat_note="reverse")
r = Fr.post(B + f"{D}/{RE2}/finalize")
check(r.status_code == 400 and "client's VAT ID" in r.json().get("error", ""), "F #3168: an EU client without a VAT id: still 400 " + r.text[:200])
Fr.put(B + O + "/settings", json={"features_off": []})
# 2.296.0 F (#3168): a client outside the EU keeps the generic reverse charge text (no section 13b, no Art. 196)
CCH = client(name="Beispiel AG", street="Bahnhofstrasse 3", zip="8001", city="Zürich", country="CH", vat_id="CHE-123.456.789")
rch = render(invoice(CCH, [{"title": "Animation", "qty": 1, "rate": 500}], vat_mode="novat", vat_note="reverse"))
check("Art. 196" not in (rch.get("vat_note_text") or "") and rch.get("vat_note_text"),  # the pack's vat_note_reverse (was the EU text)
      f"F #3168: CH client: the generic reverse charge text: {rch.get('vat_note_text')!r}")
# 2.296.0 F (#3169): a 0 EUR tax-exempt position names the reason as well (it has no tax line)
Z0 = invoice(CDE, [{"title": "Regie", "qty": 1, "rate": 1000}, {"title": "Kursgebühr (erlassen)", "qty": 1, "rate": 0, "tax": "exempt"}])
check(render(Z0)["totals"].get("exempt_note") == "Ein anderer Grund", f"F #3169: 0 EUR exempt position: the reason printed: {render(Z0)['totals'].get('exempt_note')!r}")
# 2.296.0 F (#3173): the office default XRechnung labels the buyer reference Leitweg-ID (the document has no own format)
Fr.put(B + O + "/settings", json={"einvoice_format": "xrechnung"})
XD = invoice(CNL, [{"title": "Animation", "qty": 1, "rate": 100}], einvoice_format="")
check(meta(render(XD)).get("Leitweg-ID") == "REF-4711", f"F #3173: office default XRechnung: Leitweg-ID: {meta(render(XD))}")
Fr.put(B + O + "/settings", json={"einvoice_format": "zugferd"})
# 2.296.0 F (#3175): the deduction line of an English final invoice dates the progress invoice in English (was ISO)
Q = Fr.post(B + D, json={"client_id": CNL, "project_title": "Final", "lang": "en"}).json()["id"]
Fr.put(B + f"{D}/{Q}/items", json={"items": [{"kind": "service", "title": "Camera", "qty": 1, "unit": "day", "rate": 1000}]})
Fr.post(B + f"{D}/{Q}/finalize")
Fr.post(B + f"{D}/{Q}/status", json={"status": "sent"})
Fr.post(B + f"{D}/{Q}/status", json={"status": "accepted"})
r = Fr.post(B + f"{D}/{Q}/invoice", json={"inv_type": "progress", "pct": 30})
check(r.status_code == 201, "progress invoice " + r.text[:160])
PG = r.json()["id"]
Fr.patch(B + f"{D}/{PG}", json={"service_from": "2026-10-01", "service_to": "2026-10-20"})
r = Fr.post(B + f"{D}/{PG}/finalize")
check(r.ok, "progress invoice finalised " + r.text[:200])
r = Fr.post(B + f"{D}/{Q}/invoice", json={"inv_type": "final"})
check(r.status_code == 201, "final invoice " + r.text[:160])
ded = [ln.get("title") or "" for ln in render(r.json()["id"]).get("lines") or [] if (ln.get("title") or "").startswith("Less progress invoice no.")]
check(ded and re.search(r" of \d{1,2} [A-Z][a-z]+ \d{4}$", ded[0]) is not None, f"F #3175: deduction dated in English: {ded}")

# 2.357.0 (#3217): an office with a true zero rate (standard 0 %, e.g. UK) finalises without an exemption reason, the XML says Z
r = Fr.put(B + O + "/settings", json={"pack": "XX", "exempt_reason": "", "tax_rates": {"standard": 0, "reduced": 0}})  # own rates: the base pack only
check(r.ok and r.json()["settings"]["pack"] == "XX", "#3217: base pack with a zero standard rate " + r.text[:160])
ZR = invoice(CDE, [{"title": "Regie", "qty": 1, "rate": 1000}])
check(render(ZR)["totals"].get("exempt_note") in (None, ""), f"#3217: no exemption note for a zero rated invoice: {render(ZR)['totals'].get('exempt_note')!r}")
r = Fr.post(B + f"{D}/{ZR}/finalize")
check(r.ok and r.json().get("locked"), "#3217: zero rated invoice finalised without an exemption reason " + r.text[:200])
x = Fr.get(B + f"{D}/{ZR}/xml")
check(x.ok and b"<ram:CategoryCode>Z</ram:CategoryCode>" in x.content and b"<ram:ExemptionReason>" not in x.content,
      "#3217: the XML: category Z, no reason " + re.sub(rb"\s+", b" ", x.content[x.content.find(b"<ram:ApplicableTradeTax>"):][:300]).decode(errors="replace"))
EZ = invoice(CDE, [{"title": "Kurs", "qty": 1, "rate": 300, "tax": "exempt"}])
r = Fr.post(B + f"{D}/{EZ}/finalize")
check(r.status_code == 400 and "tax exemption" in r.json().get("error", ""), "#3217: an exempt position still needs the reason " + r.text[:200])
Fr.put(B + O + "/settings", json={"pack": "DE", "tax_rates": {}})

print(f"p2296_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
