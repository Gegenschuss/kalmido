#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.357.0 D (#3183, #3219, #3220): the wording of the office PDFs in de / en / fr / es, the samples of a small business and
the closing up of empty template variables only at the gap. Own container (start.sh). Invented data only.
freelancer-matrix: office
 - #3183 the words of the built-in packs: "Summe netto" / "Gesamt brutto" / "Einzelpreis" (de), sentence case and the
   column "Description" (en), the credit note of the base pack says "above"; every new pack word translated in all languages
 - #3183 an invoice for one day prints "Leistungsdatum", for a period "Leistungszeitraum"; the closing says "Allgemeinen"
 - #3183 fr / es: the sentence after the salutation starts with a capital; es dates "9 de octubre de 2026"
 - #3183 the entertainment receipt carries the logo and a printed date in its title; a one-page letter has no "Seite 1 von 1"
   (a long one counts its pages), its producer is "Kalmido v<version>"; the online acceptance box in French
 - #3219 a small business (section 19) gets the samples with {{offer.gross}} instead of "zzgl. USt"; a template taken
   before stays as it was
 - #3220 an empty variable closes up only its own gap: an own ", (" or double space elsewhere in the line stays
 - the same for a person without organisation (personal office, tests/freelancer_fixture.py)
usage: p2357_d_wording_test.py <datadir>      (P2357D_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import base64
import io
import json
import os
import re
import sys
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
import pdfcheck  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, done, fresh, setup  # noqa: E402
from pypdf import PdfReader  # noqa: E402

O = "/api/office"
D = O + "/docs"
GMBH = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
        "email": "hallo@studio-nordlicht.example", "phone": "+494012345678", "register_court": "Amtsgericht Hamburg", "register_no": "HRB 123456",
        "managing_directors": "Jana Muster", "bank_name": "Hamburger Beispielbank", "iban": "DE89370400440532013000", "bic": "COBADEFFXXX",
        "tax_number": "12/345/67890", "vat_id": "DE123456789"}


def i18n(lang):
    with open(os.path.join(ROOT, "static", "i18n", lang + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def pack(code):
    with open(os.path.join(ROOT, "kalmido", "office", "packs", code + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- 1. the words of the packs and the translation files
DE, XX = pack("de"), pack("xx")
for p in (DE, XX):
    lde, len_ = p["labels"]["de"], p["labels"]["en"]
    check((lde["net_total"], lde["gross_total"], lde["unit_price"], lde.get("service_date")) == ("Summe netto", "Gesamt brutto", "Einzelpreis", "Leistungsdatum"),
          f"#3183 {p['code']}: German totals / unit price / service date {lde['net_total']!r} {lde['gross_total']!r} {lde['unit_price']!r}")
    check((len_["title"], len_["unit_price"], len_["net_total"], len_["gross_total"], len_["rights_time"], len_["rights_territory"], len_["rights_media"])
          == ("Description", "Unit price", "Net total", "Gross total", "Duration of licence", "Territorial rights", "Rights by medium"),
          f"#3183 {p['code']}: English labels in sentence case, 'Description' for the service column")
    check("Allgemeinen Geschäftsbedingungen" in p["texts"]["invoice_closing"]["de"], f"#3183 {p['code']}: 'Allgemeinen Geschäftsbedingungen'")
    check("oben genannten" in p["texts"]["credit_intro"]["de"] and "referenced above" in p["texts"]["credit_intro"]["en"],
          f"#3183 {p['code']}: the credit note refers to the invoice above (its number stands in the head)")
check(XX["texts"]["rights_media"][1]["de"] == "intern, Web, unbezahlte Medien", "#3183 xx: the German rights text is German")
NEW = ("Description|pack", "Unit price|pack", "Net total|pack", "Gross total|pack", "Duration of licence|pack", "Territorial rights|pack",
       "Rights by medium|pack", "Service date|pack", "Service date|document", "Regarding the invoice referenced above we issue the following credit note:|pack")
for lg in ("de", "fr", "es", "it", "nl"):
    t = i18n(lg)
    check(all(isinstance(t.get(k), str) and t[k] for k in NEW), f"#3183 {lg}: every new pack word translated {[k for k in NEW if not t.get(k)]}")
FR, ES = i18n("fr"), i18n("es")
INTROS = [k for k in FR if k.endswith("|pack") and k.lower().startswith(("regarding", "thank you for your enquiry", "the following goods", "it may have", "despite our"))]  # 2.390.0 A (#3349): the keys are capitalised now
check(len(INTROS) >= 8 and all(FR[k][:1].isupper() and ES[k][:1].isupper() for k in INTROS),
      f"#3183 fr / es: the sentence after the salutation starts with a capital {[k[:30] for k in INTROS if not (FR[k][:1].isupper() and ES[k][:1].isupper())]}")
check(FR.get("Unit price|pack") == "Prix unitaire" and FR.get("Net total|pack") == "Total HT" and FR.get("Gross total|pack") == "Total TTC", "#3183 fr: Prix unitaire, Total HT / TTC")

# ---------------------------------------------------------------- the server
KEY = base64.b64encode(os.urandom(32)).decode()
fresh({"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2357D")
A = setup("alice", "Alice Admin", lang="en")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs,files", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office


def pdf_hex(data):
    out = b""
    for m in re.finditer(rb"stream\r?\n(.*?)\nendstream", data, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out.decode("latin-1")


def in_pdf(data, text):
    return text.encode("cp1252").hex() in pdf_hex(data)


def ptext(data):
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)


def sq(t):
    return re.sub(r"\s+", "", t)


def picture():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (300, 100), (47, 93, 138)).save(out, "PNG")
    return out.getvalue()


def render(s, did):
    r = s.get(B + f"{D}/{did}/render")
    check(r.ok, f"render {r.status_code} {r.text[:200]}")
    return r.json() if r.ok else {}


def meta_of(m):
    return dict((a, b) for a, b in m.get("meta") or [])


def run(s, who, me):
    r = s.put(B + O + "/settings", json={"lang": "de", "small_business": False, "company_fields": GMBH})
    check(r.ok, f"{who}: office settings {r.status_code} {r.text[:200]}")
    cl = s.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Kundenweg 5", "zip": "20000", "city": "Hamburg", "country": "DE"}).json()["id"]

    # ---- #3183 German quotation / invoice
    q = s.post(B + D, json={"client_id": cl, "project_title": "Imagefilm", "items": [{"title": "Schnitt", "qty": 2, "rate": 500}]}).json()["id"]
    m = render(s, q)
    rows = [a for a, b in (m.get("totals") or {}).get("rows") or []]
    check("Summe netto" in rows and "Summe Netto" not in rows, f"#3183 {who}: 'Summe netto' {rows}")
    pq = s.get(B + f"{D}/{q}/pdf")
    check(pq.ok and "EINZELPREIS" in sq(ptext(pq.content)), f"#3183 {who}: the column 'Einzelpreis' ({pq.status_code})")
    clean = pdfcheck.problems(pq.content)
    check(not clean, f"#3183 {who}: the quotation layout clean {clean[:3]}")
    inv = s.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": "2026-10-09", "service_to": "2026-10-09",
                              "items": [{"title": "Beratung", "qty": 2, "rate": 100}]}).json()["id"]
    m = render(s, inv)
    meta = meta_of(m)
    check(meta.get("Leistungsdatum") == "09.10.2026" and "Leistungszeitraum" not in meta, f"#3183 {who}: one day = 'Leistungsdatum' {meta}")
    check("Allgemeinen Geschäftsbedingungen" in (m.get("closing") or ""), f"#3183 {who}: 'Allgemeinen' in the closing {(m.get('closing') or '')[-80:]!r}")
    s.patch(B + f"{D}/{inv}", json={"service_from": "2026-10-09", "service_to": "2026-10-12"})
    meta = meta_of(render(s, inv))
    check(meta.get("Leistungszeitraum") == "09.10.2026 – 12.10.2026" and "Leistungsdatum" not in meta, f"#3183 {who}: a period = 'Leistungszeitraum' {meta}")
    s.patch(B + f"{D}/{inv}", json={"service_from": None, "service_to": "2026-10-12"})
    meta = meta_of(render(s, inv))
    check(meta.get("Leistungsdatum") == "12.10.2026", f"#3183 {who}: only an end date = 'Leistungsdatum' {meta}")

    # ---- #3183 English / French / Spanish quotations
    qe = s.post(B + D, json={"client_id": cl, "project_title": "Film", "lang": "en", "items": [{"title": "Edit", "qty": 2, "rate": 500}]}).json()["id"]
    m = render(s, qe)
    rows = [a for a, b in (m.get("totals") or {}).get("rows") or []]
    check("Net total" in rows, f"#3183 {who}: en 'Net total' {rows}")
    t = ptext(s.get(B + f"{D}/{qe}/pdf").content)
    check("DESCRIPTION" in sq(t) and "UNITPRICE" in sq(t) and "TITLE" not in sq(t), f"#3183 {who}: en column heads 'Description', 'Unit price'")
    for lg, word in (("fr", "Nous vous remercions"), ("es", "Le agradecemos")):
        ql = s.post(B + D, json={"client_id": cl, "project_title": "Film", "lang": lg, "items": [{"title": "Edit", "qty": 2, "rate": 500}]}).json()["id"]
        m = render(s, ql)
        intro = m.get("intro") or ""
        check("\n" + word in intro, f"#3183 {who} {lg}: the sentence after the salutation starts with a capital {intro[:90]!r}")
        if lg == "es":
            dates = [v for v in meta_of(m).values() if re.fullmatch(r"\d{1,2} de [a-z]+ de \d{4}", str(v))]
            check(dates, f"#3183 {who} es: the date '9 de octubre de 2026' {meta_of(m)}")
        if lg == "fr":
            pf = s.get(B + f"{D}/{ql}/pdf")
            check(pf.ok and "PRIXUNITAIRE" in sq(ptext(pf.content)), f"#3183 {who} fr: 'Prix unitaire'")

    # ---- #3183 the online acceptance box in the document's language (was German for every language but English)
    qa = s.post(B + D, json={"client_id": cl, "project_title": "Annahme", "lang": "fr", "items": [{"title": "Edit", "qty": 1, "rate": 900}]}).json()["id"]
    check(s.post(B + f"{D}/{qa}/status", json={"status": "sent"}).ok, f"{who}: quotation sent")
    r = s.post(B + f"{D}/{qa}/signoff", json={})
    check(r.ok, f"{who}: customer link {r.status_code} {r.text[:200]}")
    tok = (r.json().get("url") or "").split("/s/q/")[-1] if r.ok else ""
    pg = requests.get(B + "/s/q/" + tok, allow_redirects=False)
    fk = re.search(r'name="f" value="([0-9a-f]+)"', pg.text)
    r = requests.post(B + "/s/q/" + tok, data={"f": fk.group(1) if fk else "", "name": "Camille Exemple", "do": "accept", "ok": "1"},
                      allow_redirects=False, headers={"User-Agent": "TestBrowser/1.0"})
    check(r.status_code in (200, 302, 303), f"{who}: accepted online {r.status_code}")
    pa = s.get(B + f"{D}/{qa}/pdf")
    check(pa.ok and in_pdf(pa.content, FR["Accepted online by"]) and not in_pdf(pa.content, "Online angenommen")
          and in_pdf(pa.content, "Camille Exemple"), f"#3183 {who}: the acceptance box in French ({pa.status_code})")

    # ---- #3219 the samples of a small business
    before = s.post(B + O + "/doc-templates", json={"starter": "confirmation", "lang": "de"}).json()
    check("{{offer.net}} zzgl. USt" in before.get("body", ""), f"#3219 {who}: with VAT the sample says net plus VAT")
    check(s.put(B + O + "/settings", json={"small_business": True}).ok, f"{who}: small business on")
    for st, lg in (("confirmation", "de"), ("contract", "de"), ("confirmation", "en"), ("contract", "en")):
        tb = s.post(B + O + "/doc-templates", json={"starter": st, "lang": lg}).json().get("body", "")
        check("{{offer.gross}}" in tb and "zzgl. USt" not in tb and "plus VAT" not in tb and "{{offer.net}}" not in tb,
              f"#3219 {who}: {st} {lg}: the total instead of net plus VAT")
    sts = s.get(B + O + "/doc-templates/starters?lang=de").json().get("starters") or []
    check(sts and all("zzgl. USt" not in x["body"] for x in sts), f"#3219 {who}: the picker shows the same text")
    old = next((x for x in s.get(B + O + "/doc-templates").json().get("templates") or [] if x["id"] == before.get("id")), {})
    check("{{offer.net}} zzgl. USt" in old.get("body", ""), f"#3219 {who}: a template taken before stays as it was")
    s.put(B + O + "/settings", json={"small_business": False})
    nda = s.post(B + O + "/doc-templates", json={"starter": "nda", "lang": "en"}).json().get("body", "")
    check("Confidential information means" in nda and "Confidential is all" not in nda, f"#3183 {who}: the English NDA without the Germanism")

    # ---- #3220 closing up only at the gap (a letter from a template leaves an empty variable out)
    body = ("Firma, ( Absicht )  doppelt, {{offer.number}} hier.\nName, {{offer.date}} (Hinweis)\nZu {{offer.number}}, (bleibt) und ,, so.\n"
            "Datum ({{offer.date}}) fehlt\n{{offer.number}}, Rest")
    tl = s.post(B + O + "/doc-templates", json={"kind": "letter", "name": "Brief D", "lang": "de", "body": body}).json()
    r = s.post(B + O + "/letters", json={"template_id": tl.get("id"), "client_id": cl})
    got = (r.json().get("body") or "").split("\n") if r.status_code == 201 else []
    check(got == ["Firma, ( Absicht )  doppelt, hier.", "Name (Hinweis)", "Zu, (bleibt) und ,, so.", "Datum fehlt", "Rest"],
          f"#3220 {who}: only the gap closes up {got}")
    lid = r.json().get("id") if r.status_code == 201 else None

    # ---- #3183 letters: no "Seite 1 von 1", producer as the other PDFs
    if lid:
        pl = s.get(B + O + f"/letters/{lid}/pdf")
        check(pl.ok and len(PdfReader(io.BytesIO(pl.content)).pages) == 1 and "Seite 1 von 1" not in " ".join(sum(pdfcheck.footer_lines(pl.content), [])),
              f"#3183 {who}: a one-page letter without 'Seite 1 von 1'")
        prod = str(PdfReader(io.BytesIO(pl.content)).metadata.get("/Producer") or "")
        check(re.fullmatch(r"Kalmido v\d+\.\d+\.\d+\S*", prod) is not None, f"#3183 {who}: letter producer {prod!r}")
    r = s.post(B + O + "/letters", json={"rcpt_name": "Amt für Beispiele", "rcpt_address": "Musterweg 1\n12345 Musterstadt", "subject": "Lang",
                                         "body": "\n\n".join(("Dies ist ein Absatz mit etwas Text. " * 12) for _ in range(14))})
    pl = s.get(B + O + f"/letters/{r.json().get('id')}/pdf") if r.status_code == 201 else None
    n = len(PdfReader(io.BytesIO(pl.content)).pages) if pl is not None and pl.ok else 0
    feet = pdfcheck.footer_lines(pl.content) if n else []
    check(n >= 2 and all(f"Seite {i} von {n}" in " ".join(f) for i, f in enumerate(feet, 1)), f"#3183 {who}: a long letter counts its pages ({n})")

    # ---- #3183 the entertainment receipt: logo, printed date in the title
    r = s.post(B + O + "/logo", files={"file": ("logo.png", picture(), "image/png")})
    check(r.ok, f"{who}: logo {r.status_code} {r.text[:120]}")
    r = s.post(B + O + "/meals", json={})
    mid = r.json().get("id") if r.status_code == 201 else None
    r = s.patch(B + O + f"/meals/{mid}", json={"date": "2026-10-09", "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
                                              "occasion": "Planning of the spring campaign", "host": {"id": me},
                                              "guests": [{"name": "Gina Gast", "extra": "Example GmbH"}], "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}],
                                              "tip": "0"})
    check(r.ok, f"{who}: meal saved {r.text[:200]}")
    d = s.get(B + O + f"/meals/{mid}/pdf").content
    rd = PdfReader(io.BytesIO(d))
    title = str(rd.metadata.get("/Title") or "")
    check("2026-10-09" not in title and "9 October 2026" in title, f"#3183 {who}: the receipt's title with the printed date {title!r}")
    check("/Logo Do" in pdf_hex(d), f"#3183 {who}: the receipt carries the logo")
    lay = pdfcheck.layout(d)
    first = min((t["y"] for t in lay[0]["texts"]), default=0)
    check(first > 65, f"#3183 {who}: the receipt begins below the logo ({first:.1f})")
    pr = pdfcheck.problems(d)
    check(not pr, f"#3183 {who}: the receipt layout clean {pr[:3]}")
    check(GMBH["name"] in " ".join(pdfcheck.footer_lines(d)[0]), f"#3183 {who}: the receipt footer with the company")


run(A, "org", ALICE)
run(Fr, "freelancer", Fr.get(B + "/api/state").json()["me"]["id"])

sys.exit(done("p2357_d_wording"))
