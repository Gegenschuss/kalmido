#!/usr/bin/env python3
"""2.185.0 C (#2520): the words of the office documents in every app language (nl, fr, es, it besides de / en).
Invented companies, people and figures only, addresses @example.com.
 - no server: the former de / en tables (office/pdf.py PDF_LABELS, calc.py LABELS, ledger.py COMPANY_WORDS / FE_MD_LABELS,
   einvoice.py EXEMPT_TEXT + payment words, terms.py AGB_LINE, girocode.py, invoices.py mail text) are English keys now:
   their German and English texts are the old ones word for word; nl / fr / es / it have every key; numbers / dates of
   the PDF: comma for de / nl / fr / es / it, the point for English, "9 octobre 2026"
 - the server (fresh test container): the document language takes every app language (settings, quotation, invoice),
   an unknown one is refused; a French quotation / invoice prints French words (title, labels, standard texts of the
   country pack, payment note), its PDF too, the e-invoice XML is built with French notes and unchanged codes; German and
   English documents print as before; a language switch of a draft swaps the standard texts into French
 - a person without an organisation (personal office, her own admin): an invoice in French, finalised, PDF + XML
usage: p2185_c_doclang_test.py <datadir>
freelancer-matrix: office"""
import importlib.util
import io
import json
import os
import sys
import xml.etree.ElementTree as ET

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
TODAY = testclock.today().isoformat()
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def load(name):
    spec = importlib.util.spec_from_file_location("p2185c_" + name, os.path.join(SRC, "kalmido", "office", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- no server: the old words stay, the new languages have them
I18N = os.path.join(SRC, "static", "i18n")
LG = {lg: json.load(open(os.path.join(I18N, lg + ".json"), encoding="utf-8")) for lg in ("de", "fr", "nl", "es", "it")}
pdf, calc, ein = load("pdf"), load("calc"), load("einvoice")

OLD_PDF = {  # office/pdf.py PDF_LABELS up to 2.167
    "title": ("Angebot", "Quotation"), "number": ("Angebot Nr.", "Quotation No."), "date": ("Datum", "Date"), "valid_until": ("Gültig bis", "Valid until"),
    "client": ("Kunde", "Client"), "ref": ("Ihre Referenz", "Your reference"), "project": ("Betreff", "Project"), "pos": ("Pos.", "No."),
    "service": ("Leistung", "Service"), "qty": ("Menge", "Qty"), "rate": ("Einzelpreis", "Unit price"), "vat": ("MwSt.", "VAT"), "total": ("Gesamt", "Total"),
    "net": ("Summe netto", "Net total"), "vat_plus": ("zzgl. {0} % MwSt.", "plus {0} % VAT"), "gross": ("Gesamt brutto", "Total incl. VAT"),
    "incl_raw": ("Summe netto mit Option Rohdaten", "Net total with option raw data"), "excl_raw": ("Summe ohne Rohdaten", "Total excluding raw data"),
    "net_suffix": ("netto", "net"), "optional": ("Optional", "Optional"), "rights": ("Rechteübertragung", "Transfer of rights"),
    "rights_see": ("Rechteübertragung siehe Anhang", "Transfer of rights see appendix"),
    "accept_see": ("Auftragserteilung per Unterschrift auf Seite {0}", "Order confirmation by signature on page {0}"),
    "accept": ("Auftragserteilung", "Order confirmation"), "place_date": ("Ort, Datum", "Place, date"),
    "sign": ("Unterschrift, Stempel Auftraggeber", "Signature, stamp of the client"), "page": ("Seite {0} von {1}", "Page {0} of {1}"),
    "contact": ("Kontakt", "Contact"), "register": ("Register", "Registration"), "bank": ("Bank", "Bank"), "discount": ("Rabatt", "Discount"),
    "producing": ("Producing", "Producing")}
for k, (de, en) in OLD_PDF.items():
    check(pdf.tr(pdf.PDF_LABELS[k], lg="de") == de and pdf.tr(pdf.PDF_LABELS[k], lg="en") == en, f"pdf label {k}: de / en as before")
check(len(pdf.PDF_LABELS) == len(OLD_PDF), "pdf: no label lost")
check(pdf.tr(pdf.PDF_LABELS["title"], lg="fr") == "Devis" and pdf.tr(pdf.PDF_LABELS["vat"], lg="nl") == "Btw", "pdf: fr / nl words")

OLD_CALC = {  # office/calc.py LABELS up to 2.167
    "producing_detail": ("{days} {day_word} = {qty} {prod_word} / {quot}, auf halbe Tage gerundet", "{days} {day_word} = {qty} {prod_word} / {quot}, rounded to half days"),
    "raw_optional": ("Optional: Bereitstellung der Rohdaten", "Optional: Delivery of raw data"), "raw_included": ("Bereitstellung der Rohdaten", "Delivery of raw data"),
    "share_detail": ("{amount} / {rate} x {factor} = {days} Tage, auf halbe Tage gerundet", "{amount} / {rate} x {factor} = {days} days, rounded to half days"),
    "handling": ("Handlungskosten", "Handling costs"), "markup": ("Markup", "Markup"),
    "surcharge_detail": ("{pct} % auf die markierten Positionen", "{pct} % on the marked positions"),
    "surcharge_detail_stacked": ("{pct} % auf die markierten Positionen und die Handlungskosten", "{pct} % on the marked positions and the handling costs"),
    "raw_detail": ("{pct} % der Positionen mit Rohdaten", "{pct} % of the positions with raw data"), "discount": ("Rabatt", "Discount"),
    "discount_detail": ("{pct} % auf die markierten Positionen", "{pct} % on the marked positions"), "net": ("Summe Netto", "Net Total"),
    "net_incl_raw": ("Summe netto mit Option Rohdaten", "Net total with option raw data"), "net_excl_raw": ("ohne Rohdaten", "excluding raw data"),
    "gross": ("Gesamt Brutto", "Gross Total"), "tax_standard": ("MwSt. {pct} %", "VAT {pct} %"), "tax_reduced": ("MwSt. {pct} %", "VAT {pct} %"),
    "tax_exempt": ("steuerfrei", "tax exempt"), "vat_note": ("Alle Preise zuzüglich 7 % bzw. 19 % MwSt.", "All prices plus 7 % or 19 % VAT."),
    "novat_note": ("Nicht im Inland steuerbar / Reverse-Charge-Verfahren.", "Not taxable domestically / reverse charge."),
    "fx_note": ("Wechselkurs 1 €: {rate} $", "Exchange rate €1: ${rate}"), "unit_day": ("Tage", "days"), "unit_hour": ("Std.", "h"),
    "unit_piece": ("Stk.", "pcs"), "unit_minute": ("Min.", "min"), "unit_flat": ("pauschal", "flat"), "producing": ("Producing", "Producing")}
for k, (de, en) in OLD_CALC.items():
    check(calc.label(None, "de", k) == de and calc.label(None, "en", k) == en, f"calc label {k}: de / en as before ({calc.label(None, 'de', k)!r})")
check(calc.label(None, "fr", "discount") == "Remise" and calc.label(None, "it", "tax_exempt") == "esente IVA", "calc: fr / it words")
check(calc.bwa_vat_note(calc.label(None, "de", "vat_note"), [19], "de") == "Alle Preise zuzüglich 19 % MwSt.", "calc: the German VAT note narrows as before")
check(calc.bwa_vat_note(calc.label(None, "fr", "vat_note"), [7, 19], "fr").count("ou") == 1, "calc: the French VAT note keeps its 'ou'")
check(calc.fmt_money(1234.5, "de") == "1.234,50 €" and calc.fmt_money(1234.5, "en") == "€1,234.50" and calc.fmt_money(1234.5, "fr") == "1.234,50 €",
      "calc: money de / en as before, fr with the comma")
check(calc.fmt_qty(4.5, "nl") == "4,5" and calc.fmt_qty(4.5, "en") == "4.5", "calc: quantities")
check(calc.calc_lang("fr") == "fr" and calc.calc_lang("en-GB") == "en" and calc.calc_lang("xx") == "de" and calc.calc_lang(None) == "de", "calc: the document language")

check(pdf.pdf_money(1234.5, "de", "EUR") == "1.234,50 €" and pdf.pdf_money(1234.5, "en", "EUR") == "1,234.50 €", "pdf: money de / en as before")
check(pdf.pdf_money(1234.5, "fr", "EUR") == "1.234,50 €" and pdf.pdf_money(1234.5, "es", "EUR") == "1.234,50 €", "pdf: money fr / es with the comma")
check(pdf.pdf_money(1234.5, "fr", "EUR", {"decimal": ".", "thousands": ","}) == "1,234.50 €", "pdf: a pack's own format still wins")
check(pdf.pdf_num(4.5, "it") == "4,5" and pdf.pdf_num(4.5, "en") == "4.5", "pdf: quantities")
check(pdf.pdf_date("2026-10-09", "de") == "09.10.2026" and pdf.pdf_date("2026-10-09", "en") == "9 October 2026", "pdf: dates de / en as before")
check(pdf.pdf_date("2026-10-09", "fr") == "9 octobre 2026" and pdf.pdf_date("2026-10-09", "nl") == "9 oktober 2026", "pdf: dates fr / nl")
check(pdf.pdf_lang("fr") == "fr" and pdf.pdf_lang("EN") == "en" and pdf.pdf_lang("") == "de" and pdf.pdf_lang("zz") == "de", "pdf: the model's language")

OLD_EX = {"reverse": ("Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge).", "Reverse charge: VAT liability of the recipient."),
          "abroad": ("Nicht im Inland steuerbar (Ausfuhr / Leistung außerhalb der EU).", "Not taxable domestically (export / service outside the EU)."),
          "small": ("Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.", "No VAT charged under section 19 of the German VAT Act (small business).")}
for k, (de, en) in OLD_EX.items():
    check(ein.tr(ein.EXEMPT_TEXT[k], lg="de") == de and ein.tr(ein.EXEMPT_TEXT[k], lg="en") == en, f"e-invoice exemption {k}: de / en as before")
for k, (de, en) in {"project": ("Projekt: X", "Project: X"), "transfer": ("Überweisung", "Credit transfer"),
                    "refund": ("Der Betrag wird erstattet oder verrechnet.", "The amount will be refunded or offset."),
                    "now": ("Zahlbar sofort ohne Abzug.", "Payable on receipt.")}.items():
    a = ("X",) if k == "project" else ()
    check(ein.tr(ein.EIN_WORDS[k], *a, lg="de") == de and ein.tr(ein.EIN_WORDS[k], *a, lg="en") == en, f"e-invoice word {k}: de / en as before")

OLD_KEYS = {  # the other former tables (ledger, terms, girocode, invoices mail): German as before, English = the key
    "Phone|company": "Tel.", "Email|company": "E-Mail", "Tax number|company": "Steuernummer", "VAT ID|company": "USt-IdNr.",
    "Register court|company": "Registergericht", "Managing directors|company": "Geschäftsführung", "Shareholders|company": "Gesellschafter",
    "Owner|company, male": "Inhaber", "Owner|company, female": "Inhaberin", "Executive board|company": "Vorstand", "Partners|company": "Partner",
    "Partners|company, GbR": "Gesellschafter", "Our terms and conditions (as of {0}) apply, see attachment.|terms": "Es gelten unsere AGB (Stand {0}), siehe Anhang.",
    "Scan with banking app|girocode": "Mit Banking-App scannen",
    "Dear Sir or Madam,\n\nplease find attached {0} {1}.\n\nKind regards\n{2}|document mail": "Sehr geehrte Damen und Herren,\n\nanbei erhalten Sie {0} {1}.\n\nMit freundlichen Grüßen\n{2}",
    "the document|mail": "das Dokument", "the document|mail, quotation": "das Angebot", "the document|mail, invoice": "die Rechnung",
    "the document|mail, credit note": "die Gutschrift", "the document|mail, reminder": "die Mahnung", "the document|mail, delivery note": "den Lieferschein",
    "Re quotation No.|pack": "zu Angebot Nr."}
for k, de in OLD_KEYS.items():
    check(LG["de"].get(k) == de, f"de.json {k!r} = the old German ({LG['de'].get(k)!r})")
NEW = [k for k in LG["de"] if k.endswith(("|pdf", "|calc", "|company", "|company, male", "|company, female", "|company, GbR", "|einvoice", "|terms",
                                          "|girocode", "|pack")) or k.startswith("the document|mail") or k.endswith("|document mail")]
check(len(NEW) >= 170, f"the new keys are there ({len(NEW)})")
for lg in ("fr", "nl", "es", "it"):
    check(all(isinstance(LG[lg].get(k), str) and LG[lg][k] for k in NEW), f"{lg}.json has every new document word")

# ---------------------------------------------------------------- the server
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
COMPANY = {"name": "Beispiel Studio GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "email": "studio@example.com",
           "phone": "+49 30 000000", "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def office_setup(s, name, client):
    s.get(B + O + "/settings")
    r = s.put(B + O + "/settings", json={"company_fields": {**COMPANY, "name": name}})
    check(r.ok, f"{name}: office settings " + r.text[:160])
    return s.post(B + "/api/clients", json={"name": client, "street": "Rue Exemple 3", "zip": "75001", "city": "Paris", "country": "FR",
                                            "email": "compta@example.com"}).json()["id"]


def render(s, did):
    r = s.get(B + f"{D}/{did}/render")
    assert r.ok, r.text
    return r.json()


def pdf_text(s, did):
    from pypdf import PdfReader
    r = s.get(B + f"{D}/{did}/pdf")
    check(r.ok and r.content[:5] == b"%PDF-", f"PDF of {did} ({r.status_code})")
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages) if r.ok else ""


def invoice(s, client, lang, tag, novat=False):
    """A finalised invoice in lang -> (id, print model)."""
    r = s.post(B + D, json={"kind": "invoice", "client_id": client, "project_title": f"Film {tag}", "lang": lang})
    check(r.status_code in (200, 201), f"{tag}: invoice draft in {lang} " + r.text[:160])
    did = r.json()["id"]
    s.put(B + f"{D}/{did}/items", json={"items": [{"kind": "service", "title": "Kamera", "qty": 1.5, "unit": "day", "rate": 1000}]})
    patch = {"service_from": TODAY, "service_to": TODAY, "payment_days": 14}
    if novat:
        patch.update(vat_mode="novat", vat_note="small")
    r = s.patch(B + f"{D}/{did}", json=patch)
    check(r.ok, f"{tag}: invoice head " + r.text[:160])
    r = s.post(B + f"{D}/{did}/finalize")
    check(r.ok, f"{tag}: invoice finalised " + r.text[:200])
    return did, render(s, did)


def xml_of(s, did, tag):
    r = s.get(B + f"{D}/{did}/xml")
    check(r.ok, f"{tag}: e-invoice XML ({r.status_code})")
    try:
        return ET.fromstring(r.content) if r.ok else None
    except ET.ParseError as e:
        check(False, f"{tag}: the XML parses ({e})")
        return None


def texts(root, tag):
    return [el.text or "" for el in root.iter() if el.tag.endswith("}" + tag)] if root is not None else []


def lang_checks(s, client, tag):
    # settings: every app language is a document language; an unknown one stays 400
    check(s.put(B + O + "/settings", json={"lang": "xx"}).status_code == 400, f"{tag}: settings lang xx 400")
    r = s.put(B + O + "/settings", json={"lang": "fr"})
    check(r.ok and s.get(B + O + "/settings").json()["settings"]["lang"] == "fr", f"{tag}: settings lang fr " + r.text[:160])
    # a quotation in the office's language (fr): French words, standard texts of the pack in French
    q = s.post(B + D, json={"client_id": client, "project_title": f"Image {tag}"}).json()
    check(q.get("lang") == "fr", f"{tag}: a new quotation takes the office language fr ({q.get('lang')!r})")
    s.put(B + f"{D}/{q['id']}/items", json={"items": [{"kind": "service", "title": "Kamera", "qty": 2, "unit": "day", "rate": 1234.5}]})
    m = render(s, q["id"])
    meta = dict((a, b) for a, b in m.get("meta") or [])
    check(m["title"] == "Devis", f"{tag}: quotation title {m['title']!r}")
    check("Date" in meta and any(k.startswith("Devis n") for k in meta), f"{tag}: quotation head in French {list(meta)}")
    check((m.get("intro") or "").startswith("Madame, Monsieur,"), f"{tag}: the standard intro in French ({(m.get('intro') or '')[:60]!r})")
    check(m.get("signature") == "Cordialement", f"{tag}: the closing word ({m.get('signature')!r})")
    rows = [a for a, b in (m.get("totals") or {}).get("rows") or []]
    check("Total HT" in rows, f"{tag}: the totals' words {rows}")
    check(m["totals"].get("net_text") == "2.469,00 €", f"{tag}: money with the comma ({m['totals'].get('net_text')!r})")
    t = pdf_text(s, q["id"])
    check("Devis" in t and "Qté" in t and "Cordialement" in t, f"{tag}: the quotation PDF in French ({t[:200]!r})")
    # a language switch of a draft: the standard texts follow (doclang)
    r = s.patch(B + f"{D}/{q['id']}", json={"lang": "de"})
    check(r.ok and render(s, q["id"])["intro"].startswith("Sehr geehrte Damen und Herren,"), f"{tag}: switched to German, the intro follows")
    r = s.patch(B + f"{D}/{q['id']}", json={"lang": "nl"})
    check(r.ok and render(s, q["id"])["intro"].startswith("Geachte heer, mevrouw,") and render(s, q["id"])["title"] == "Offerte",
          f"{tag}: switched to Dutch, intro and title follow ({render(s, q['id'])['intro'][:40]!r})")
    check(s.patch(B + f"{D}/{q['id']}", json={"lang": "xx"}).status_code == 400, f"{tag}: an unknown document language 400")
    # a French invoice: words, payment note, PDF, XML with French notes and unchanged codes
    inv, m = invoice(s, client, "fr", tag, novat=True)
    check(m["title"] == "Facture", f"{tag}: invoice title {m['title']!r}")
    pt = (m.get("payment") or {}).get("text") or ""
    check(pt.startswith("Payable avant le "), f"{tag}: the payment note in French ({pt!r})")
    check(m.get("vat_note_text", "").startswith("TVA non applicable"), f"{tag}: the small business note in French ({m.get('vat_note_text')!r})")
    t = pdf_text(s, inv)
    check("Facture" in t and "Payable avant le" in t, f"{tag}: the invoice PDF in French ({t[:200]!r})")
    x = xml_of(s, inv, tag)
    notes = texts(x, "Content")
    check(any(n == f"Projet : Film {tag}" for n in notes), f"{tag}: the XML note 'Projet : …' {notes}")
    check(any("TVA non applicable" in n for n in texts(x, "ExemptionReason")), f"{tag}: the exemption reason in French {texts(x, 'ExemptionReason')}")
    check(texts(x, "TypeCode")[:1] == ["380"] and "E" in texts(x, "CategoryCode") and "EUR" in texts(x, "InvoiceCurrencyCode"),
          f"{tag}: the codes stay (380, E, EUR) {texts(x, 'TypeCode')[:2]} {texts(x, 'CategoryCode')[:2]}")
    # German and English invoices print as before
    for lg, title, note, proj in (("de", "Rechnung", "Zahlbar bis ", "Projekt: "), ("en", "Invoice", "Payable by ", "Project: ")):
        did, m = invoice(s, client, lg, f"{tag} {lg}")
        check(m["title"] == title and ((m.get("payment") or {}).get("text") or "").startswith(note), f"{tag}: the {lg} invoice as before ({m['title']!r})")
        x = xml_of(s, did, f"{tag} {lg}")
        check(any(n == f"{proj}Film {tag} {lg}" for n in texts(x, "Content")), f"{tag}: the {lg} XML note as before {texts(x, 'Content')}")
    s.put(B + O + "/settings", json={"lang": "de"})


CL = office_setup(A, "Beispiel Studio GmbH", "Exemple SARL")
lang_checks(A, CL, "org")

# ---------------------------------------------------------------- a person without an organisation
# freelancer-matrix: office
FID, F = freelancer(B, A)
CLF = office_setup(F, "Frida Film", "Exemple Studio")
lang_checks(F, CLF, "freelancer")

print(f"p2185_c_doclang: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
