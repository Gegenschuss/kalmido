#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.591.0 B (#4863): archive numbers from codes - digits only, every page, a hint when the number is taken. Invented values only.
freelancer-matrix: files
A person WITHOUT an organisation (frida) scans (QR codes drawn in the test container: segno + Pillow are in the image):
 - a sticker whose QR code holds only "00143" -> archive number 143 (red before: no prefix, no number)
 - a three-page scan with the sticker "ASN00007" on page 3 -> 7 (red before: only page 1 was read)
 - another scan with "00143" -> no number, but the hint asn_taken names the document that has it (id, name), "in the
   trash" once that one is deleted; the agent API (v1) carries no such hint; a number set by hand ends the hint
 - the digits "00143" in a text file never become an archive number
usage: p2591_b_asn_test.py <datadir>   (P2591BA_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import base64
import subprocess
import sys

import requests

import kt
from kt import B, CT, check, until
from freelancer_fixture import freelancer

kt.fresh(prefix="P2591BA")
A = kt.setup()
FEAT = "docs,files"
_fid, F = freelancer(B, A, features=FEAT)
F.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})


def qr_pdf(texts, tag=""):
    """A scan of len(texts) pages; page i carries a QR code with texts[i] (None: an empty page). tag makes the bytes differ."""
    code = ("import base64, io, json, segno\nfrom PIL import Image, ImageDraw\npages = []\n"
            "for i, t in enumerate(json.loads(%r)):\n"
            "    page = Image.new('L', (1654, 2339), 255)\n"
            "    ImageDraw.Draw(page).text((100, 100 + 40 * i), %r + ' page ' + str(i + 1), fill=0)\n"
            "    if t:\n"
            "        b = io.BytesIO()\n        segno.make(t, micro=False).save(b, kind='png', scale=8, border=4)\n"
            "        page.paste(Image.open(b).convert('L'), (1200, 100))\n"
            "    pages.append(page)\n"
            "o = io.BytesIO()\npages[0].save(o, 'PDF', resolution=200, save_all=True, append_images=pages[1:])\n"
            "print(base64.b64encode(o.getvalue()).decode())") % (__import__("json").dumps(texts), tag)
    out = subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True, check=True)
    return base64.b64decode(out.stdout)


def up(name, data, mime="application/pdf"):
    r = F.post(B + "/api/docs", data={"ws": "private"}, files=[("files", (name, data, mime))])
    assert r.status_code == 201, r.text
    return r.json()["ids"][0]


def doc(nid):
    r = F.get(B + f"/api/docs/{nid}")
    return r.json() if r.ok else None


def done(nid):
    return until(lambda: (lambda d: d if d and d["state"] in ("done", "failed") else None)(doc(nid)), 120)


st = F.get(B + "/api/docs/settings", params={"ws": "private"}).json()
check(st.get("ocr") is True, f"setup: the test image reads codes and text {st.get('ocr')}")

q1 = up("aufkleber.pdf", qr_pdf(["00143"], "eins"))
d = done(q1)
check(d and d["asn"] == 143 and d["auto"].get("asn") == "code", f"#4863: a QR code of digits only gives archive number 143 {d and (d['asn'], d['auto'])}")
check(d and "asn_taken" not in d, "no hint on the document that got the number")

q2 = up("drei-seiten.pdf", qr_pdf([None, None, "ASN00007"], "zwei"))
d = done(q2)
check(d and d["asn"] == 7, f"#4863: the sticker on page 3 is read {d and (d['asn'], d['pages'])}")

q3 = up("nochmal.pdf", qr_pdf(["00143"], "drei"))
d = done(q3)
t = (d or {}).get("asn_taken") or {}
check(d and d["asn"] is None and t.get("asn") == 143 and (t.get("doc") or {}).get("id") == q1
      and (t.get("doc") or {}).get("name", "").startswith("aufkleber") and (t.get("doc") or {}).get("trash") is False,
      f"#4863: the number is taken - the document says by which one {d and (d['asn'], t)}")

tok = F.post(B + "/api/me/tokens", json={"name": "lesen", "scopes": ["read", "files:read"]}).json().get("token", "")
r = requests.get(B + f"/api/v1/documents/{q3}", headers={"Authorization": "Bearer " + tok})
check(r.ok and r.json().get("asn") is None and "asn_taken" not in r.json(), f"#4863: the agent API carries no such hint {r.status_code} {r.text[:120]}")

check(F.delete(B + f"/api/files/nodes/{q1}").ok, "setup: the first document into the trash")
t = (doc(q3) or {}).get("asn_taken") or {}
check(t.get("asn") == 143 and (t.get("doc") or {}).get("trash") is True, f"#4863: the hint says the holder is in the trash {t}")

r = F.patch(B + f"/api/docs/{q3}", json={"asn": 144})
d = doc(q3)
check(r.ok and d and d["asn"] == 144 and "asn_taken" not in d, f"a number set by hand ends the hint {r.status_code} {d and d.get('asn_taken')}")
r = F.patch(B + f"/api/docs/{q3}", json={"asn": None})
check(r.ok and "asn_taken" not in (doc(q3) or {}), "emptied again: the old hint does not come back")

q4 = up("kundennummer.txt", b"Kundennummer\n00143\nBeispiel GmbH", "text/plain")
d = done(q4)
check(d and d["asn"] is None and "asn_taken" not in d, f"#4863: digits in the text are no archive number {d and d['asn']}")

sys.exit(kt.done("p2591_b_asn"))
