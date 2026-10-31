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
 - 2.449.0 (#3766) the switches "de, else en": the privacy sheet's mail and sample, the neutral summary position of an
   invoice from parts (never "Film production"), the language of a new office without a country pack, the PDF reports and
   file names in the person's language
usage: p2185_c_doclang_test.py <datadir>
freelancer-matrix: office"""
import importlib.util
import io
import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
TODAY = testclock.today().isoformat()
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


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
# 2.357.0 C (#3182): + accept_text (the order sentence above the signature lines of a quotation)
NEW_PDF = {"accept_text", "ov_title", "ov_part", "ov_page", "ov_hint"}  # 2.449.0 (#3766): + the overview of #3622 (this check was red since then)
check(set(pdf.PDF_LABELS) == set(OLD_PDF) | NEW_PDF, "pdf: no label lost")
check(pdf.tr(pdf.PDF_LABELS["title"], lg="fr") == "Devis" and pdf.tr(pdf.PDF_LABELS["vat"], lg="nl") == "Btw", "pdf: fr / nl words")

OLD_CALC = {  # office/calc.py LABELS up to 2.167 (2.357.0 (#3183): German "Summe netto" / "Gesamt brutto")
    "producing_detail": ("{days} {day_word} = {qty} {prod_word} / {quot}, auf halbe Tage gerundet", "{days} {day_word} = {qty} {prod_word} / {quot}, rounded to half days"),
    "raw_optional": ("Optional: Bereitstellung der Rohdaten", "Optional: Delivery of raw data"), "raw_included": ("Bereitstellung der Rohdaten", "Delivery of raw data"),
    "share_detail": ("{amount} / {rate} x {factor} = {days} Tage, auf halbe Tage gerundet", "{amount} / {rate} x {factor} = {days} days, rounded to half days"),
    "handling": ("Handlungskosten", "Handling costs"), "markup": ("Aufschlag", "Markup"),  # 2.296.0 B (#3173): German "Aufschlag" (was "Markup")
    "surcharge_detail": ("{pct} % auf die markierten Positionen", "{pct} % on the marked positions"),
    "surcharge_detail_stacked": ("{pct} % auf die markierten Positionen und die Handlungskosten", "{pct} % on the marked positions and the handling costs"),
    "raw_detail": ("{pct} % der Positionen mit Rohdaten", "{pct} % of the positions with raw data"), "discount": ("Rabatt", "Discount"),
    "discount_detail": ("{pct} % auf die markierten Positionen", "{pct} % on the marked positions"), "net": ("Summe netto", "Net Total"),
    "net_incl_raw": ("Summe netto mit Option Rohdaten", "Net total with option raw data"), "net_excl_raw": ("ohne Rohdaten", "excluding raw data"),
    "gross": ("Gesamt brutto", "Gross Total"), "tax_standard": ("MwSt. {pct} %", "VAT {pct} %"), "tax_reduced": ("MwSt. {pct} %", "VAT {pct} %"),
    "tax_exempt": ("steuerfrei", "tax exempt"), "vat_note": ("Alle Preise zuzüglich 7 % bzw. 19 % MwSt.", "All prices plus 7 % or 19 % VAT."),
    "novat_note": ("Nicht im Inland steuerbar / Reverse-Charge-Verfahren.", "Not taxable domestically / reverse charge."),
    "fx_note": ("Wechselkurs 1 €: {rate} $", "Exchange rate €1: ${rate}"), "unit_day": ("Tage", "days"), "unit_hour": ("Std.", "h"),
    "unit_piece": ("Stk.", "pcs"), "unit_minute": ("Min.", "min"), "unit_flat": ("pauschal", "flat"), "producing": ("Producing", "Producing")}
for k, (de, en) in OLD_CALC.items():
    check(calc.label(None, "de", k) == de and calc.label(None, "en", k) == en, f"calc label {k}: de / en as before ({calc.label(None, 'de', k)!r})")
check(calc.label(None, "fr", "discount") == "Remise" and calc.label(None, "it", "tax_exempt") == "esente IVA", "calc: fr / it words")
check(calc.bwa_vat_note(calc.label(None, "de", "vat_note"), [19], "de") == "Alle Preise zuzüglich 19 % MwSt.", "calc: the German VAT note narrows as before")
check(calc.bwa_vat_note(calc.label(None, "fr", "vat_note"), [19], "fr") == "Tous les prix s'entendent TVA de 19 % en sus." and
      calc.bwa_vat_note(calc.label(None, "fr", "vat_note"), [7, 19], "fr").count(" ou ") == 1, "calc: the French VAT note narrows to the rates of the document")
# 2.296.0 B (#3175): fr groups with a no-break space, nl puts the sign first (was "1.234,50 €" for every comma language)
check(calc.fmt_money(1234.5, "de") == "1.234,50 €" and calc.fmt_money(1234.5, "en") == "€1,234.50" and calc.fmt_money(1234.5, "fr") == "1\u00a0234,50 €"
      and calc.fmt_money(1234.5, "nl") == "€ 1.234,50", "calc: money de / en as before, fr / nl by their language")
check(calc.fmt_qty(4.5, "nl") == "4,5" and calc.fmt_qty(4.5, "en") == "4.5", "calc: quantities")
check(calc.fmt_point("7.5", "fr") == "7,5" and calc.fmt_point("7.5", "nl") == "7,5" and calc.fmt_point("7.5", "en-GB") == "7.5", "#3766: the decimal sign by the language")
check(calc.calc_lang("fr") == "fr" and calc.calc_lang("en-GB") == "en" and calc.calc_lang("xx") == "de" and calc.calc_lang(None) == "de", "calc: the document language")

# 2.296.0 B (#3175): pdf_money = calc.fmt_money ("€1,234.50" en like the model's texts); the pack's format only for German
check(pdf.pdf_money(1234.5, "de", "EUR") == "1.234,50 €" and pdf.pdf_money(1234.5, "en", "EUR") == "€1,234.50", "pdf: money de / en like the model")
check(pdf.pdf_money(1234.5, "fr", "EUR") == "1\u00a0234,50 €" and pdf.pdf_money(1234.5, "es", "EUR") == "1.234,50 €", "pdf: money fr / es with the comma")
check(pdf.pdf_money(1234.5, "de", "EUR", {"decimal": ".", "thousands": ","}) == "1,234.50 €"
      and pdf.pdf_money(1234.5, "fr", "EUR", {"decimal": ".", "thousands": ","}) == "1\u00a0234,50 €", "pdf: a pack's own format wins for German documents")
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
    "Dear Sir or Madam,\n\nPlease find attached {0} {1}.\n\nKind regards\n{2}|document mail": "Sehr geehrte Damen und Herren,\n\nanbei erhalten Sie {0} {1}.\n\nMit freundlichen Grüßen\n{2}",
    "the document|mail": "das Dokument", "the document|mail, quotation": "das Angebot", "the document|mail, invoice": "die Rechnung",
    # 2.431.0 (#3595): credit notes are called Rechnungskorrektur, default scheme RK- (was Gutschrift / GS-)
    "the document|mail, credit note": "die Rechnungskorrektur", "the document|mail, reminder": "die Mahnung", "the document|mail, delivery note": "den Lieferschein",
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
    check(m["totals"].get("net_text") == "2\u00a0469,00 €", f"{tag}: money with the comma (2.296.0 B #3175: fr groups with a no-break space) ({m['totals'].get('net_text')!r})")
    t = pdf_text(s, q["id"])
    check("Devis" in t and "Total HT" in t and "Cordialement" in t, f"{tag}: the quotation PDF in French ({t[-300:]!r})")
    # a language switch of a draft: the standard texts follow (doclang)
    r = s.patch(B + f"{D}/{q['id']}", json={"lang": "de"})
    check(r.ok and render(s, q["id"])["intro"].startswith("Sehr geehrte Damen und Herren,"), f"{tag}: switched to German, the intro follows")
    r = s.patch(B + f"{D}/{q['id']}", json={"lang": "nl"})
    check(r.ok and render(s, q["id"])["intro"].startswith("Geachte heer, mevrouw,") and render(s, q["id"])["title"] == "Offerte",
          f"{tag}: switched to Dutch, intro and title follow ({render(s, q['id'])['intro'][:40]!r})")
    check(s.patch(B + f"{D}/{q['id']}", json={"lang": "xx"}).status_code == 400, f"{tag}: an unknown document language 400")
    # review 2.185.0: an own text with a bar stays whole in a non-de/en document
    r = s.patch(B + f"{D}/{q['id']}", json={"intro": "Tel. 1 | Fax 2"})
    check(r.ok and render(s, q["id"]).get("intro") == "Tel. 1 | Fax 2", f"{tag}: own intro with a bar whole ({render(s, q['id']).get('intro')!r})")
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


def privacy_checks(s, client, tag):
    """#3766: the mail of a French sheet is French (it was German), its sample opens (it was a 500)."""
    t = s.post(B + O + "/doc-templates", json={"kind": "other", "name": "Fiche", "lang": "fr", "sign": 1, "body": "# Fiche\n\nTexte."}).json()["id"]
    r = s.post(B + O + "/privacy-sheets", json={"client_id": client, "kind": "dpa", "template_id": t})
    check(r.status_code == 201, f"{tag}: a French sheet " + r.text[:200])
    m = s.get(B + O + f"/privacy-sheets/{r.json()['sheet']['id']}/mail").json()
    check(m.get("text", "").startswith(LG["fr"]["Hello,"]) and LG["fr"]["Kind regards"] in m["text"], f"{tag}: the sheet's mail in French ({m.get('text', '')[:80]!r})")
    r = s.post(B + O + "/privacy-sheets", json={"client_id": client, "kind": "info"})
    check(r.status_code == 201, f"{tag}: a sheet from the sample in an office in French ({r.status_code})")
    # 2.449.0 (#3768): the sample itself is French, not English text in a French frame
    r = s.post(B + O + "/privacy-sheets", json={"client_id": client, "kind": "dpa"})
    check(r.status_code == 201 and r.json()["sheet"]["title"] == "Contrat de sous-traitance de données", f"{tag}: the sample's text in French " + r.text[:200])


def summary_invoice(s, lang, tag):
    """A quotation with one part in lang -> the positions of its summary invoice."""
    did = s.post(B + D, json={"kind": "offer", "lang": lang, "project_title": f"Parts {tag}",
                              "items": [{"kind": "service", "title": "Concept", "qty": 1, "unit": "day", "rate": 800}]}).json()["id"]
    r = s.post(B + f"{D}/{did}/parts", json={"title": "Module"})
    check(r.status_code == 201, f"{tag}: a part " + r.text[:160])
    s.put(B + f"{D}/{did}/parts/{r.json()['part']['id']}/items", json={"items": [{"kind": "service", "title": "Animation", "qty": 1, "unit": "day", "rate": 500}]})
    r = s.post(B + f"{D}/{did}/invoice", json={"parts_mode": "summary"})
    check(r.status_code == 201, f"{tag}: summary invoice {lang} " + r.text[:200])
    return r.json()["items"] if r.ok else []


def position_checks(s, tag):
    """#3766: the summary position is neutral and in the document's language; the former default stored by the form counts as empty."""
    st = s.get(B + O + "/settings").json()["settings"]
    check(st["parts_summary_title_de"] == "" and st["parts_summary_title_en"] == "", f"{tag}: the default is empty ({st['parts_summary_title_en']!r})")
    for lg, word in (("fr", "Prestations"), ("de", "Leistungen"), ("en", "Services"), ("nl", "Diensten")):
        ti = [x["title"] for x in summary_invoice(s, lg, f"{tag} {lg}")]
        check(ti and set(ti) == {word}, f"{tag}: summary position in {lg} {ti}")
    s.put(B + O + "/settings", json={"parts_summary_title_de": "Filmherstellung", "parts_summary_title_en": "Film production"})
    ti = [x["title"] for x in summary_invoice(s, "fr", f"{tag} old")]
    check(ti and set(ti) == {"Prestations"}, f"{tag}: a stored former default is no title of the office {ti}")
    r = s.put(B + O + "/settings", json={"industry_packs": ["film"], "parts_summary_title_de": "Filmherstellung", "parts_summary_title_en": "Film production"})
    check(r.ok, f"{tag}: the film pack " + r.text[:160])
    ti = [x["title"] for x in summary_invoice(s, "de", f"{tag} film")]
    check(ti and set(ti) == {"Filmherstellung"}, f"{tag}: an office with the film pack keeps it {ti}")
    ti = [x["title"] for x in summary_invoice(s, "fr", f"{tag} film fr")]
    check(ti and set(ti) == {"Prestations"}, f"{tag}: never the English film word on a French invoice {ti}")
    s.put(B + O + "/settings", json={"industry_packs": [], "parts_summary_title_de": "", "parts_summary_title_en": "Motion design"})
    ti = [x["title"] for x in summary_invoice(s, "fr", f"{tag} own")]
    check(ti and set(ti) == {"Motion design"}, f"{tag}: an own title stays {ti}")
    s.put(B + O + "/settings", json={"parts_summary_title_en": ""})


def report(s, path, tag):
    """(text of the PDF, Content-Disposition) of a report."""
    from pypdf import PdfReader
    r = s.get(B + O + path)
    check(r.ok and r.content[:5] == b"%PDF-", f"{tag}: {path} ({r.status_code})")
    return ("\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages) if r.ok else ""), r.headers.get("Content-Disposition", "")


def report_checks(s, uid, tag):
    """#3766: a person working in French gets the reports with French numbers, dates and file names (they were English)."""
    check(s.patch(B + "/api/settings", json={"lang": "fr"}).ok, f"{tag}: French")
    r = s.post(B + O + "/equipment", json={"name": "Licht", "serial_no": "L-1", "purchase_date": "2026-02-01", "purchase_net": "300"})
    check(r.status_code == 201, f"{tag}: equipment " + r.text[:160])
    t, _ = report(s, "/equipment/value.pdf", tag)
    check("février" in t, f"{tag}: equipment value: French date ({t[:200]!r})")
    t, cd = report(s, f"/books/euer.pdf?year={TODAY[:4]}", tag)
    check("0,00" in t and "0.00" not in t, f"{tag}: EUeR: French money ({t[:200]!r})")
    check("compte-de-resultat-" in cd, f"{tag}: EUeR PDF: file name {cd}")
    r = s.get(B + O + f"/books/euer.csv?year={TODAY[:4]}")
    check("compte-de-resultat-" in r.headers.get("Content-Disposition", ""), f"{tag}: EUeR CSV: file name")
    vid = s.post(B + O + "/vehicles", json={"name": "Kombi", "kind": "private", "odo_start": "10000"}).json()["id"]
    r = s.post(B + O + "/drives", json={"vehicle_id": vid, "day": "2026-03-02", "start_place": "Hamburg", "dest": "Lübeck", "purpose": "Dreh", "odo_start": "10000",
                                        "odo_end": "10120.5", "kind": "business"})
    check(r.status_code == 201, f"{tag}: a drive " + r.text[:200])
    t, cd = report(s, "/logbook.pdf?year=2026", tag)
    check("10120,5" in t and "10120.5" not in t, f"{tag}: logbook: the French decimal comma ({t[:300]!r})")
    check("carnet-de-bord-2026.pdf" in cd, f"{tag}: logbook PDF: file name {cd}")
    r = s.get(B + O + "/logbook.csv?year=2026")
    check("carnet-de-bord-2026.csv" in r.headers.get("Content-Disposition", ""), f"{tag}: logbook CSV: file name")
    r = s.post(B + O + "/cashbooks", json={"name": "Caisse", "opening": "500.00", "opening_day": "2026-01-01"})
    check(r.status_code == 201, f"{tag}: a cash book " + r.text[:160])
    t, _ = report(s, f"/cashbook.pdf?book_id={r.json()['id']}&year=2026", tag)
    check("500,00" in t and "€500" not in t, f"{tag}: cash book: French money ({t[:200]!r})")
    r = s.post(B + O + "/trips", json={"date_from": "2025-09-03", "date_to": "2025-09-05", "dest": "Athènes", "overnight": True, "country": "GR",
                                       "people": [{"id": uid}], "purpose": "job"})
    check(r.status_code == 201, f"{tag}: a trip " + r.text[:200])
    j = s.get(B + O + "/trips/vma?year=2025").json()
    lines = str(j.get("people"))
    check("Grèce" in lines, f"{tag}: per diem: the country in French ({lines[:300]!r})")
    t, cd = report(s, "/trips/vma.pdf?year=2025", tag)
    check("septembre 2025" in t, f"{tag}: per diem: French date ({t[:200]!r})")
    check("indemnites-repas-2025" in cd, f"{tag}: per diem: file name {cd}")
    m = s.post(B + O + "/meals", json={}).json()
    r = s.patch(B + O + f"/meals/{m['id']}", json={"date": "2025-05-14", "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
                                                   "occasion": "Negotiation of the follow-up order", "host": {"id": uid}, "guests": [{"name": "Gina Gast"}],
                                                   "amounts": [{"kind": "food", "rate": 7.5, "gross": "107.50"}]})
    check(r.ok, f"{tag}: a meal " + r.text[:200])
    t, _ = report(s, f"/meals/{m['id']}/pdf", tag)
    check("mai 2025" in t and "7,5 %" in t, f"{tag}: meal: French date and rate ({t[:300]!r})")
    r = s.get(B + O + "/subs.csv")
    check(r.ok and ";" in r.text.splitlines()[0], f"{tag}: subscriptions CSV: the semicolon of a comma language")
    names = zipfile.ZipFile(io.BytesIO(s.get(B + "/api/export/markdown.zip").content)).namelist()
    check(LG["fr"]["Basket"] + ".md" in names, f"{tag}: export: the inbox's file in French {names}")
    s.patch(B + "/api/settings", json={"lang": "en"})


def offer_title_checks(s, client, tag):
    """2.453.0 (#3816): a finalised quotation keeps its heading: frozen at finalising, switching the industry pack off (or
    on) never changes it; one finalised before keeps the word of its country pack."""
    def offer(pt):
        did = s.post(B + D, json={"kind": "offer", "client_id": client, "lang": "de", "project_title": pt,
                                  "items": [{"kind": "service", "title": "Kamera", "qty": 1, "unit": "day", "rate": 500}]}).json()["id"]
        r = s.post(B + f"{D}/{did}/finalize")
        check(r.ok, f"{tag}: {pt} finalised " + r.text[:200])
        return did
    check(s.put(B + O + "/settings", json={"industry_packs": ["film"]}).ok, f"{tag}: film pack on")
    film = offer(f"Film {tag}")
    draft = s.post(B + D, json={"kind": "offer", "client_id": client, "lang": "de", "project_title": f"Draft {tag}"}).json()["id"]
    check(render(s, film)["title"] == "Kostenvoranschlag", f"{tag}: the pack's heading on the finalised quotation")
    check(s.put(B + O + "/settings", json={"industry_packs": []}).ok, f"{tag}: film pack off")
    check(render(s, film)["title"] == "Kostenvoranschlag", f"{tag}: pack off: the finalised quotation keeps its heading")
    check(render(s, draft)["title"] == "Angebot", f"{tag}: pack off: a draft follows the settings")
    plain = offer(f"Plain {tag}")
    check(s.put(B + O + "/settings", json={"industry_packs": ["film"]}).ok, f"{tag}: film pack on again")
    check(render(s, plain)["title"] == "Angebot", f"{tag}: pack on later: a finalised quotation keeps its word")
    check(render(s, draft)["title"] == "Kostenvoranschlag", f"{tag}: pack on: a draft follows the settings")
    # finalised before 2.453.0: no heading in the snapshot, the country pack's word even with the pack on
    c = dbxm.connect(os.path.join(sys.argv[1], "tasks.db"))
    t = json.loads(c.execute("SELECT tax_snapshot FROM office_docs WHERE id=?", (film,)).fetchone()[0])
    check(t.pop("offer_title", "") == "Kostenvoranschlag", f"{tag}: the heading lies in the snapshot")
    c.execute("UPDATE office_docs SET tax_snapshot=? WHERE id=?", (json.dumps(t, ensure_ascii=False), film))
    c.commit()
    c.close()
    check(render(s, film)["title"] == "Angebot", f"{tag}: an older finalised quotation keeps the country pack's word")
    s.put(B + O + "/settings", json={"industry_packs": []})


def new_office_checks(s, tag):
    """#3766: a new office without a country pack takes the person's language (it was the base pack's English)."""
    check(s.patch(B + "/api/settings", json={"lang": "fr"}).ok, f"{tag}: French")
    r = s.put(B + O + "/settings", json={"pack": "XX"})
    check(r.ok and r.json()["settings"]["lang"] == "fr", f"{tag}: a new office without a country pack takes the person's language ({r.text[:120]})")
    r = s.put(B + O + "/settings", json={"pack": "DE"})
    check(r.ok and r.json()["settings"]["lang"] == "de", f"{tag}: the German pack brings its language back")
    s.patch(B + "/api/settings", json={"lang": "en"})


CL = office_setup(A, "Beispiel Studio GmbH", "Exemple SARL")
lang_checks(A, CL, "org")
A.put(B + O + "/settings", json={"lang": "fr"})
privacy_checks(A, CL, "org")
A.put(B + O + "/settings", json={"lang": "de"})
position_checks(A, "org")
offer_title_checks(A, CL, "org")
report_checks(A, ALICE, "org")
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
new_office_checks(A, "org")

# ---------------------------------------------------------------- a person without an organisation
# freelancer-matrix: office
FID, F = freelancer(B, A)
CLF = office_setup(F, "Frida Film", "Exemple Studio")
lang_checks(F, CLF, "freelancer")
F.put(B + O + "/settings", json={"lang": "fr"})
privacy_checks(F, CLF, "freelancer")
F.put(B + O + "/settings", json={"lang": "de"})
position_checks(F, "freelancer")
offer_title_checks(F, CLF, "freelancer")
report_checks(F, FID, "freelancer")
_, F2 = freelancer(B, A, name="gaston")
new_office_checks(F2, "freelancer")

print(f"p2185_c_doclang: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
