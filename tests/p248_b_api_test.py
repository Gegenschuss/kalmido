#!/usr/bin/env python3
"""2.48.0 API tests, part B (#1111): documents. Invented names only; the test documents are generated here (a PDF with a
text layer written by hand, a "scan" = an image PDF drawn with Pillow).
 - upload -> recognition in the background: text layer and OCR (skipped with a clear note when the image has no Tesseract),
   date / due date / amount, preview image, sealed text and amount in the database (server key set)
 - full-text search over the HMAC word index (whole words, prefixes), nothing for words that are not there
 - corrections train the workspace's model: sure matches set directly ("learn"), the rest waits in "To review"; accept
 - rules (any / regex), an evil regex refused; the level "agent" leaves a feature to an agent (a suggestion)
 - workspace boundary: an organisation's documents only for its members (list, search, detail), private ones only for
   the owner; settings of an organisation only for its admins; models never shared between workspaces
 - agents: nothing without a share; with view they read, with edit they set fields ("agent"); every access in fs_log
 - a task for the due date; the inbox folder "Dokumente/Eingang"; the forwarding address (mail with a PDF attachment)
 - trash + restore of a document (the file store's routes), rollback: only new tables / columns
usage: p248_b_api_test.py <datadir>      (a fresh container; P248B_NOSTART=1: the container runs already)"""
import email.message
import io
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
MAILENV = ["-e", "KALMIDO_MAIL_ADDRESS=tasks@example.test", "-e", "KALMIDO_IMAP_HOST=127.0.0.1", "-e", "KALMIDO_IMAP_PORT=1143",
           "-e", "KALMIDO_IMAP_SSL=0", "-e", "KALMIDO_IMAP_USER=kalmido", "-e", "KALMIDO_IMAP_PASSWORD=secret", "-e", "KALMIDO_IMAP_INTERVAL=600",
           "-e", "KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=", "-e", "KALMIDO_DOCS_SCAN_S=2"]


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


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def text_pdf(lines):
    """A one-page PDF with a text layer (hand-written, no library)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 12 Tf 60 740 Td 16 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET").encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def scan_pdf(lines):
    """An image-only PDF (a "scan"): black text drawn on a white page with Pillow, no text layer. Without Pillow on this
    machine it is drawn inside the test container (the image has Pillow)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        import base64
        import json
        code = ("import base64, io, json, sys\nfrom PIL import Image, ImageDraw, ImageFont\nf = ImageFont.load_default(size=44)\n"
                "im = Image.new('L', (1654, 2339), 255)\nd = ImageDraw.Draw(im)\n"
                "for i, ln in enumerate(json.loads(sys.argv[1])):\n    d.text((150, 200 + i * 90), ln, fill=0, font=f)\n"
                "b = io.BytesIO()\nim.save(b, 'PDF', resolution=200)\nprint(base64.b64encode(b.getvalue()).decode())")
        out = subprocess.run(["docker", "exec", CT, "python", "-c", code, json.dumps(lines)], capture_output=True, text=True, check=True)
        return base64.b64decode(out.stdout)
    font = None
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
              "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(p):
            font = ImageFont.truetype(p, 44)
            break
    if font is None:
        try:
            font = ImageFont.load_default(size=44)
        except TypeError:
            font = ImageFont.load_default()
    im = Image.new("L", (1654, 2339), 255)
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        d.text((150, 200 + i * 90), ln, fill=0, font=font)
    b = io.BytesIO()
    im.save(b, "PDF", resolution=200)
    return b.getvalue()


def upload(s, files, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", f) for f in files])
    return r


def doc(s, nid):
    return s.get(B + f"/api/docs/{nid}")


def done(s, nid, secs=90):
    return until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(doc(s, nid)), secs)


def ids_of(s, **params):
    r = s.get(B + "/api/docs", params={"facets": "0", **params})
    return [d["id"] for d in r.json()["docs"]] if r.ok else None


# ---- setup (like part A): alice (instance admin, private), Alpha = bob (admin) + carol, Beta = dave, erin alone
if not os.environ.get("P248B_NOSTART"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA],
                       env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = ids["bob"], ids["carol"], ids["dave"], ids["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok, "setup: carol joins Alpha")
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id NOT IN (?))",
    (ORG, BOB, CAROL, ORG2, DAVE), write=True)
r = A.post(B + "/api/admin/agents", json={"username": "alicebot", "display_name": "Alicebot"})
assert r.status_code == 201, r.text
PAG, PAGT = r.json()["id"], r.json().get("token") or ""
dbx("DELETE FROM org_members WHERE user_id=?", (PAG,), write=True)
dbx("UPDATE agents SET org_id=NULL, owner_id=1 WHERE user_id=?", (PAG,), write=True)  # alice's personal agent
for s in (A, Bo):
    s.post(B + "/api/auth/logout")
A, Bo, Ca, Da, Er = sess("alice"), sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
AGS = tok(PAGT)

cols = dbx("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name LIKE 'doc\\_%'")
check({x[0] for x in cols} >= {"doc_meta", "doc_senders", "doc_types", "doc_tags", "doc_node_tags", "doc_rules", "doc_models", "doc_cfg",
                               "doc_words", "doc_mail"}, f"the new tables ({sorted(x[0] for x in cols)})")
OCR = A.get(B + "/api/docs/settings", params={"ws": "private"}).json().get("ocr")
if not OCR:
    print("NOTE: this image has no Tesseract (deu+eng) -- the OCR checks are skipped (build the image from the Dockerfile)", flush=True)

# ---- upload, recognition, sealing
INS = ["Versicherung Beispiel AG", "Beitragsrechnung vom 01.09.2026", "Police Haftpflicht Hausrat", "Rechnungsbetrag 89,90 EUR",
       "faellig am 30.09.2026"]
SCAN = ["Stadtwerke Musterstadt", "Rechnung vom 03.10.2026", "Kilowattstunden Abschlag Strom", "Gesamtbetrag 119,00 EUR"]
r = upload(A, [("versicherung.pdf", text_pdf(INS), "application/pdf"), ("scan.pdf", scan_pdf(SCAN), "application/pdf")])
check(r.status_code == 201 and len(r.json()["ids"]) == 2, f"upload two documents ({r.status_code} {r.text[:150]})")
D1, D2 = r.json()["ids"]
d1 = done(A, D1)
check(d1 and d1["state"] == "done" and d1["method"] == "pdf", f"text layer read ({d1 and (d1['state'], d1['method'], d1['error'])})")
check(d1 and d1["date"] == "2026-09-01" and d1["due"] == "2026-09-30", f"date + due date ({d1 and (d1['date'], d1['due'])})")
check(d1 and d1["amount"] == "89.90" and d1["currency"] == "EUR", f"amount ({d1 and (d1['amount'], d1['currency'])})")
check(d1 and d1["review"] and "Haftpflicht" in d1["text"], "new unsorted document waits in To review, text there")
d2 = done(A, D2, 120)
if OCR:
    check(d2 and d2["method"] == "ocr" and "Kilowattstunden" in (d2.get("text") or ""), f"OCR of the scan ({d2 and (d2['state'], d2['method'], d2['error'])})")
    check(d2 and d2["amount"] == "119.00" and d2["date"] == "2026-10-03", f"OCR: amount + date ({d2 and (d2['amount'], d2['date'])})")
    check(d2 and d2["thumb"] and A.get(B + f"/api/docs/{D2}/thumb").headers.get("Content-Type") == "image/jpeg", "preview image of the scan")
else:
    check(d2 and d2["state"] == "failed" and d2["error"] == "no_ocr", f"without Tesseract: a clear failure, no 500 ({d2})")
row = dbx("SELECT text, amount FROM doc_meta WHERE node_id=?", (D1,))[0]
check(row[0].startswith("kenc1:") and row[1].startswith("kenc1:"), "text and amount sealed in the database")
check(not any("haftpflicht" in (x[0] or "").lower() for x in dbx("SELECT h FROM doc_words WHERE node_id=?", (D1,))), "word index holds hashes only")
check(A.get(B + f"/api/docs/{D1}/file").content[:4] == b"%PDF", "the file itself")
# 2.48.0 review (L3): the preview of a private document is sealed on disk like its text, the route opens it
th = dbx("SELECT thumb FROM doc_meta WHERE node_id=?", (D1,))[0][0]
if th:
    raw = open(os.path.join(DATA, "attachments", th), "rb").read()
    check(raw.startswith(b"KENC1\n") and A.get(B + f"/api/docs/{D1}/thumb").content[:2] == b"\xff\xd8", "private preview: sealed on disk, a JPEG from the route")
else:
    print("NOTE: no preview image for the text PDF in this image -- the sealing check of the preview is skipped", flush=True)

# ---- search
check(ids_of(A, q="haftpflicht") == [D1], "search: a whole word")
check(ids_of(A, q="Beitragsrech") == [D1], "search: a prefix")
check(ids_of(A, q="police hausrat") == [D1], "search: two words")
check(ids_of(A, q="nichtdrin") == [], "search: a word that is not there")
if OCR:
    check(ids_of(A, q="kilowattstunden") == [D2], "search finds a word recognised by OCR")

# ---- corrections train, sure / unsure, accept
r = A.patch(B + f"/api/docs/{D1}", json={"sender": "Versicherung Beispiel AG", "type": "Beitragsrechnung", "tags": ["Versicherung"]})
check(r.ok and r.json()["sender"]["name"] == "Versicherung Beispiel AG" and r.json()["auto"] == {}, f"correct the fields ({r.text[:150]})")
more = [("vers2.pdf", ["Versicherung Beispiel AG", "Police Haftpflicht Beitrag", "Beitragsrechnung 2026", "Hausrat Versicherungsschein"], "Versicherung Beispiel AG"),
        ("stadt1.pdf", ["Stadtwerke Musterstadt", "Abschlag Strom Kilowattstunden", "Zaehlerstand Verbrauch"], "Stadtwerke Musterstadt"),
        ("stadt2.pdf", ["Stadtwerke Musterstadt", "Jahresabrechnung Strom Verbrauch", "Kilowattstunden Zaehlerstand"], "Stadtwerke Musterstadt")]
for name, lines, sender in more:
    nid = upload(A, [(name, text_pdf(lines), "application/pdf")]).json()["ids"][0]
    done(A, nid)
    A.patch(B + f"/api/docs/{nid}", json={"sender": sender})
    A.post(B + f"/api/docs/{nid}/review", json={"done": True})
check(len(dbx("SELECT 1 FROM doc_models WHERE ws=?", (f"u{1}",))) >= 3, "models of alice's workspace stored")
check(dbx("SELECT data FROM doc_models WHERE ws=? AND feature='sender'", ("u1",))[0][0].startswith("kenc1:"), "models sealed")
nid = upload(A, [("vers3.pdf", text_pdf(["Versicherung Beispiel AG", "Police Haftpflicht Beitrag Hausrat", "Beitragsrechnung"]), "application/pdf")]).json()["ids"][0]
d = done(A, nid)
learnt = d and d["sender"] and d["sender"]["name"] == "Versicherung Beispiel AG" and d["auto"].get("sender") == "learn"
offered = d and d["suggest"].get("sender", {}).get("label") == "Versicherung Beispiel AG"
check(learnt or offered, f"learnt sender: set or suggested ({d and (d['sender'], d['auto'], d['suggest'])})")
if offered:
    r = A.post(B + f"/api/docs/{nid}/accept", json={})
    check(r.ok and r.json()["sender"]["name"] == "Versicherung Beispiel AG", "accept the suggestion")
r = A.post(B + f"/api/docs/{nid}/review", json={"done": True})
check(r.ok and not r.json()["review"], "checked: out of To review")
check(nid not in ids_of(A, review="1"), "review filter")
check(A.post(B + f"/api/docs/{nid}/review", json={"done": False}).json()["review"], "undo: back into To review")

# ---- rules, evil regex, level agent
r = A.post(B + "/api/docs/rules", json={"ws": "private", "kind": "regex", "match": "(a+)+$", "type": "X"})
check(r.status_code == 400, f"an evil regex is refused ({r.status_code})")
r = A.post(B + "/api/docs/rules", json={"ws": "private", "kind": "any", "match": "Gaszaehler", "type": "Abschlag", "tags": "Energie, Haus",
                                         "folder": "Energie"})
check(r.status_code == 201, f"a rule ({r.text[:120]})")
r = A.post(B + "/api/docs/rules", json={"ws": "private", "kind": "regex", "match": r"Vertrag\s+Nr\.?\s*\d+", "sender": "Vermieter GmbH"})
check(r.status_code == 201, f"a regex rule ({r.text[:120]})")
nid = upload(A, [("gas.pdf", text_pdf(["Gaszaehler Ablesung", "Vertrag Nr. 4711", "Datum 02.10.2026"]), "application/pdf")]).json()["ids"][0]
d = done(A, nid)
check(d and d["type"] and d["type"]["name"] == "Abschlag" and d["auto"].get("type") == "rule", f"rule sets the type ({d and d['type']})")
check(d and sorted(t["name"] for t in d["tags"]) == ["Energie", "Haus"], f"rule sets tags ({d and d['tags']})")
check(d and d["sender"] and d["sender"]["name"] == "Vermieter GmbH", f"regex rule sets the sender ({d and d['sender']})")
check(d and d["folder"] and d["folder"]["name"] == "Energie", f"rule puts it into a folder of the same workspace ({d and d['folder']})")
check(A.put(B + "/api/docs/settings", json={"ws": "private", "levels": {"type": "agent"}}).json()["levels"]["type"] == "agent", "level agent")

# ---- labels: rename, delete + its undo (the documents get it back, no training)
sid_ = A.get(B + f"/api/docs/{D1}").json()["sender"]["id"]
check(A.patch(B + f"/api/docs/labels/sender/{sid_}", json={"name": "Versicherung Beispiel AG (neu)"}).ok and
      A.get(B + f"/api/docs/{D1}").json()["sender"]["name"] == "Versicherung Beispiel AG (neu)", "rename a sender")
r = A.delete(B + f"/api/docs/labels/sender/{sid_}")
check(r.ok and D1 in r.json()["ids"] and A.get(B + f"/api/docs/{D1}").json()["sender"] is None, "delete a sender: the documents lose it")
r = A.post(B + "/api/docs/labels/sender", json={"ws": "private", "name": r.json()["name"], "ids": r.json()["ids"]})
check(r.status_code == 201 and A.get(B + f"/api/docs/{D1}").json()["sender"]["name"] == "Versicherung Beispiel AG (neu)", "undo: back on the documents")
check(Bo.delete(B + f"/api/docs/labels/sender/{r.json()['id']}").status_code == 404, "another person cannot delete the label")

# ---- archive serial numbers: a QR code on a scan, unique per workspace, the next free one, search
def qr_pdf(text):
    """A scan with a QR code (drawn in the test container: segno + Pillow are in the image)."""
    import base64
    code = ("import base64, io, segno\nfrom PIL import Image\nq = segno.make(%r, micro=False)\nb = io.BytesIO()\n"
            "q.save(b, kind='png', scale=8, border=4)\nqr = Image.open(b).convert('L')\npage = Image.new('L', (1654, 2339), 255)\n"
            "page.paste(qr, (1200, 100))\no = io.BytesIO()\npage.save(o, 'PDF', resolution=200)\nprint(base64.b64encode(o.getvalue()).decode())") % text
    out = subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True, check=True)
    return base64.b64decode(out.stdout)


if OCR:
    q1 = upload(A, [("qr1.pdf", qr_pdf("ASN00042"), "application/pdf")]).json()["ids"][0]
    d = done(A, q1, 120)
    check(d and d["asn"] == 42 and d["auto"].get("asn") == "code", f"archive number read from the QR code ({d and (d['asn'], d['auto'])})")
    # 2.146.0 (#2452): another scan of the same code (other bytes: the same file would be a duplicate, not stored twice)
    q2 = upload(A, [("qr2.pdf", qr_pdf("ASN00042") + b"\n% another scan\n", "application/pdf")]).json()["ids"][0]
    d = done(A, q2, 120)
    check(d and d["asn"] is None, "the same number twice: not given again")
    check(ids_of(A, q="ASN00042") == [q1] and q1 in ids_of(A, q="42"), "search by the archive number")
r = A.patch(B + f"/api/docs/{D1}", json={"asn": "next"})
nxt = r.json().get("asn") if r.ok else None
check(r.ok and isinstance(nxt, int) and nxt >= 1, f"the next free number ({r.text[:100]})")
check(A.patch(B + f"/api/docs/{D2}", json={"asn": nxt}).status_code == 409, "a number in use: 409")
check(A.put(B + "/api/docs/settings", json={"ws": "private", "asn_prefix": "1x"}).status_code == 400, "prefix: a letter first")
check(A.put(B + "/api/docs/settings", json={"ws": "private", "asn_prefix": "ARC"}).json()["asn_prefix"] == "ARC", "own prefix")
check(D1 in ids_of(A, q=f"ARC{nxt:05d}"), "search with the own prefix")
A.put(B + "/api/docs/settings", json={"ws": "private", "asn_prefix": "ASN"})

# ---- task for the due date
r = A.post(B + f"/api/docs/{D1}/task")
check(r.status_code == 201, f"a task for the due date ({r.text[:120]})")
if r.ok:
    t = A.get(B + f"/api/tasks/{r.json()['task_id']}").json()
    check(str(t.get("due") or "").startswith("2026-09-30") and f"#docs/{D1}" in (t.get("notes") or t.get("content") or ""), f"task: due + link ({t.get('due')})")

# ---- workspace boundary (tenant-matrix: document)
r = upload(Bo, [("alpha.pdf", text_pdf(["Alpha Lieferant Rechnung", "Projekt Sonnenblume", "Summe 10,00 EUR"]), "application/pdf")], f"org:{ORG}")
check(r.status_code == 201, f"bob uploads into Alpha ({r.text[:120]})")
DA = r.json()["ids"][0]
done(Bo, DA)
check(DA not in (ids_of(Ca) or []), "carol (member) sees bob's document only when it is shared (the file store's rules)")
check(ids_of(Ca, q="sonnenblume") == [] and Ca.get(B + "/api/docs", params={"ws": f"org:{ORG}"}).json()["facets"]["senders"] == [],
      "carol: no search hit, no sender names of documents she cannot open")
check(doc(Da, DA).status_code == 404 and DA not in (ids_of(Da) or []), "dave (Beta) never sees Alpha's document")
check(ids_of(Da, q="sonnenblume") == [] and ids_of(Er, q="sonnenblume") == [], "search: nothing across the boundary")
check(doc(Bo, D1).status_code == 404 and D1 not in (ids_of(Bo) or []) and ids_of(Bo, q="haftpflicht") == [], "alice's private documents: not for bob")
check(Ca.put(B + "/api/docs/settings", json={"ws": f"org:{ORG}", "levels": {"sender": "off"}}).status_code == 403, "org settings: admins only")
check(Da.get(B + "/api/docs/settings", params={"ws": f"org:{ORG}"}).status_code == 404, "org settings: not for other organisations")
check(Bo.put(B + "/api/docs/settings", json={"ws": f"org:{ORG}", "levels": {"sender": "rules"}}).ok, "org settings: the admin")
check(upload(Da, [("x.pdf", text_pdf(["x"]), "application/pdf")], f"org:{ORG}").status_code == 404, "no upload into a foreign organisation")
# 2.48.0 review (S1): a member files into the organisation's marked documents folder (never a second "Dokumente (2)"),
# the document stays theirs; folders only as far as they see them
RA = Bo.get(B + "/api/docs/settings", params={"ws": f"org:{ORG}"}).json()["root_id"]
check(Bo.patch(B + f"/api/files/nodes/{RA}", json={"name": "Unterlagen"}).ok, "the admin renames the documents folder")
r = upload(Ca, [("carol.pdf", text_pdf(["Carol Beleg Kreidefabrik", "Datum 07.10.2026"]), "application/pdf")], f"org:{ORG}")
check(r.status_code == 201, f"carol (member) uploads into Alpha ({r.text[:120]})")
DC = r.json()["ids"][0] if r.ok else 0
dc = done(Ca, DC)
check(dc and dc["parent_id"] == RA, f"carol's document lies in Alpha's documents folder ({dc and dc['parent_id']} vs {RA})")
check(not dbx("SELECT 1 FROM fs_nodes WHERE org_id=? AND parent_id IS NULL AND id<>?", (ORG, RA)), "no second documents folder")
check(dbx("SELECT owner_id FROM fs_nodes WHERE id=?", (DC,))[0][0] == CAROL, "the document stays carol's")
check(DC in (ids_of(Bo) or []) and DC in (ids_of(Ca) or []) and DA not in (ids_of(Ca) or []), "bob (admin) sees it; carol still not bob's")
fr = Bo.post(B + "/api/files/folders", json={"name": "Belege", "parent_id": RA}).json().get("id")
check(Bo.patch(B + f"/api/docs/{DC}", json={"folder": fr}).ok and doc(Ca, DC).ok and (doc(Ca, DC).json()["folder"] or {}).get("id") == fr,
      "the admin sorts carol's document into a folder of the documents folder; it stays hers")
check([f["id"] for f in Ca.get(B + "/api/docs/settings", params={"ws": f"org:{ORG}"}).json()["folders"]] == [] and
      fr in [f["id"] for f in Bo.get(B + "/api/docs/settings", params={"ws": f"org:{ORG}"}).json()["folders"]],
      "settings: carol sees no folder she cannot open (L4), bob sees it")
check(Ca.patch(B + f"/api/docs/{DC}", json={"folder": "Privatkram"}).status_code == 400 and
      not dbx("SELECT 1 FROM fs_nodes WHERE name='Privatkram'"), "carol makes no folder in bob's documents folder")
check(Ca.post(B + "/api/files/folders", json={"name": "X", "parent_id": RA}).status_code in (403, 404), "members add files there, not folders")
ws_rows = {x[0] for x in dbx("SELECT DISTINCT ws FROM doc_meta")}
check(ws_rows == {"u1", f"o{ORG}"}, f"documents keep their workspace ({ws_rows})")
check(dbx("SELECT org_id FROM fs_nodes WHERE id=?", (DA,))[0][0] == ORG and dbx("SELECT org_id FROM fs_nodes WHERE id=?", (D1,))[0][0] is None,
      "never moved into another workspace")

# ---- the organisation export holds the documents decrypted (not the models, not the word index, no mail token)
r = Bo.post(B + f"/api/orgs/{ORG}/export")
if r.status_code == 202:
    j = until(lambda: (lambda x: x if x.get("state") != "running" else None)(Bo.get(B + f"/api/orgs/{ORG}/export").json()), 120)
    arc = Bo.get(B + f"/api/orgs/{ORG}/export/file").content
    rk = Bo.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
    import tempfile
    import zipfile
    tmp = tempfile.mkdtemp(prefix="p248b-")
    open(os.path.join(tmp, "a.kalmido-export"), "wb").write(arc)
    out = subprocess.run([sys.executable, os.path.join(N, "..", "tools", "kalmido_export_decrypt.py"), os.path.join(tmp, "a.kalmido-export"),
                          "-o", os.path.join(tmp, "o.zip")], input=rk + "\n", capture_output=True, text=True, timeout=300)
    check(out.returncode == 0, f"export opens ({out.stderr[:200]})")
    if out.returncode == 0:
        z = zipfile.ZipFile(os.path.join(tmp, "o.zip"))
        names = set(z.namelist())
        meta = [x for x in names if x.endswith("documents/meta.json")]
        body = z.read(meta[0]).decode() if meta else ""
        check(meta and "Sonnenblume" in body and "kenc1:" not in body, "export: the documents with their text in plain")
        check(not any("doc_models" in x or "doc_words" in x or "documents/mail" in x for x in names), "export: no models, no word index, no mail token")
else:
    check(False, f"org export could not start ({r.status_code} {r.text[:120]})")

# ---- agents: only with a share
check(AGS.get(B + "/api/v1/documents").ok and D1 not in [x["id"] for x in AGS.get(B + "/api/v1/documents").json()["data"]], "agent: nothing unshared")
check(AGS.get(B + f"/api/v1/documents/{D1}").status_code == 404, "agent: 404 without a share")
root = A.get(B + "/api/docs/settings", params={"ws": "private"}).json()["root_id"]
r = A.post(B + f"/api/files/nodes/{root}/shares", json={"agent_id": PAG, "role": "view"})
check(r.status_code == 201, f"share the documents folder with the agent (view) ({r.text[:120]})")
r = AGS.get(B + f"/api/v1/documents/{D1}")
check(r.ok and "Haftpflicht" in r.json().get("text", ""), f"agent reads a shared document ({r.status_code})")
check(AGS.patch(B + f"/api/v1/documents/{D1}", json={"sender": "X"}).status_code in (403, 404), "agent with view cannot set fields")
check(dbx("SELECT 1 FROM fs_log WHERE node_id=? AND agent=1", (D1,)), "agent access in the history")
sid = dbx("SELECT id FROM fs_shares WHERE node_id=? AND agent_id=?", (root, PAG))[0][0]
check(A.patch(B + f"/api/files/shares/{sid}", json={"role": "edit"}).ok, "share -> edit")
r = AGS.patch(B + f"/api/v1/documents/{D2}", json={"sender": "Stadtwerke Musterstadt", "type": "Rechnung", "tags": ["Energie"]})
check(r.ok and r.json()["auto"].get("sender") == "agent" and r.json()["sender"]["name"] == "Stadtwerke Musterstadt", f"agent sets a field ({r.text[:150]})")
check(r.ok and r.json()["suggest"].get("type", {}).get("by") == "agent" and r.json()["review"], "level agent: the agent's value is a suggestion")
check(AGS.patch(B + f"/api/v1/documents/{D2}", json={"folder": 1}).status_code == 400, "agents never move documents")

# ---- inbox folder
fid = A.post(B + "/api/files/folders", json={"name": "Eingang", "parent_id": root}).json().get("id")
r = A.post(B + "/api/files/upload", data={"parent_id": str(fid)}, files={"file": ("inbox.pdf", text_pdf(["Eingang Brief", "Datum 05.10.2026"]), "application/pdf")})
check(r.status_code == 201, f"a file into Dokumente/Eingang ({r.text[:120]})")
inb = r.json()["items"][0]["id"] if r.ok else 0
d = until(lambda: (lambda x: x.json() if x.ok and x.json()["state"] == "done" else None)(doc(A, inb)), 60)
check(d and d["date"] == "2026-10-05", f"the inbox file became a document ({d and d['state']})")
check(d and d["parent_id"] == root, "recognised: it moves on into the documents folder")

# ---- forwarding address
r = A.post(B + "/api/docs/mail", json={"ws": "private"})
check(r.ok and "+d" in r.json()["address"], f"a forwarding address ({r.text[:120]})")
if r.ok:
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "post@example.com", r.json()["address"], "Fwd: Rechnung", "<doc-mail-1@example.com>"
    m.set_content("see attachment")
    m.add_attachment(text_pdf(["Mailversand Rechnung", "Datum 06.10.2026"]), maintype="application", subtype="pdf", filename="mailed.pdf")
    open(os.path.join(DATA, "mail", "in", "1.eml"), "wb").write(bytes(m))
    A.post(B + "/api/admin/mail/poll")
    got = until(lambda: dbx("SELECT node_id FROM doc_meta WHERE source='mail'"), 40)
    check(bool(got), "the mail's PDF became a document")
    check(not dbx("SELECT 1 FROM tasks WHERE title LIKE '%Rechnung%' AND tt_id LIKE 'mail:%'"), "no task from a document mail")

# ---- trash + restore (the file store's routes)
check(A.delete(B + f"/api/files/nodes/{D1}").ok and D1 not in ids_of(A), "deleted: out of the list")
check(A.post(B + f"/api/files/nodes/{D1}/restore").ok and D1 in ids_of(A), "restored: back")

# ---- rollback: only new tables and columns
legacy = dbx("SELECT table_name FROM information_schema.columns WHERE table_schema=current_schema() AND column_name='task_id' AND table_name='doc_meta'")
check(bool(legacy), "doc_meta.task_id is a new column of a new table")

print(f"p248_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
