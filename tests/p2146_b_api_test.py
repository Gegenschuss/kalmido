#!/usr/bin/env python3
"""2.146.0 API tests, part B (#2452 #2453 #2454): receipts -- duplicates, several files / a ZIP / winmail.dat, HEIC photos.
Own container (start.sh, org encryption on, the IMAP stub for the mail input). Invented companies, figures and files only
(every PDF, picture, ZIP and winmail.dat is made here). freelancer-matrix: files  tenant-matrix: document
 - the same file: a PDF uploaded twice is not stored again (dups -> the first one), in another workspace / of another
   person it is a new document, a document from before 2.146 (no raw_sha) is found by its stored version, one in the trash
   is no duplicate any more
 - ZIP (unzip=1, the receipt button): PDFs / pictures inside become documents (no path in the name), other types, nested
   ZIPs and the packing system's hidden files are left out (named in errors), more than 100 files: 400 with a text; without
   unzip a ZIP stays one document as before; a broken ZIP: a message, no 500
 - winmail.dat (TNEF, written here): its PDF / picture become documents (a short name gets its type from the content); a
   broken one: a message
 - the same invoice: same supplier + invoice number -> duplicate_of (the older one), same supplier + amount + date too,
   another supplier with the same amount / date not; "nodup" removes the warning and keeps it after a new recognition
   run, "dup" brings it back; another organisation 404; the DATEV batch of the personal office leaves the duplicate out
   (hint "dups"), ?dups=1 takes it
 - mail to the document address: a ZIP attachment unpacked, the same PDF twice in one mail and again in a second mail
   stays one document
 - HEIC (a 640x240 picture with two text lines drawn with Pillow and encoded with libheif's heif-enc at quality 80, 2.6 KB,
   embedded below; no photo): recognised (text from it), a preview made
usage: p2146_b_api_test.py <datadir>   (P2146B_NOSTART=1: the container with the IMAP stub runs already)"""
import base64
import email.message
import io
import os
import struct
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
MAILENV = ["-e", "KALMIDO_MAIL_ADDRESS=tasks@example.test", "-e", "KALMIDO_IMAP_HOST=127.0.0.1", "-e", "KALMIDO_IMAP_PORT=1143",
           "-e", "KALMIDO_IMAP_SSL=0", "-e", "KALMIDO_IMAP_USER=kalmido", "-e", "KALMIDO_IMAP_PASSWORD=secret", "-e", "KALMIDO_IMAP_INTERVAL=600",
           "-e", "KALMIDO_SECRET_KEY=" + base64.b64encode(os.urandom(32)).decode(), "-e", "KALMIDO_ORGCRYPT_DELAY=0", "-e", "KALMIDO_DOCS_SCAN_S=2"]
HEIC = base64.b64decode(
    "AAAAHGZ0eXBoZWljAAAAAG1pZjFoZWljbWlhZgAAAVdtZXRhAAAAAAAAACFoZGxyAAAAAAAAAABwaWN0AAAAAAAAAAAAAAAAAAAAACJpbG9jAAAAAERAAAEA"
    "AQAAAAABewABAAAAAAAACOkAAAAjaWluZgAAAAAAAQAAABVpbmZlAgAAAAABAABodmMxAAAAAA5waXRtAAAAAAABAAAA12lwcnAAAAC4aXBjbwAAAHlodmND"
    "AQNwAAAAAAAAAAAAP/AA/P34+AAADwNgAAEAGEABDAH//wNwAAADAJAAAAMAAAMAP7oCQGEAAQAsQgEBA3AAAAMAkAAAAwAAAwA/oAUCA8WW6kkprm4CGgwI"
    "AAADAMgAAAMACEBiAAEAB0QBwXKwYkAAAAATY29scm5jbHgAAQANAAaAAAAAFGlzcGUAAAAAAAACgAAAAPAAAAAQcGl4aQAAAAADCAgIAAAAF2lwbWEAAAAA"
    "AAAAAQABBIECAwQAAAjxbWRhdAAACOUoAa8E8guBgIJAQONGHZOrCv+QU1SQZGYcJqFt0FyQXbx/N5/K9cnh+76dnnfinyOD9T+g/c9ty3e5Ddr/olDl4LBN"
    "9sX4R65czAdwSAWzEjmmsDK0ZQzgjQKPB/oTuU2l49hWeaFCwT3Hjk2zlCegPP1Xmaps/CYtmni0ehQd/5KCD1gbv4j8Iv+ayehunyc9lSXC1MMb4fNqpvMU"
    "vM5qU53wH8t8WYlg7C+/OzKWJD0s+puZFSJ1OG94CfkZx5rL+qVT19luOcpFLxD+L+Na+st8gorV6ld4AAWzCJq87BUyhcwb00On7vp0z+gJmCt1RWnO85dI"
    "2p/xxt0gjJjUdtrspej+vGjp5WeuA64QSxh1re3PzU7gEaUZtEfibkBkU3CJlG/1vcMmEkDNhrZQY2DXeJKtKLOz2QYRIO//HoPp4kxVo7EV2mvnkEJaOfVO"
    "Ruw7YEebqEqoF9JyaGecG0XALmodQLTSJEZdr25MQJgwGXFfNYEn7Cw1PaxsDPiaQf1J5gLaydktMst4aJDHLRnF7qlhMEmvEAZ2uQ6jF8JVXCAmfAnnRJ3q"
    "EVMR8tpO16juQj4roJgRDgtKIzjbJDypiwNpZj1rxT1XwwnW8qWMosFCMCtPFCYDhZK1AJc7LvoLhyX3giO1+nnfK2Uo/FsAenVABEDwpCWkijWWutKnAWcy"
    "8i1Dyp11my6/Ff7auSN4I4kIuBg2LQUMX1v7DT4C3aVygvAWIj19mXBNBzN+K7IBmIjyM4gCr/fHqZnSkmq+gc4pXON+xVe4U40pLcH4Vf05ofgmD6Okk7/W"
    "M7A4Qjh/lRgYOwgkWL6Jpa6c9oe0c4p2AgxVqYd69zns9tR9sY/9Nw7OZpKMQctPYOPqNBjFAwxeWGF8zGvsfE8MK8NbN85liemsfqcvXJKTzK293zHnJ44L"
    "HsEdrONceVt+kCdyGaHQPEFfSboXYeLF+zi1FNyJ7fNvidmHOABfjI8SW6zJRf7qpJtW+dJoJeP3Nj3HWHQC35N8yQDzNFsnQX1EBQAqseoh5/PjVqcjwF8o"
    "ni80xcg2BuTNhN2A/7gY8E2f3e7F6+/BemPPFQx/d0us/mcAAHewyc4TL/ez8fFH1JpxVK44HC7FaRtOIXXGA0AlO84r9AEmUhNsbv1e78b4VMo4yqaVE+5x"
    "2x1dtuKZSkeYAIMwMnwyg3AlvfcnlhYH/mxRY6fS5zUfQ0TCrz7UTmVwqeTC+WmIDU3XjbnXR0O24wnrw53jHpBv8GXeeogKqJYyphYcJFtjoZQVGhIbzQma"
    "IVHXL4edcxcjTqyAhB2aOTrbR58ttjBtouLzTe6CC9kQ2PRBykJd/9nFVV9GTmnOCcuy2cAARhIQAAADAAADAAADAAADAAADAAADAAADABxQPoRGA4WYAAAD"
    "AAADAAADAAADAAADAAADAAADAAADADygKXy/zvcs+5rP02CisecVhd+XMxMFPSGuxSuqJZQtmXxZYh0by9AIha1hFfaSiWMkIyiVKGouulFVC9bRBQmBrrqz"
    "OzSCFGfOp7794kb/qZuAHXAKCpV4LiqW6cYuYEs941W+iior6q04gGQh+RvrG/vNiHzlm5y2QpI3jyDvhaZ10dk8uPj9/9awhOci2wPjIhDiyK8kYwmsdFNh"
    "cuJ4Or3v/KztBoN4qZe0CHjjEDdg21mBdhTufWoopYDTzfKlUnmu+e6J9QeAftmIb8ED7F1RaC+W1rz/1RiISW6tbh+csa95ZUai7gn0FAHhcMjtMhp6YZli"
    "ehnVLU+kCN+yJxskUHHQtCjUVxMjUwOn4FgAxLX/B2NLdr42M7ysEK6UF6Y2n0PXcgnl3Ek0oBonovkaD1XMP1YtDPU0O9a/m9DmgUBKBOxUEBE7a98Z1TfL"
    "q4PP32sMOFgKbHKaD0P3eLh5ZlSLoZ6C25X7o4pNsTKH0GXO8ZluAK4NgbQ2UXWfK6RsErJPtHGMm0C8xCwXKNnWghE1/oAOm00rKDa/0tj8OcOljgneJbLM"
    "3Pv5IH/5qaaP2HhD2TZzvjDCkegfRpzNwMMIQK5MGgKRdu7AX7/VuGAfoe3VTKFh+PMkPTFGG+bv8yWq2BYRQkie6yLT3XMfMUpKRlhzXNxqEIkNCIn0EgVF"
    "0fjtiUW2AuEgy0ATM69hkqwF03OtHZLEGtGJJrb2am7cQWFZ99VW3XErYcFv6QnsrwKFDTpAHW7SnQux2WSDyxZpbjTmxwoeaK+PM0wIsZTfQaL/f/g8fxX0"
    "tmX5uP73xBmB+a/QcPEwKlI6dsDlg5weecB8/1IkpZdGaZ0jOS5XBh/da9QjlgWYJ1D1dxG9Wg/91o7nUTO+Ca7ESypNfzC+pfdQ/6uPPThjMaz+eZOtwGpG"
    "9/5I4sAGUGzLgt+z8v5mEqSHVmPwyv6ucTu08Np6sK6SQP0C5UZQi3khp59BNU7BTspr0LP1WgJH5doQPCip85VQmrB/AMoSl4xmtRUuTewo6dJCKQcbmwBc"
    "0XthSd7byblSlC6tym/ya6k4bFbTUTwLlO2eozPIcd2mWfaSzaP2sehNUtyHhmAjE+gffe/WyhIeNOQ/ZAfR40TFtfYnNxODR+vjcJtgqYNCdrInGON0WEAV"
    "8bo50ifXE0jUMXZF5GWSyqktB4pfHI7WjHqq4auiOHfpQDv/6ZQGYONyIQ+ywgrdnJCy+rSBhG0XaIOV5oTmu/WnAxHLaq1wjSPeLSY7Mu6oJOAQCBesVd0R"
    "IPNEeCo0AKbPWbd2yvXIUrfR+8iItIwvUjh0d7GepwTaRPBhKlUC1Z9wuiUpu8qENkiobGNlwG+JeJ6IuGQ6hdwqjxVV17n5BLkuDtpLZZSv/u+WOlYzCgTm"
    "juWlfqoxkRXnj1766/jXx1BSL2kLgHh7uv23NwEU0XX4gvUQZ3H9qHDWXtUsLK9MaoFGWP9zJUPD6aHhK+hruqpHTApMPiXmLuDNw3RLFXlABugBUABqAD3A"
    "NYBEAH0CTgAAAwAAAwAAAwAAAwAAAwAAAwAAAwAAAwAAAwAAAwAAAwAAAwAAAwAAKWA="
)


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
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


def jpeg(color):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(b, "JPEG")
    return b.getvalue()


def mkzip(entries):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
    return b.getvalue()


def tnef(atts):
    """A TNEF stream (winmail.dat) with these (title, bytes) attachments -- the attributes Outlook writes for them."""
    def attr(lvl, aid, data):
        return struct.pack("<BII", lvl, aid, len(data)) + data + struct.pack("<H", sum(data) & 0xFFFF)
    out = struct.pack("<IH", 0x223E9F78, 1) + attr(1, 0x00089006, struct.pack("<I", 0x00010000))
    for title, data in atts:
        out += attr(2, 0x00069002, b"\x01\x00\x00\x00\xff\xff\xff\xff" + b"\x00" * 6)
        out += attr(2, 0x00018010, title.encode("cp1252") + b"\x00")
        out += attr(2, 0x0006800F, data)
    return out


def up(s, files, ws="private", unzip=False):
    data = {"ws": ws}
    if unzip:
        data["unzip"] = "1"
    return s.post(B + "/api/docs", data=data, files=[("files", f) for f in files])


def doc(s, nid):
    r = s.get(B + f"/api/docs/{nid}")
    return r.json() if r.ok else None


def done(s, nid, secs=90):
    return until(lambda: (lambda d: d if d and d["state"] in ("done", "failed") else None)(doc(s, nid)), secs)


def names(s, ids):
    return sorted(doc(s, i)["name"] for i in ids)


def ndocs(ws):
    return dbx("SELECT COUNT(*) FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE d.ws=? AND n.deleted_at IS NULL", (ws,))[0][0]


if not os.environ.get("P2146B_NOSTART"):
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
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: files (private documents = the personal office's receipts)
WSF = f"u{FID}"

# ---- schema: three new columns, nothing renamed
cols = {r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_name='doc_meta' AND column_name IN ('raw_sha','dup_of','dup_ok')")}
check(cols == {"raw_sha", "dup_of", "dup_ok"}, f"doc_meta: raw_sha, dup_of, dup_ok added ({cols})")

# ---- #2452 the same file
P1 = text_pdf(["Rechnung Beispiel Papier GmbH", "Rechnungsnummer PP-1001", "Datum 02.10.2026", "Summe EUR 23,80"])
r = up(Fr, [("papier.pdf", P1, "application/pdf")])
check(r.status_code == 201 and len(r.json()["ids"]) == 1 and r.json().get("dups") == [], "first upload: a new document " + r.text[:200])
D1 = r.json()["ids"][0]
n0 = ndocs(WSF)
r = up(Fr, [("papier-nochmal.pdf", P1, "application/pdf")])
j = r.json()
check(r.status_code == 200 and j["ids"] == [] and j.get("dups") == [{"id": D1, "name": "papier-nochmal.pdf"}], f"the same bytes again: not stored, dups names the first {r.status_code} {j}")
check(ndocs(WSF) == n0, "no second document")
r = up(Fr, [("a.pdf", P1, "application/pdf"), ("b.pdf", text_pdf(["Etwas anderes"]), "application/pdf")])
check(r.status_code == 201 and len(r.json()["ids"]) == 1 and [d["id"] for d in r.json()["dups"]] == [D1], "a mixed upload: the new one stored, the old one named")
r = up(A, [("papier.pdf", P1, "application/pdf")], ws=f"org:{ORG}")
check(r.status_code == 201 and r.json()["ids"] and r.json()["ids"][0] != D1, "another workspace (an organisation): a document of its own")
DORG = r.json()["ids"][0]
r = up(Ca, [("papier.pdf", P1, "application/pdf")], ws="private")
check(r.status_code == 201 and r.json()["ids"][0] not in (D1, DORG), "another person's private space: a document of its own (nothing of frida's named)")
dbx("UPDATE doc_meta SET raw_sha='' WHERE node_id=?", (D1,), write=True)  # a document from before 2.146
r = up(Fr, [("alt.pdf", P1, "application/pdf")])
check(r.status_code == 200 and [d["id"] for d in r.json().get("dups", [])] == [D1], "a document from before 2.146: found by its stored version " + r.text[:160])
check(Fr.delete(B + f"/api/files/nodes/{D1}").ok, "the first one into the trash")
r = up(Fr, [("papier.pdf", P1, "application/pdf")])
check(r.status_code == 201 and r.json()["ids"] and r.json()["ids"][0] != D1, "one in the trash is no duplicate any more")
check(Fr.post(B + f"/api/files/nodes/{D1}/restore").ok, "restored")

# ---- #2453 ZIP
J1, J2 = jpeg("red"), jpeg("blue")
ZP = text_pdf(["Amazon Beispiel Rechnung", "Bestellung 1"])
Z = mkzip([("Rechnungen/bestellung-1.pdf", ZP), ("foto.JPG", J1), ("tief/unten/zweites.jpeg", J2), ("notiz.txt", b"nur Text"),
           ("innen.zip", mkzip([("x.pdf", text_pdf(["Verschachtelt"]))])), ("__MACOSX/Rechnungen/._bestellung-1.pdf", b"\x00\x05"),
           (".DS_Store", b"x"), ("leer/", b"")])
r = up(Fr, [("portal-download.zip", Z, "application/zip")], unzip=True)
j = r.json()
check(r.status_code == 201 and len(j["ids"]) == 3, f"ZIP: three documents {r.status_code} {j}")
if j.get("ids"):
    check(names(Fr, j["ids"]) == ["bestellung-1.pdf", "foto.JPG", "zweites.jpeg"], f"names without a path {names(Fr, j['ids'])}")
    check(doc(Fr, j["ids"][0])["mime"] == "application/pdf", "the PDF's type")
check(any("2" in e and "portal-download.zip" in e for e in j.get("errors", [])), f"the text file and the nested ZIP named as left out {j.get('errors')}")
r = up(Fr, [("portal-download.zip", Z, "application/zip")], unzip=True)
check(r.status_code == 200 and len(r.json().get("dups", [])) == 3 and not r.json()["ids"], "the same ZIP again: three duplicates, nothing new")
r = up(Fr, [("ablage.zip", mkzip([("eins.pdf", text_pdf(["Ablage eins"]))]), "application/zip")])
check(r.status_code == 201 and names(Fr, r.json()["ids"]) == ["ablage.zip"], "without unzip (the documents area): the ZIP stays one document")
big = mkzip([(f"r{i}.pdf", text_pdf([f"Beleg {i}"])) for i in range(101)])
r = up(Fr, [("viele.zip", big, "application/zip")], unzip=True)
check(r.status_code == 400 and any("100" in e for e in r.json().get("errors", [])), f"more than 100 files: 400 with a text {r.status_code} {r.text[:200]}")
r = up(Fr, [("kaputt.zip", b"PK\x03\x04 kaputt", "application/zip")], unzip=True)
check(r.status_code == 400 and r.json().get("errors"), f"a broken ZIP: a message, no 500 {r.status_code}")
r = up(Fr, [("evil.zip", mkzip([("../../etc/x.pdf", text_pdf(["Pfad"]))]), "application/zip")], unzip=True)
check(r.status_code == 201 and names(Fr, r.json()["ids"]) == ["x.pdf"], "a path in an entry's name: only the file name")

# ---- #2453 winmail.dat
TP = text_pdf(["Outlook Beispiel Rechnung", "Nr. OUT-77"])
r = up(Fr, [("winmail.dat", tnef([("RECHNU~1.PDF", TP), ("ATT00001", jpeg("green")), ("text.txt", b"x")]),
             "application/ms-tnef")], unzip=True)
j = r.json()
check(r.status_code == 201 and len(j["ids"]) == 2, f"winmail.dat: the PDF and the picture {r.status_code} {j}")
if j.get("ids"):
    check(names(Fr, j["ids"]) == ["ATT00001.jpg", "RECHNU~1.PDF"], f"a short name gets its type from the content {names(Fr, j['ids'])}")
r = up(Fr, [("winmail.dat", b"\x78\x9f\x3e\x22\x01\x00" + b"\x02" * 20, "application/ms-tnef")], unzip=True)
check(r.status_code == 400 and any("winmail.dat" in e for e in r.json().get("errors", [])), f"a broken winmail.dat: a message {r.text[:200]}")

# ---- #2452 the same invoice (text documents are recognised like a PDF's text layer)
CRAFT = """Muster Bau GmbH · Werkstraße 12 · 54321 Beispielort
Rechnung
Rechnungs-Nr.: RE-2026-118
Datum: 06.10.2026
Arbeitszeit 4 Std.   240,00 €
Material              60,00 €
Nettobetrag          300,00 €
zzgl. 19 % MwSt.      57,00 €
Gesamtbetrag         357,00 €
USt-IdNr. DE123456789
"""
BAKE = """Bäckerei Musterkorn
Brotgasse 2
12345 Musterstadt
05.10.2026  08:12
2x Brötchen   1,20
1x Kaffee     2,50
Summe EUR     3,70
MwSt 7%  0,24
"""


def txt(s, name, text, ws="private"):
    r = up(s, [(name, text.encode(), "text/plain")], ws=ws)
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    d = done(s, nid)
    check(d and d["state"] == "done", f"{name} recognised ({d and d['state']})")
    return nid


T1 = txt(Fr, "bau-mail.txt", CRAFT)
T2 = txt(Fr, "bau-foto.txt", CRAFT + "\nFoto vom Handy\n")
d1, d2 = doc(Fr, T1), doc(Fr, T2)
check("duplicate_of" not in d1, "the older one is no duplicate")
check(d2.get("duplicate_of") == {"id": T1, "name": "bau-mail.txt"}, f"same supplier + invoice number: duplicate_of the older one {d2.get('duplicate_of')}")
check((d2.get("extracted") or {}).get("invoice_no") == "RE-2026-118", "the recognised values stay")
check(dbx("SELECT dup_of, dup_ok FROM doc_meta WHERE node_id=?", (T2,))[0] == (T1, 0), "stored: dup_of, dup_ok 0")
B1 = txt(Fr, "baecker-1.txt", BAKE)
B2 = txt(Fr, "baecker-2.txt", BAKE.replace("2x Brötchen   1,20\n1x Kaffee     2,50", "1x Kaffee     2,50\n2x Brötchen   1,20"))
check(doc(Fr, B2).get("duplicate_of", {}).get("id") == B1, f"same supplier + amount + date: duplicate {doc(Fr, B2).get('duplicate_of')}")
B3 = txt(Fr, "kiosk.txt", BAKE.replace("Bäckerei Musterkorn", "Kiosk Beispielecke").replace("Brotgasse 2", "Eckweg 1"))
check("duplicate_of" not in doc(Fr, B3), "another supplier with the same amount and date: no duplicate")
# rights
check(Ca.post(B + f"/api/docs/{T2}/extracted", json={"do": "nodup"}).status_code == 404, "another person: 404")
check(Fr.post(B + f"/api/docs/{T2}/extracted", json={"do": "nodup!"}).status_code == 400, "an unknown action: 400")

# DATEV of the personal office: the duplicate stays out unless asked for
O = "/api/office"
r = Fr.put(B + O + "/settings", json={"company": {"name": "Frida Beispiel"}, "currency": "EUR",
                                     "company_fields": {"name": "Frida Beispiel", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg", "country": "DE",
                                                        "tax_number": "12/345/67890"}})
check(r.ok, "personal office settings " + r.text[:160])
r = Fr.put(B + O + "/settings", json={"datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}})
check(r.ok, "DATEV numbers " + r.text[:160])
for nid in (T1, T2, B1, B2, B3):
    check(Fr.put(B + f"/api/docs/{nid}/receipt", json={"category": "Material", "vat_pct": "19", "keep": True}).ok, f"receipt {nid}")
P = "?from=2026-10-01&to=2026-10-31"


def batch(q):
    r = Fr.get(B + O + "/datev/extf" + q)
    assert r.ok, r.text
    rows = [ln.split(";") for ln in r.content.decode("cp1252").split("\r\n")[2:-1]]
    return {x[10].strip('"') for x in rows}


def hints(q):
    r = Fr.get(B + O + "/datev/extf" + q + "&check=1")
    assert r.ok, r.text
    return {h["key"]: h for h in r.json().get("hints", [])}


bel = batch(P)
check(f"B{T1}" in bel and f"B{T2}" not in bel and f"B{B1}" in bel and f"B{B2}" not in bel and f"B{B3}" in bel, f"DATEV: the duplicates left out {sorted(bel)}")
h = hints(P).get("dups") or {}
check(h.get("count") == 2 and sorted(h.get("ids") or []) == sorted([T2, B2]) and "not exported" in h.get("text", ""), f"the hint names them {h}")
bel = batch(P + "&dups=1")
check({f"B{T1}", f"B{T2}", f"B{B2}"} <= bel, f"?dups=1: exported too {sorted(bel)}")
check("are exported" in (hints(P + "&dups=1").get("dups") or {}).get("text", ""), "the hint says they are in")

# "no duplicate" -> gone, also after a new recognition run; "dup" brings it back
r = Fr.post(B + f"/api/docs/{T2}/extracted", json={"do": "nodup"})
check(r.ok and "duplicate_of" not in r.json()["doc"], "nodup: the warning goes " + r.text[:160])
check(f"B{T2}" in batch(P), "nodup: in the DATEV batch")
check(Fr.post(B + f"/api/docs/{T2}/redo").ok, "recognise again")
d = done(Fr, T2)
check(d and "duplicate_of" not in d and dbx("SELECT dup_ok FROM doc_meta WHERE node_id=?", (T2,))[0][0] == 1, "the decision stays after a new run")
r = Fr.post(B + f"/api/docs/{T2}/extracted", json={"do": "dup"})
check(r.ok and (r.json()["doc"].get("duplicate_of") or {}).get("id") == T1, "dup (undo): the warning is back " + r.text[:160])
# an edit by hand looks again: another amount on B2 -> no duplicate any more
r = Fr.patch(B + f"/api/docs/{B2}", json={"amount": "4.10"})
check(r.ok and "duplicate_of" not in doc(Fr, B2), "a corrected amount: no duplicate any more")
# the older one in the trash: the warning goes
check(Fr.delete(B + f"/api/files/nodes/{T1}").ok and "duplicate_of" not in doc(Fr, T2), "the older one in the trash: no warning")
check(f"B{T2}" in batch(P), "... and the newer one is exported")
check(Fr.post(B + f"/api/files/nodes/{T1}/restore").ok, "restored")

# an organisation: sealed values, the warning for its members, another organisation 404
O1 = txt(A, "org-bau-1.txt", CRAFT, ws=f"org:{ORG}")
O2 = txt(A, "org-bau-2.txt", CRAFT + "\nKopie\n", ws=f"org:{ORG}")
check((doc(A, O2).get("duplicate_of") or {}).get("id") == O1, "organisation: duplicate_of")
check(Ca.get(B + f"/api/docs/{O2}").status_code == 404, "another organisation: 404")
check((doc(Fr, T2).get("duplicate_of") or {}).get("id") == T1, "workspaces stay apart (frida's warning names her own document)")

# ---- mail to the document address: ZIP unpacked, the same PDF once
r = Fr.post(B + "/api/docs/mail", json={"ws": "private"})
check(r.ok and "+d" in r.json().get("address", ""), "a forwarding address " + r.text[:120])
if r.ok:
    ADDR = r.json()["address"]
    MP = text_pdf(["Mail Beispiel Rechnung", "Nr. MAIL-9"])
    before = ndocs(WSF)

    def mail(no, atts):
        m = email.message.EmailMessage()
        m["From"], m["To"], m["Subject"], m["Message-ID"] = "post@example.com", ADDR, "Fwd: Rechnungen", f"<doc-mail-{no}@example.com>"
        m.set_content("siehe Anhang")
        for name, data, mt, st in atts:
            m.add_attachment(data, maintype=mt, subtype=st, filename=name)
        open(os.path.join(DATA, "mail", "in", f"{no}.eml"), "wb").write(bytes(m))
        A.post(B + "/api/admin/mail/poll")

    mail(1, [("rechnungen.zip", mkzip([("mail-rechnung.pdf", MP), ("bild.jpg", jpeg("yellow")), ("liesmich.txt", b"x")]), "application", "zip"),
             ("mail-rechnung.pdf", MP, "application", "pdf"), ("winmail.dat", tnef([("SCAN.PDF", text_pdf(["Outlook Scan 3"]))]), "application", "ms-tnef")])
    got = until(lambda: ndocs(WSF) >= before + 3, 40)
    time.sleep(2)
    check(ndocs(WSF) == before + 3, f"mail: ZIP (PDF + picture) + winmail.dat PDF, the same PDF once ({ndocs(WSF) - before})")
    mail(2, [("nochmal.pdf", MP, "application", "pdf")])
    time.sleep(4)
    check(ndocs(WSF) == before + 3, "a second mail with the same PDF: linked, not stored again")
    check(not dbx("SELECT 1 FROM tasks WHERE title LIKE '%Rechnungen%' AND tt_id LIKE 'mail:%'"), "no task from a document mail")

# ---- #2454 HEIC
r = up(Fr, [("IMG_0001.HEIC", HEIC, "image/heic")])
check(r.status_code == 201, "HEIC upload " + r.text[:160])
if r.status_code == 201:
    HID = r.json()["ids"][0]
    d = done(Fr, HID, 120)
    check(d and d["state"] == "done" and not d["error"], f"HEIC recognised ({d and d['state']} {d and d['error']} {d and d.get('error_text')})")
    t = ((d or {}).get("text") or "").upper()
    check(any(w in t for w in ("4711", "SUMME", "KASSENBON", "42,00")), f"text read from the photo {t[:120]!r}")
    check(d and d["thumb"] and Fr.get(B + f"/api/docs/{HID}/thumb").content[:2] == b"\xff\xd8", "a preview (JPEG)")
    r = up(Fr, [("IMG_0001.HEIC", HEIC, "image/heic")])
    check(r.status_code == 200 and [x["id"] for x in r.json().get("dups", [])] == [HID], "the same photo again: a duplicate (before its metadata was cut)")

print(f"p2146_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
