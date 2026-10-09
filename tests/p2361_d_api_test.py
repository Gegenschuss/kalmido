#!/usr/bin/env python3
"""2.36.1 API tests, part D: the quotation PDF and the company logo of Office & finance (#1021), own container in mode
workspaces (start.sh).
 - GET /api/office/docs/<id>/pdf: a PDF (application/pdf, Content-Disposition with the document's number, ?inline=1 shows
   it in the browser) for the organisation's admin and members; pypdf reads the number, recipient, positions, net total
   and the rights texts from it; a long quotation gives several pages with "Seite x von y"
 - POST /api/office/logo (organisation admin only): PNG / JPEG / WebP up to 4 MB, scaled to at most 1600 px width,
   stored as office/<org>/logo.png below the data folder and noted in the settings; SVG, text and oversized files are
   refused; GET /api/office/logo serves it to members, DELETE removes it; the PDF carries the logo as an image
 - tenant matrix (tenant-matrix: office): the second organisation gets 404 for the PDF and its own logo slot, a private
   person 400, an agent token 403, signed out 401, feature off 403
 - backups: the logo is part of a backup (member office/<org>/logo.png in the zip) and comes back with a restore
usage: p2361_d_api_test.py <datadir>"""
import io
import json
import os
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


try:
    from pypdf import PdfReader
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    print("pypdf and pillow are needed (tests/requirements.txt)")
    sys.exit(2)


def pdf_texts(data):
    r = PdfReader(io.BytesIO(data))
    return r, [p.extract_text() or "" for p in r.pages]


def has_image(page):
    try:
        xo = page["/Resources"].get("/XObject") or {}
        return any(xo[k].get_object().get("/Subtype") == "/Image" for k in xo)
    except Exception:  # noqa: BLE001
        return False


def picture(fmt="PNG", size=(900, 300), mode="RGBA"):
    im = Image.new(mode, size, (255, 255, 255, 0) if mode == "RGBA" else (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, size[0] - 10, size[1] - 10], fill=(47, 93, 138, 255) if mode == "RGBA" else (47, 93, 138))
    out = io.BytesIO()
    im.save(out, fmt)
    return out.getvalue()


def upload(s, data, name="logo.png", mime="image/png"):
    return s.post(B + "/api/office/logo", files={"file": (name, data, mime)})


FEAT = "cal,comments,collab,office,clients"
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT})
ME = A.get(B + "/api/state").json()["me"]
ALICE = ME["id"]
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123"}).json()["id"]
DAVE = A.post(B + "/api/users", json={"username": "dave", "display_name": "Dave Private", "password": "password123"}).json()["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT})
# mode workspaces: Alpha (alice admin, bob member), Beta (carol admin), dave in no organisation
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.ok, r.text
ORG = r.json()["id"]
r = A.patch(B + f"/api/admin/orgs/{ORG}", json={"members": [ALICE, BOB], "admins": [ALICE]})
assert r.ok, (r.status_code, r.text)
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.ok, r.text
ORG2 = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
wss = {n: {w["id"]: w.get("role") for w in s.get(B + "/api/state").json()["me"].get("workspaces") or []} for n, s in (("alice", A), ("bob", Bo), ("carol", Ca), ("dave", Da))}
assert wss["alice"].get(ORG) == "admin" and wss["bob"].get(ORG) == "member" and list(wss["carol"]) == [ORG2] and wss["dave"] == {}, wss
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
D = "/api/office/docs"
OFFICE = os.path.join(DATA, "office")

# ---------------------------------------------------------------- settings, services and one quotation (invented data; B's and C's routes)
r = A.put(B + "/api/office/settings", json={"company": {"name": "Studio Nordlicht GmbH", "lines": ["Studio Nordlicht GmbH", "Hafenstraße 12", "20457 Hamburg"],
                                                        "contact_lines": ["post@beispiel-studio.example"], "register_lines": ["Amtsgericht Hamburg HRB 00000"],
                                                        "bank_lines": ["Beispielbank", "IBAN DE00 0000 0000 0000 0000 00"]},
                                            "lang": "de", "currency": "EUR", "prod_quotient": 3, "raw_factor": 0.25, "producing_rate": 600,
                                            "offer_valid_days": 30, "offer_scheme": "KVA-{yyyy}-{seq:03}", "color": "#1f7a68"})
check(r.ok, "settings saved " + r.text[:200])
check(r.json()["settings"].get("logo", "") == "", "no logo at the start")


def svc(name_de, name_en, rate, cat="Video", raw=0, prod=0, unit="day"):
    r = A.post(B + "/api/office/services", json={"name_de": name_de, "name_en": name_en, "category": cat, "daily_rate": rate, "hourly_rate": None,
                                                 "raw_fee": raw, "producing": prod, "intext": "intern", "unit": unit, "tax": "standard"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


S_STORY = svc("Storyboard-Erstellung", "Storyboard creation", 980)
S_ANIM = svc("Animation 2D / Motion Design", "Animation 2D / motion design", 1080, raw=1, prod=1)
S_CUT = svc("Schnitt", "Editing", 980, raw=1, prod=1)
S_SOUND = svc("Sound Design", "Sound design", 980, cat="Audio", raw=1, prod=1)
r = A.post(B + D, json={"project_title": "Imagefilm Herbstkampagne", "project_ref": "PO-4711",
                        "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "z. Hd. Max Mustermann", "Marktstraße 5", "50667 Köln"]}})
assert r.status_code == 201, r.text
DOC, NUMBER = r.json()["id"], r.json()["number"]
r = A.put(B + f"{D}/{DOC}/items", json={"items": [{"service_id": S_STORY, "qty": 3}, {"service_id": S_ANIM, "qty": 4.5}, {"service_id": S_CUT, "qty": 2},
                                                   {"kind": "text", "detail": "Die Untertitel liefern wir als SRT-Datei."}, {"service_id": S_SOUND, "qty": 1}]})
check(r.ok, "positions set " + r.text[:200])
NET = r.json()["totals"]["net"] if r.ok else 0

# ---------------------------------------------------------------- the PDF
r = A.get(B + f"{D}/{DOC}/pdf")
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/pdf"), f"GET pdf -> 200 application/pdf ({r.status_code} {r.headers.get('Content-Type')})")
check(r.headers.get("Content-Disposition") == f'attachment; filename="{NUMBER}.pdf"', f"Content-Disposition with the number: {r.headers.get('Content-Disposition')}")
check(r.headers.get("Cache-Control") == "no-store", "the PDF is not cached")
rd, T = pdf_texts(r.content)
all_t = "\n".join(T)
check(r.content.startswith(b"%PDF-1.4"), "a PDF 1.4 file")
for want in (NUMBER, "Beispielkunde AG", "z. Hd. Max Mustermann", "50667 Köln", "KOSTENVORANSCHLAG", "Imagefilm Herbstkampagne", "PO-4711",
             "Storyboard-Erstellung", "Animation 2D / Motion Design", "Sound Design", "Producing", "Die Untertitel liefern wir als SRT-Datei.",
             "Studio Nordlicht GmbH", "Hafenstraße 12", "Beispielbank", "Seite 1 von"):
    check(want in all_t, f"pdf text layer has {want!r}")
net_text = f"{NET:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"
check(net_text in all_t, f"the net total {net_text} is printed (model net {NET})")
check(not has_image(rd.pages[0]) and T[0].lstrip().startswith("Studio Nordlicht GmbH"), "without a logo: the company name heads the page, no image")
check("3750" not in all_t, "no internal figures in the PDF")
r = A.get(B + f"{D}/{DOC}/pdf?inline=1")
check(r.ok and r.headers.get("Content-Disposition", "").startswith("inline;"), "?inline=1 shows the PDF in the browser")
r = Bo.get(B + f"{D}/{DOC}/pdf")
check(r.status_code == 200 and r.content.startswith(b"%PDF"), "a member of the organisation gets the PDF")
# an English quotation in USD
r = A.post(B + D, json={"project_title": "Image film autumn campaign", "lang": "en", "currency": "USD",
                        "recipient": {"name": "Example Client Ltd.", "lines": ["Example Client Ltd.", "1 Sample Street", "London"]}})
EN = r.json()["id"]
A.put(B + f"{D}/{EN}/items", json={"items": [{"service_id": S_STORY, "qty": 2}]})
r = A.get(B + f"{D}/{EN}/pdf")
_, Ten = pdf_texts(r.content)
check(r.ok and "QUOTATION" in Ten[0] and "Example Client Ltd." in Ten[0] and "Page 1 of" in Ten[0].replace("  ", " "), "an English quotation: English labels and 'Page 1 of'")
check("$" in Ten[0] or "USD" in Ten[0], "USD amounts in the English PDF")
# a long quotation: several pages, every page numbered
r = A.post(B + D, json={"project_title": "Langes Angebot", "recipient": {"name": "Beispielkunde AG", "lines": ["Marktstraße 5", "50667 Köln"]}})
LONG = r.json()["id"]
items = []
for i in range(30):
    if i % 8 == 0:
        items.append({"kind": "heading", "title": f"Kategorie {i // 8 + 1}"})
    items.append({"service_id": S_STORY, "qty": 1, "title": f"Zusatzleistung Nr. {i + 1}"})
r = A.put(B + f"{D}/{LONG}/items", json={"items": items})
check(r.ok, "30 positions set " + r.text[:120])
r = A.get(B + f"{D}/{LONG}/pdf")
rl, Tl = pdf_texts(r.content)
nl = len(rl.pages)
check(nl >= 2, f"30 positions: several pages ({nl})")
check(all(f"Seite {i + 1} von {nl}".replace(" ", "") in t.replace(" ", "") for i, t in enumerate(Tl)), "every page carries 'Seite x von y'")
check(all(("LEISTUNG" in t and "GESAMT" in t) for t in Tl if "Zusatzleistung" in t), "the table head is repeated on every page with positions")
tot_page = next((t for t in Tl if "Summe Netto" in t), "")
check("Zusatzleistung" in tot_page or "Producing" in tot_page, "the totals never stand alone on a page")

# ---------------------------------------------------------------- tenant matrix (tenant-matrix: office)
check(Ca.get(B + f"{D}/{DOC}/pdf").status_code == 404, "the second organisation: 404 for the PDF")
check(Ca.get(B + f"{D}/{LONG}/pdf").status_code == 404 and Ca.get(B + f"{D}/999999/pdf").status_code == 404, "foreign and unknown ids: 404, never 403 with content")
check(A.get(B + f"{D}/999999/pdf").status_code == 404, "unknown document: 404")
check(Da.get(B + f"{D}/{DOC}/pdf").status_code == 400 and Da.get(B + "/api/office/logo").status_code == 400, "a private person without an organisation: 400")
ags = [requests.get(B + f"{D}/{DOC}/pdf", headers=AGH).status_code, requests.get(B + "/api/office/logo", headers=AGH).status_code,
       requests.post(B + "/api/office/logo", headers=AGH, files={"file": ("l.png", picture(), "image/png")}).status_code]
check(all(x in (401, 403) for x in ags), f"an agent token: refused on pdf and logo {ags}")
check(requests.get(B + f"{D}/{DOC}/pdf", headers=H).status_code in (401, 303) and requests.get(B + "/api/office/logo", headers=H).status_code in (401, 303),
      "signed out: refused")
check(requests.get(B + "/api/v1/office/docs/1/pdf", headers=AGH).status_code == 404, "no /api/v1 route for the PDF in stage 1")
Bo.patch(B + "/api/settings", json={"features": "cal,comments"})
check(Bo.get(B + f"{D}/{DOC}/pdf").status_code == 403 and Bo.get(B + "/api/office/logo").status_code == 403, "feature off: 403")
Bo.patch(B + "/api/settings", json={"features": FEAT})

# ---------------------------------------------------------------- the logo
check(A.get(B + "/api/office/logo").status_code == 404 and Bo.get(B + "/api/office/logo").status_code == 404, "no logo yet: 404")
check(upload(Bo, picture()).status_code == 403, "a member cannot upload the logo (403)")
check(Bo.delete(B + "/api/office/logo").status_code == 403, "a member cannot remove it (403)")
r = upload(A, picture())
check(r.status_code == 200 and r.json()["logo"] == "logo.png" and r.json()["width"] == 900 and r.json()["height"] == 300, f"the admin uploads a PNG: {r.text[:200]}")
LOGO = os.path.join(OFFICE, str(ORG), "logo.png")
check(os.path.isfile(LOGO), f"stored as office/{ORG}/logo.png below the data folder")
check(A.get(B + "/api/office/settings").json()["settings"]["logo"] == "logo.png", "the settings note the logo")
r = Bo.get(B + "/api/office/logo")
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/png") and r.content[:8] == b"\x89PNG\r\n\x1a\n", "a member gets the logo as PNG")
png1 = r.content
check(Image.open(io.BytesIO(png1)).mode == "RGBA", "transparency kept")
r = A.get(B + f"{D}/{DOC}/pdf")
rd, T = pdf_texts(r.content)
check(has_image(rd.pages[0]) and NUMBER in T[0], "the PDF carries the logo as an image")
r = A.get(B + f"{D}/{LONG}/pdf")
rl, _ = pdf_texts(r.content)
check(all(has_image(p) for p in rl.pages), "the small head of every following page shows the logo")
# formats and limits
r = upload(A, picture("JPEG", (2400, 600), "RGB"), "big.jpg", "image/jpeg")
check(r.status_code == 200 and r.json()["width"] == 1600 and r.json()["height"] == 400, f"a 2400 px JPEG is scaled to 1600 px width and stored as PNG: {r.text[:120]}")
check(A.get(B + "/api/office/logo").content[:8] == b"\x89PNG\r\n\x1a\n", "... served as PNG")
r = upload(A, picture("WEBP", (600, 200), "RGB"), "l.webp", "image/webp")
check(r.status_code == 200 and r.json()["width"] == 600, "WebP accepted")
r = upload(A, b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='10' height='10'/></svg>", "l.svg", "image/svg+xml")
check(r.status_code == 400 and "PNG" in r.text, f"SVG refused with the hint (PNG at least 600 px): {r.status_code} {r.text[:120]}")
check(upload(A, b"hello, not a picture", "l.txt", "text/plain").status_code == 400, "a text file refused")
check(A.post(B + "/api/office/logo").status_code == 400, "no file: 400")
big = b"\x89PNG" + b"\0" * (4 * 1024 * 1024 + 10)
check(upload(A, big).status_code == 413, "more than 4 MB: 413")
check(A.get(B + "/api/office/logo").status_code == 200, "the previous logo is kept after refused uploads")
# the second organisation has its own slot
check(Ca.get(B + "/api/office/logo").status_code == 404, "the second organisation has no logo (its own slot)")
r = upload(Ca, picture("PNG", (300, 100), "RGB"))
check(r.status_code == 200 and os.path.isfile(os.path.join(OFFICE, str(ORG2), "logo.png")), "the second organisation's admin uploads her own")
check(Ca.get(B + "/api/office/logo").content != A.get(B + "/api/office/logo").content, "each organisation gets its own logo")
check(Ca.delete(B + "/api/office/logo").ok and Ca.get(B + "/api/office/logo").status_code == 404 and A.get(B + "/api/office/logo").status_code == 200,
      "removing the second organisation's logo leaves the first one alone")

# ---------------------------------------------------------------- backup with the logo, restore brings it back
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, "backup started " + r.text[:100])
for _ in range(100):
    j = A.get(B + "/api/admin/backups").json()
    if not j["running"] and j["items"]:
        break
    time.sleep(0.3)
items_b = A.get(B + "/api/admin/backups").json()["items"]
check(items_b and not items_b[0]["encrypted"], f"a backup exists: {items_b[:1]}")
NAME = items_b[0]["name"]
with zipfile.ZipFile(os.path.join(DATA, "backups", NAME)) as z:
    names = z.namelist()
    man = json.loads(z.read("manifest.json"))
check(f"office/{ORG}/logo.png" in names, f"the logo is a member of the backup zip: {names}")
check(any(f[0] == f"office/{ORG}/logo.png" for f in man["files"]), "... and listed in the manifest with its hash")
check(f"office/{ORG2}/logo.png" not in names, "the removed logo of the second organisation is not in it")
check(A.delete(B + "/api/office/logo").ok and not os.path.exists(LOGO) and A.get(B + "/api/office/logo").status_code == 404, "the admin removes the logo: file gone, 404")
r = A.get(B + f"{D}/{DOC}/pdf")
check(r.ok and not has_image(pdf_texts(r.content)[0].pages[0]), "without the logo the PDF shows the company name again")
r = A.post(B + "/api/admin/backups/restore", json={"name": NAME, "confirm": "RESTORE"})
check(r.ok, f"restore: {r.status_code} {r.text[:160]}")
A = sess("alice")
check(os.path.isfile(LOGO) and A.get(B + "/api/office/logo").status_code == 200 and A.get(B + "/api/office/settings").json()["settings"]["logo"] == "logo.png",
      "after the restore the logo file and the setting are back")
r = A.get(B + f"{D}/{DOC}/pdf")
check(r.ok and has_image(pdf_texts(r.content)[0].pages[0]), "... and the PDF carries it again")

print(f"p2361_d_api_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
