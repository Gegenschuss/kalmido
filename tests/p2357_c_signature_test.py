#!/usr/bin/env python3
# kalmido-suite:
"""2.357.0 C (#3158, #3182): the own signature in letters, documents from templates and quotations; the signature lines and
the rights appendix of the office PDFs. Own container (start.sh). Invented companies, people and figures only; the signature
picture is made here.
freelancer-matrix: office
 - #3158 letters: the draft PDF never carries the signature picture (its room stays free), the sent letter has it above the
   name and on the page of the greeting; a draft of Alice sent by Bob carries no signature at all (never someone else's)
 - #3158 documents from templates: sign_image stores the asking person only (sign_mine), the draft PDF has no picture, the
   finished one has it above the line of the own side (with signature lines) or above the name (without); finished by
   another admin -> no picture and sign_uid emptied; the copy of a document keeps it only for its signer
 - #3158 quotations: office setting sign_offers (default off): off -> no picture, on -> the finished quotation carries the
   picture of the person who finalised it, a draft never
 - #3182 the signature lines of a template document stay on one page with the last paragraph and above the footer, whatever
   the length of the text before them (was: 62 pt reserved for 74); a long title wraps
 - #3182 quotation: the order sentence above the lines; a quotation with one position and rights fits on ONE page (the rights
   appendix only gets its own page when it does not fit); many rights rows still get the appendix page
 - the same for a person without organisation (personal office, tests/freelancer_fixture.py)
usage: p2357_c_signature_test.py <datadir>      (P2357C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import importlib.util
import os
import re
import struct
import subprocess
import sys
import time
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
sys.path.insert(0, N)
from kt import FAILS, OKS, check, sess  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402
import pdfcheck  # noqa: E402
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
L = O + "/letters"
TP = O + "/doc-templates"
GD = O + "/gen-docs"
D = O + "/docs"
SIG_RE = re.compile(rb"q ([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm /Sig Do Q")


def png_sig(w=180, h=60):
    """An RGBA PNG: a dark wavy stroke on a transparent background (made here, no real signature)."""
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            yy = h / 2 + 14 * ((x % 40) - 20) / 20 * (1 if (x // 40) % 2 else -1)
            row += bytes((20, 30, 60, 255)) if abs(y - yy) < 2.5 else bytes((255, 255, 255, 0))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


SIG_URI = "data:image/png;base64," + base64.b64encode(png_sig()).decode()


def sigs(data):
    """Per page the signature pictures: (x, top, w, h) with top measured from the top of the page."""
    from pypdf import PdfReader
    import io
    out = []
    for page in PdfReader(io.BytesIO(data)).pages:
        raw = page.get_contents().get_data() if page.get_contents() is not None else b""
        ph = float(page.mediabox.height)
        out.append([(float(x), ph - float(y) - float(hh), float(w), float(hh)) for w, hh, x, y in SIG_RE.findall(raw)])
    return out


def sig_raw(data):
    """2.357.0 (#3158, review M1): the bytes of every signature picture (XObject /Sig) of the PDF, page by page."""
    from pypdf import PdfReader
    import io
    out = []
    for page in PdfReader(io.BytesIO(data)).pages:
        xo = (page.get("/Resources") or {}).get("/XObject") or {}
        out.extend(xo[k].get_object().get_data() for k in xo if k == "/Sig")
    return out


def find(lay, s, exact=True):
    """[(page index, text)] of the texts equal to (or containing) s."""
    return [(i, t) for i, p in enumerate(lay) for t in p["texts"] if (t["s"] == s if exact else s in t["s"])]


def pdf_get(S, url):
    r = S.get(B + url)
    assert r.ok and r.content[:5] == b"%PDF-", (url, r.status_code, r.text[:200])
    return r.content


if os.environ.get("P2357C_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
assert A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Beispiel", "password": "password123", "email": "bob@example.com"}).ok
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "admin"})
org_join(B, "bob", ORG)
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})


def run(S, who, other=None):
    r = S.put(B + O + "/settings", json={"lang": "de", "currency": "EUR",
                                         "company_fields": {"name": "Studio Nordlicht GmbH", "street": "Musterweg 1", "zip": "12345",
                                                            "city": "Musterstadt", "country": "DE"}})
    check(r.ok, f"{who}: office settings {r.status_code} {r.text[:200]}")
    cl = S.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Kundenweg 5", "zip": "20000", "city": "Hamburg",
                                          "country": "DE"}).json()["id"]
    # ---- profile without a picture: the letter can still ask for the signature, nothing is printed
    check(S.put(B + L + "/profile", json={"name": "Jana Muster"}).ok, f"{who}: profile name")
    lid = S.post(B + L, json={"rcpt_name": "Amt fuer Beispiele", "rcpt_address": "Musterweg 1\n12345 Musterstadt", "subject": "Anfrage",
                              "body": "Sehr geehrte Damen und Herren,\n\nbitte senden Sie uns die Unterlagen.", "greeting": "Mit freundlichen Grüßen"}).json()["id"]
    r = S.patch(B + f"{L}/{lid}", json={"sign_image": 1})
    check(r.ok and r.json().get("sign_image") == 1, f"{who}: #3158 sign_image can be set without a picture {r.status_code} {r.text[:160]}")
    check(not any(sigs(pdf_get(S, f"{L}/{lid}/pdf"))), f"{who}: #3158 no picture in the profile -> none printed")
    # ---- with a picture: draft without, sent letter with it above the name
    r = S.put(B + L + "/profile", json={"image": SIG_URI})
    check(r.ok and r.json().get("has_image"), f"{who}: profile picture saved {r.status_code} {r.text[:160]}")
    data = pdf_get(S, f"{L}/{lid}/pdf")
    check(not any(sigs(data)), f"{who}: #3158 the draft letter (watermark) carries no signature picture")
    lay = pdfcheck.layout(data)
    nm = find(lay, "Jana Muster")
    check(len(nm) == 1, f"{who}: the draft names the signer {nm}")
    r = S.post(B + f"{L}/{lid}/sent", json={})
    check(r.ok, f"{who}: letter sent {r.status_code} {r.text[:160]}")
    data = pdf_get(S, f"{L}/{lid}/pdf")
    sg, lay = sigs(data), pdfcheck.layout(data)
    nm2 = find(lay, "Jana Muster")
    gr = find(lay, "Mit freundlichen Grüßen")
    check(sum(len(x) for x in sg) == 1 and nm2 and gr, f"{who}: #3158 the sent letter carries the picture once {sg} {nm2} {gr}")
    if sum(len(x) for x in sg) == 1 and nm2 and gr:
        pi = next(i for i, x in enumerate(sg) if x)
        x, top, w, h = sg[pi][0]
        check(pi == nm2[0][0] == gr[0][0] and gr[0][1]["y"] < top and top + h <= nm2[0][1]["y"] + 0.5,
              f"{who}: #3158 picture between greeting and name, one page ({pi}, greeting {gr[0][1]['y']:.1f}, pic {top:.1f}+{h:.1f}, name {nm2[0][1]['y']:.1f})")
        check(nm == [] or abs(nm[0][1]["y"] - nm2[0][1]["y"]) < 0.5, f"{who}: #3158 the draft keeps the room of the picture (name at the same height)")
    # ---- documents from templates
    tc = S.post(B + TP, json={"kind": "contract", "name": "Vertrag", "lang": "de", "sign": 1,
                              "body": "# Vertrag\n\nZwischen den Parteien wird folgendes vereinbart.\n\nOrt, den heutigen Tag. Mit freundlichen Grüßen"}).json()
    g = S.post(B + GD, json={"template_id": tc["id"], "client_id": cl, "sign_image": 1}).json()
    check(g.get("sign_image") is True and g.get("sign_mine") is True, f"{who}: #3158 a new document with the own signature {g.get('sign_image')} {g.get('sign_mine')}")
    check(not any(sigs(pdf_get(S, f"{GD}/{g['id']}/pdf"))), f"{who}: #3158 template draft: no picture")
    r = S.post(B + f"{GD}/{g['id']}/final")
    check(r.ok and r.json().get("sign_mine") is True, f"{who}: finished {r.status_code} {r.text[:160]}")
    data = pdf_get(S, f"{GD}/{g['id']}/pdf")
    sg, lay = sigs(data), pdfcheck.layout(data)
    cap = find(lay, "Ort, Datum, Unterschrift")
    check(sum(len(x) for x in sg) == 1 and len(cap) == 2, f"{who}: #3158 finished template document: picture once, two lines {sg} {len(cap)}")
    if sum(len(x) for x in sg) == 1 and len(cap) == 2:
        pi = next(i for i, x in enumerate(sg) if x)
        x, top, w, h = sg[pi][0]
        left = min(cap, key=lambda c: c[1]["x"])
        check(pi == left[0] and top + h <= left[1]["y"] and abs(x - left[1]["x"]) < 1 and top > left[1]["y"] - 80,
              f"{who}: #3158 the picture stands above the line of the own side ({x:.1f}/{top:.1f}+{h:.1f} vs caption {left[1]['x']:.1f}/{left[1]['y']:.1f})")
    check(not pdfcheck.problems(data), f"{who}: template document layout clean {pdfcheck.problems(data)[:3]}")
    # without signature lines: picture above the name
    tn = S.post(B + TP, json={"kind": "other", "name": "Bestätigung", "lang": "de", "sign": 0, "body": "Hiermit bestätigen wir den Termin."}).json()
    g2 = S.post(B + GD, json={"template_id": tn["id"], "client_id": cl, "sign_image": 1}).json()
    S.post(B + f"{GD}/{g2['id']}/final")
    data = pdf_get(S, f"{GD}/{g2['id']}/pdf")
    sg, lay = sigs(data), pdfcheck.layout(data)
    nm = find(lay, "Jana Muster")
    check(sum(len(x) for x in sg) == 1 and nm and sg[nm[0][0]] and sg[nm[0][0]][0][1] + sg[nm[0][0]][0][3] <= nm[0][1]["y"] + 0.5,
          f"{who}: #3158 no lines: picture above the name {sg} {nm}")
    # a copy keeps the signature only for its signer
    r = S.post(B + GD, json={"copy_of": g2["id"]})
    check(r.status_code == 201 and r.json().get("sign_mine") is True, f"{who}: #3158 the signer's copy keeps the signature")
    if other is not None:
        # never someone else's signature: Bob's copy, Bob finishing Alice's draft, Bob sending Alice's letter
        Bo_ = other
        check(Bo_.put(B + L + "/profile", json={"name": "Bob Beispiel", "image": SIG_URI}).ok, "bob: profile picture")
        r = Bo_.post(B + GD, json={"copy_of": g2["id"]})
        check(r.status_code == 201 and r.json().get("sign_image") is False, f"{who}: #3158 another person's copy has no signature {r.text[:160]}")
        g3 = S.post(B + GD, json={"template_id": tn["id"], "client_id": cl, "sign_image": 1}).json()
        j = Bo_.get(B + f"{GD}/{g3['id']}").json()
        check(j.get("sign_image") is True and j.get("sign_mine") is False, f"{who}: #3158 Bob sees Alice's choice, not as his own")
        r = Bo_.post(B + f"{GD}/{g3['id']}/final")
        check(r.ok and r.json().get("sign_image") is False, f"{who}: #3158 finished by Bob: Alice's signature dropped {r.text[:160]}")
        check(not any(sigs(pdf_get(S, f"{GD}/{g3['id']}/pdf"))), f"{who}: #3158 finished by Bob: no picture")
        g4 = S.post(B + GD, json={"template_id": tn["id"], "client_id": cl}).json()
        r = Bo_.patch(B + f"{GD}/{g4['id']}", json={"sign_image": 1})
        check(r.ok and r.json().get("sign_mine") is True and S.get(B + f"{GD}/{g4['id']}").json().get("sign_mine") is False,
              f"{who}: #3158 sign_image stores the asking person only")
        l2 = S.post(B + L, json={"rcpt_name": "Amt", "rcpt_address": "Weg 1\n12345 Ort", "subject": "Zweiter Brief", "body": "Text."}).json()
        check(l2.get("sign_image") == 1, f"{who}: a new letter takes the picture by default")
        Bo_.post(B + f"{L}/{l2['id']}/sent", json={})
        check(not any(sigs(pdf_get(S, f"{L}/{l2['id']}/pdf"))), f"{who}: #3158 Alice's letter sent by Bob: no signature (never someone else's)")
    # ---- #3182 the signature lines stay with the last paragraph and above the footer, whatever the text before
    bad = []
    for n in range(18, 46):
        body = "# Vertrag\n\n" + "\n\n".join(f"Absatz {i + 1}: ein kurzer Satz." for i in range(n)) + "\n\nOrt, den heutigen Tag. Mit freundlichen Grüßen"
        gx = S.post(B + GD, json={"client_id": cl, "title": "Vertrag", "body": body, "sign": 1}).json()
        data = pdf_get(S, f"{GD}/{gx['id']}/pdf")
        lay = pdfcheck.layout(data)
        cap = find(lay, "Ort, Datum, Unterschrift")
        last = find(lay, "Ort, den heutigen Tag. Mit freundlichen Grüßen")
        pr = pdfcheck.problems(data)
        if len(cap) != 2 or not last or cap[0][0] != last[-1][0] or cap[1][0] != last[-1][0] or pr:
            bad.append((n, [c[0] for c in cap], [x[0] for x in last], pr[:2]))
        S.delete(B + f"{GD}/{gx['id']}")
    check(not bad, f"{who}: #3182 lines + last paragraph on one page, nothing over the footer {bad[:3]}")
    gx = S.post(B + GD, json={"client_id": cl, "title": "Vertrag " + "über eine sehr lange Zusammenarbeit " * 4, "body": "Text.", "sign": 0}).json()
    data = pdf_get(S, f"{GD}/{gx['id']}/pdf")
    check(not pdfcheck.problems(data), f"{who}: #3182 a long title wraps inside the page {pdfcheck.problems(data)[:2]}")
    # ---- quotations: the order sentence; the office setting sign_offers
    st = S.get(B + O + "/settings").json()["settings"]
    check(st.get("sign_offers") == 0, f"{who}: #3158 sign_offers is off by default ({st.get('sign_offers')!r})")
    q = S.post(B + D, json={"client_id": cl, "project_title": "Imagefilm"}).json()["id"]
    S.put(B + f"{D}/{q}/items", json={"items": [{"kind": "service", "title": "Kamera", "qty": 1, "unit": "day", "rate": 1000}]})
    data = pdf_get(S, f"{D}/{q}/pdf")
    check(not any(sigs(data)), f"{who}: #3158 quotation draft without picture")
    S.put(B + O + "/settings", json={"sign_offers": 1})
    check(not any(sigs(pdf_get(S, f"{D}/{q}/pdf"))), f"{who}: #3158 sign_offers on: the draft still has no picture")
    r = S.post(B + f"{D}/{q}/finalize")
    check(r.ok, f"{who}: quotation finalised {r.status_code} {r.text[:160]}")
    data = pdf_get(S, f"{D}/{q}/pdf")
    lay = pdfcheck.layout(data)
    check(sum(len(x) for x in sigs(data)) == 1, f"{who}: #3158 sign_offers on: the finalised quotation carries the picture {sigs(data)}")
    acc = find(lay, "Hiermit erteilen wir den Auftrag zu den Bedingungen dieses Angebots.")
    cap = find(lay, "Unterschrift, Stempel Auftraggeber")
    check(len(acc) == 1 and cap and acc[0][0] == cap[0][0] and acc[0][1]["y"] < cap[0][1]["y"] - 20,
          f"{who}: #3182 the order sentence above the signature lines {acc} {cap}")
    # 2.357.0 (#3158, review M1): the picture is frozen at finalising: a later setting or a new profile picture never changes it
    frozen = sig_raw(data)
    S.put(B + O + "/settings", json={"sign_offers": 0})
    later = pdf_get(S, f"{D}/{q}/pdf")
    check(sum(len(x) for x in sigs(later)) == 1 and sig_raw(later) == frozen and frozen, f"{who}: M1 setting off later: the finalised quotation keeps its picture")
    S.put(B + L + "/profile", json={"image": "data:image/png;base64," + base64.b64encode(png_sig(220, 50)).decode()})
    later = pdf_get(S, f"{D}/{q}/pdf")
    check(sig_raw(later) == frozen, f"{who}: M1 a new profile picture does not change the finalised quotation")
    S.put(B + L + "/profile", json={"image": SIG_URI})
    q2 = S.post(B + D, json={"client_id": cl, "project_title": "Zweiter Film"}).json()["id"]
    S.put(B + f"{D}/{q2}/items", json={"items": [{"kind": "service", "title": "Schnitt", "qty": 1, "unit": "day", "rate": 800}]})
    S.post(B + f"{D}/{q2}/finalize")
    check(not any(sigs(pdf_get(S, f"{D}/{q2}/pdf"))), f"{who}: #3158 sign_offers off: no picture")


run(A, "org admin", Bo)
FID, Fr = freelancer(B, A)
run(Fr, "freelancer")

# ---------------------------------------------------------------- #3182 the rights appendix (pdf.py, no server)
SRC = os.path.abspath(os.environ.get("KALMIDO_SRC") or os.path.join(N, ".."))
spec = importlib.util.spec_from_file_location("office_pdf_2357c", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)
CO = {"name": "Studio Nordlicht GmbH", "lines": ["Musterweg 1", "12345 Musterstadt"], "contact_lines": ["E-Mail: info@example.com"],
      "bank_lines": ["IBAN DE89 3704 0044 0532 0130 00"], "color": "#2f5d8a"}


def model(**kw):
    m = {"kind": "offer", "lang": "de", "currency": "EUR", "number": "KVA-2026-357", "date": "2026-10-26", "title": "Angebot",
         "project_title": "Imagefilm", "company": dict(CO), "recipient": {"name": "Beispielkunde AG", "lines": ["Marktplatz 2", "54321 Beispielort"]},
         "meta": [["Angebot Nr.", "KVA-2026-357"], ["Datum", "26.10.2026"]], "intro": "Sehr geehrte Damen und Herren,\nvielen Dank.",
         "lines": [{"kind": "item", "pos": 1, "title": "Kamera", "qty": 1, "qty_text": "1", "unit_text": "Tag", "rate": 1000,
                    "rate_text": "1.000,00 €", "tax_pct": 19, "total": 1000, "total_text": "1.000,00 €"}],
         "totals": {"rows": [["Summe netto", "1.000,00 €"]], "vat_note": "zzgl. USt"},
         "closing": "Wir freuen uns auf die Zusammenarbeit.", "signature": "Mit freundlichen Grüßen", "labels": {"page_of": "Seite {x} von {y}"},
         "rights": {"title": "Rechteübertragung", "rows": [["Zeitraum", "unbegrenzt"], ["Gebiet", "weltweit"], ["Medien", "Online"]]}}
    m.update(kw)
    return m


data = pdf.office_pdf(model())
lay = pdfcheck.layout(data)
check(len(lay) == 1 and find(lay, "RECHTEÜBERTRAGUNG") and find(lay, "Hiermit erteilen wir den Auftrag zu den Bedingungen dieses Angebots."),
      f"#3182: one position + rights + order confirmation fit on ONE page ({len(lay)} pages)")
check(not pdfcheck.problems(data), f"#3182: one page layout clean {pdfcheck.problems(data)[:3]}")
SENT = "Dies ist ein Satz mit einigen Wörtern, der die Zeile füllt und umbricht, damit der Absatz wächst."
data = pdf.office_pdf(model(rights={"title": "Rechteübertragung", "rows": [[f"Recht {i}", SENT] for i in range(1, 25)]}))
lay = pdfcheck.layout(data)
hd = find(lay, "RECHTEÜBERTRAGUNG")
check(len(lay) >= 2 and hd and hd[0][0] >= 1 and not any(t["s"] == "Kamera" for t in lay[hd[0][0]]["texts"]),
      f"#3182: many rights rows keep the appendix on its own page ({len(lay)} pages, head on {hd[:1]})")
data = pdf.office_pdf(model(kind="delivery", rights={}))
check(not find(pdfcheck.layout(data), "Hiermit erteilen wir den Auftrag zu den Bedingungen dieses Angebots."), "#3182: no order sentence on a delivery note")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
