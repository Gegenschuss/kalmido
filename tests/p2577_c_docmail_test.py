#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.577.0 C (#4466) API tests: named document addresses with a target folder and tags. Own container (start.sh with the
mail input switched on + the IMAP stub); the mails are handed to docs_mail_import inside the container. Invented names,
addresses (@example.com / example.test) and files only (every PDF is made here).
freelancer-matrix: files
 - a person without an organisation: the general address ("General", POST /api/docs/mail) and a named one ("Kontoauszuege",
   folder + two tags); a mail to the named one lands in its folder with its tags, never sorted by area; the general one
   still lands in the documents folder; the settings' general address stays the general one
 - wrong input: no name, an unknown field, tags not a list of texts, a folder of somebody else / outside the documents -> 400
 - switched off (PATCH active false) -> the mail is refused (0), nothing filed; on again -> filed; a stale expect_updated_at -> 409
   with the current state; renew -> the old address is no document address any more, the new one files; the hourly budget
   is counted on the named row (not the general one)
 - the target folder in the trash -> the documents folder, tagged "Target folder unavailable"; the settings mark it (ok false)
 - renewing / turning off the general address keeps the named ones
 - an organisation (tenant-matrix: document): carol's named address of Alpha, a folder of bob she cannot edit -> 400; the
   folder shared with her (edit) files there; bob ends the share -> Alpha's documents folder with the hint; frida sees, changes,
   renews and deletes nothing of it (404) and gets 404 on Alpha's list; carol out of Alpha -> nothing filed
 - an agent token: 403; a support session may not write the route (supportgrant.py sga_may_write)
usage: p2577_c_docmail_test.py <datadir>      (a fresh container; P2577C_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import base64
import email.message
import json
import os
import shutil
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, CT, DATA, check, sess, until  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402

MAILENV = {"KALMIDO_MAIL_ADDRESS": "tasks@example.test", "KALMIDO_IMAP_HOST": "127.0.0.1", "KALMIDO_IMAP_PORT": "1143",
           "KALMIDO_IMAP_SSL": "0", "KALMIDO_IMAP_USER": "kalmido", "KALMIDO_IMAP_PASSWORD": "secret", "KALMIDO_IMAP_INTERVAL": "600",
           "KALMIDO_DOCS_SCAN_S": "2"}
if kt.fresh(env=MAILENV, prefix="P2577C"):
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
A = kt.setup()
MA = "/api/docs/mail-addresses"


def py(code):
    """Runs code inside the test container (the app's modules importable) -> the last JSON line it printed."""
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=300)
    if r.returncode:
        print("PY FAILED:", r.stdout[-2000:], r.stderr[-3000:], flush=True)
    for ln in reversed((r.stdout or "").splitlines()):
        if ln.startswith("{"):
            return json.loads(ln)
    return {}


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


IMPORT = r'''
import base64, email, email.policy, json, app
from kalmido.core.db import connect
from kalmido.docs import ingest as I
I.docs_kick = lambda: None  # the server's queue recognises them (this process ends at once)
raw = base64.b64decode(%r)
c = connect()
try:
    print(json.dumps({"nid": I.docs_mail_import(c, email.message_from_bytes(raw, policy=email.policy.default), raw)}))
finally:
    c.close()
'''
SEQ = [0]


def deliver(to, text="Kontoauszug"):
    """A mail with one PDF attached to `to` -> what docs_mail_import returned (None = no document address, 0 = refused)."""
    SEQ[0] += 1
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "bank@example.com", to, f"{text} {SEQ[0]}", f"<p2577c-{SEQ[0]}@example.com>"
    m.set_content("Anbei.")
    m.add_attachment(text_pdf(["Beispielbank AG", f"{text} Nr. {SEQ[0]}", "Kontostand 1.234,56 EUR"]), maintype="application",
                     subtype="pdf", filename=f"auszug-{SEQ[0]}.pdf")
    return py(IMPORT % base64.b64encode(bytes(m)).decode()).get("nid", "error")


def node(nid):
    r = kt.dbx("SELECT parent_id, org_id, owner_id FROM fs_nodes WHERE id=?", (nid,))
    return tuple(r[0]) if r else None


def tags(s, nid, secs=90):
    """The tag names of document nid once recognised (GET /api/docs/<id>), or None."""
    def one():
        r = s.get(B + f"/api/docs/{nid}")
        return r.json() if r.ok and r.json()["state"] in ("done", "failed") else None
    d = until(one, secs)
    return sorted(t["name"] for t in (d or {}).get("tags") or []) if d else None


def first_doc(s, ws):
    r = s.post(B + "/api/docs", files={"files": ("start.txt", b"Start Beispiel", "text/plain")}, data={"ws": ws})
    assert r.ok, r.text
    return s.get(B + f"/api/docs/settings?ws={ws}").json()["root_id"]


def folder(s, name, parent):
    r = s.post(B + "/api/files/folders", json={"name": name, "parent_id": parent})
    assert r.ok, r.text
    return r.json()["id"]


def named(s, ws="private"):
    r = s.get(B + f"/api/docs/mail-addresses?ws={ws}")
    return r.json()["addresses"] if r.ok else None


# ---- setup: alice (instance admin), Alpha = bob (admin) + carol (member), frida without an organisation
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG), "setup: carol joins Alpha")
FRIDA, Fr = freelancer(B, A)
Ca = sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "files,docs,comments,collab"})

# ==== a person without an organisation (freelancer-matrix: files)
j = Fr.get(B + "/api/docs/mail-addresses?ws=private").json()
check(j.get("enabled") is True and j.get("addresses") == [] and j.get("max") == 20, f"frida: mail input on, no address yet {j}")
GEN = Fr.post(B + "/api/docs/mail", json={"ws": "private"}).json()["address"]
ROOT = first_doc(Fr, "private")
FOLD = folder(Fr, "Kontoauszuege", ROOT)
r = Fr.post(B + "/api/docs/mail-addresses", json={"ws": "private", "name": "Kontoauszuege", "target_folder": FOLD, "tags": ["Bank", "Konto", "bank"]})
check(r.status_code == 201 and r.json().get("target") == "Kontoauszuege" and r.json().get("tags") == ["Bank", "Konto"] and r.json().get("active") is True,
      f"frida makes a named address (folder, tags; a tag twice once) {r.status_code} {r.text[:300]}")
AD = r.json()
AID, ADDR = AD.get("id", "x"), AD.get("address", "")
check(ADDR.startswith("tasks+d") and ADDR.endswith("@example.test") and ADDR != GEN, f"the same plus address scheme, its own token {ADDR}")
lst = named(Fr)
check([a["id"] for a in lst] == ["general", AID] and lst[0]["name"] == "General" and lst[0]["general"] is True and lst[0]["address"] == GEN,
      f"the list: the general one first ('General'), then the named one {lst}")
check(Fr.get(B + "/api/docs/settings?ws=private").json()["mail"]["address"] == GEN, "the documents settings still name the general address")
# wrong input
check(Fr.post(B + "/api/docs/mail-addresses", json={"ws": "private", "name": " "}).status_code == 400, "no name: 400")
check(Fr.post(B + "/api/docs/mail-addresses", json={"ws": "private", "name": "X", "colour": "red"}).status_code == 400, "an unknown field: 400")
check(Fr.post(B + "/api/docs/mail-addresses", json={"ws": "private", "name": "X", "tags": [1, 2]}).status_code == 400, "tags not texts: 400")
check(Fr.post(B + "/api/docs/mail-addresses", json={"ws": "private", "name": "X", "target_folder": "7"}).status_code == 400, "a folder id as text: 400")
OUTSIDE = folder(Fr, "Privat ausserhalb", None)
check(Fr.post(B + "/api/docs/mail-addresses", json={"ws": "private", "name": "X", "target_folder": OUTSIDE}).status_code == 400, "a folder outside the documents: 400")

# a mail to the named address: its folder, its tags, no area sorting
D1 = deliver(ADDR)
check(isinstance(D1, int) and D1 > 0 and node(D1) == (FOLD, None, FRIDA), f"the mail lands in frida's folder Kontoauszuege {D1} {D1 and node(D1)}")
check(kt.dbx("SELECT area_sort FROM doc_meta WHERE node_id=?", (D1,)) == [("",)], "#4433: a named address is never sorted by area")
check(tags(Fr, D1) == ["Bank", "Konto"], f"with the address's tags {tags(Fr, D1, 5)}")
check(kt.dbx("SELECT parent_id FROM fs_nodes WHERE id=?", (D1,)) == [(FOLD,)], "the recognition leaves it in the folder")
D0 = deliver(GEN, "Brief")
check(isinstance(D0, int) and D0 > 0 and node(D0)[0] == ROOT, f"the general address: the documents folder as before {D0}")

# off / on, the version check
r = Fr.patch(B + f"/api/docs/mail-addresses/{AID}", json={"active": False, "expect_updated_at": AD["updated_at"]})
check(r.ok and r.json()["active"] is False and r.json()["note"], f"switched off {r.status_code} {r.text[:200]}")
OFF_AT = r.json().get("updated_at")
n0 = kt.dbx("SELECT COUNT(*) FROM fs_nodes WHERE parent_id=?", (FOLD,))[0][0]
check(deliver(ADDR) == 0, "a switched-off address refuses the mail (0: known, nothing filed)")
check(kt.dbx("SELECT COUNT(*) FROM fs_nodes WHERE parent_id=?", (FOLD,))[0][0] == n0, "nothing filed")
r = Fr.patch(B + f"/api/docs/mail-addresses/{AID}", json={"name": "Alt", "expect_updated_at": AD["updated_at"]})
check(r.status_code == 409 and (r.json().get("address") or {}).get("active") is False, f"a stale version: 409 with the current state {r.status_code} {r.text[:200]}")
check(Fr.patch(B + f"/api/docs/mail-addresses/{AID}", json={"active": "yes"}).status_code == 400, "active must be true / false")
r = Fr.patch(B + f"/api/docs/mail-addresses/{AID}", json={"active": True, "expect_updated_at": OFF_AT})
check(r.ok and r.json()["active"] is True, "on again")
D2 = deliver(ADDR)
check(isinstance(D2, int) and D2 > 0 and node(D2)[0] == FOLD, "on again: filed into the folder")

# renew: the old address is gone at once
r = Fr.post(B + f"/api/docs/mail-addresses/{AID}/renew", json={})
NEW = r.json().get("address", "") if r.ok else ""
check(r.ok and NEW and NEW != ADDR and r.json()["target"] == "Kontoauszuege" and r.json()["tags"] == ["Bank", "Konto"],
      f"renewed: a new address, folder and tags stay {r.text[:200]}")
check(deliver(ADDR) is None, "the old address is no document address any more")
D3 = deliver(NEW)
check(isinstance(D3, int) and D3 > 0 and node(D3)[0] == FOLD, "the new address files")
# the hourly budget counts on the named row
TOK = NEW.split("+", 1)[1].split("@", 1)[0]
GTOK = GEN.split("+", 1)[1].split("@", 1)[0]
j = py(r'''
import json, app
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.docs.maillink import ml_budget
c = connect()
with system_ctx(c):
    ml_budget(c, %r, "eml", 3)
    rows = [[r[0], r[1]] for r in c.execute("SELECT token, hits_eml FROM doc_mail WHERE token IN (?, ?)", (%r, %r)).fetchall()]
c.commit()
print(json.dumps({"rows": rows}))
c.close()
''' % (TOK, TOK, GTOK))
check(sorted(j.get("rows") or []) == sorted([[TOK, 3], [GTOK, 0]]), f"rate counter hits_* per address {j}")

# the general address renewed / turned off: the named ones stay
check(Fr.post(B + "/api/docs/mail", json={"ws": "private"}).ok and AID in [a["id"] for a in named(Fr)], "renewing the general one keeps the named one")
check(Fr.delete(B + "/api/docs/mail?ws=private").ok and [a["id"] for a in named(Fr)] == [AID], "turning the general one off keeps the named one")

# the target folder in the trash: into the documents folder, with the hint
check(Fr.delete(B + f"/api/files/nodes/{FOLD}").ok, "setup: frida moves Kontoauszuege to the trash")
D4 = deliver(NEW)
check(isinstance(D4, int) and D4 > 0 and node(D4)[0] == ROOT, f"the folder is gone: the documents folder instead {D4} {D4 and node(D4)}")
check(tags(Fr, D4) == ["Bank", "Konto", "Target folder unavailable"], f"tagged with the hint {tags(Fr, D4, 5)}")
a = next((x for x in named(Fr) if x["id"] == AID), {})
check(a.get("ok") is False and "no longer open" in (a.get("note") or ""), f"the settings mark the address {a}")
r = Fr.patch(B + f"/api/docs/mail-addresses/{AID}", json={"target_folder": None})
check(r.ok and r.json()["ok"] is True and r.json()["target"] == "", "a new folder choice (the documents folder) clears it")

# ==== an organisation (tenant-matrix: document)
ORT = first_doc(Bo, f"org:{ORG}")
BF = folder(Bo, "Nur Bob", ORT)
check(Fr.post(B + "/api/docs/mail-addresses", json={"ws": f"org:{ORG}", "name": "X"}).status_code == 404, "frida cannot make an address of Alpha")
check(Fr.get(B + f"/api/docs/mail-addresses?ws=org:{ORG}").status_code == 404, "frida gets 404 on Alpha's list")
r = Ca.post(B + "/api/docs/mail-addresses", json={"ws": f"org:{ORG}", "name": "Alpha Bank", "tags": "Alpha, Bank"})
check(r.status_code == 201 and r.json()["tags"] == ["Alpha", "Bank"], f"carol makes a named address of Alpha (tags as text) {r.text[:200]}")
CAID, CADDR = r.json().get("id", "y"), r.json().get("address", "")
CF = folder(Bo, "Carol Bank", ORT)
check(Bo.post(B + f"/api/files/nodes/{CF}/shares", json={"user_id": CAROL, "role": "edit"}).status_code == 201, "setup: bob shares Carol Bank with carol (edit)")
check(Ca.patch(B + f"/api/docs/mail-addresses/{CAID}", json={"target_folder": FOLD}).status_code == 400, "carol: frida's folder: 400")
r = Ca.patch(B + f"/api/docs/mail-addresses/{CAID}", json={"target_folder": BF})
check(r.status_code == 400, f"carol: bob's folder she cannot edit: 400 ({r.status_code})")
r = Ca.patch(B + f"/api/docs/mail-addresses/{CAID}", json={"target_folder": CF})
check(r.ok and r.json()["target"] == "Carol Bank", f"carol: the folder shared with her in Alpha {r.text[:200]}")
D5 = deliver(CADDR)
check(isinstance(D5, int) and D5 > 0 and node(D5)[:2] == (CF, ORG), f"the mail lands in Alpha's folder Carol Bank {D5} {D5 and node(D5)}")
check(tags(Ca, D5) == ["Alpha", "Bank"], "with the tags")
check(CAID not in [a["id"] for a in named(Fr)] and [a["id"] for a in named(Ca)] == [], "listed only in Alpha's settings of carol")
check(Fr.patch(B + f"/api/docs/mail-addresses/{CAID}", json={"name": "Weg"}).status_code == 404, "frida cannot change carol's address")
check(Fr.post(B + f"/api/docs/mail-addresses/{CAID}/renew", json={}).status_code == 404, "nor renew it")
check(Fr.delete(B + f"/api/docs/mail-addresses/{CAID}").status_code == 404, "nor delete it")
check(Bo.patch(B + f"/api/docs/mail-addresses/{CAID}", json={"name": "Weg"}).status_code == 404, "not even Alpha's admin (it is carol's)")
# the right on the folder lost after it was set (bob ends the share): Alpha's documents folder with the hint
SID = (kt.dbx("SELECT id FROM fs_shares WHERE node_id=? AND user_id=?", (CF, CAROL)) or [[0]])[0][0]
check(Bo.delete(B + f"/api/files/shares/{SID}").ok, "setup: bob ends the share")
D6 = deliver(CADDR)
check(isinstance(D6, int) and D6 > 0 and node(D6)[:2] == (ORT, ORG), f"no right on the folder at delivery: Alpha's documents folder {D6} {D6 and node(D6)}")
check(tags(Ca, D6) == ["Alpha", "Bank", "Target folder unavailable"], "tagged with the hint")
a = next((x for x in named(Ca, f"org:{ORG}") if x["id"] == CAID), {})
check(a.get("ok") is False, f"carol's settings mark the address {a}")
check(Bo.delete(B + f"/api/orgs/{ORG}/members/{CAROL}").ok, "setup: bob takes carol out of Alpha")
check(deliver(CADDR) == 0, "carol out of Alpha: the mail is refused")
check(Ca.get(B + f"/api/docs/mail-addresses?ws=org:{ORG}").status_code == 404 and Ca.patch(B + f"/api/docs/mail-addresses/{CAID}", json={"name": "X"}).status_code == 404,
      "and she reaches the address no more")

# ---- agents and support sessions never
r = Fr.post(B + "/api/agents", json={"name": "Postbot"})
tok = (r.json().get("token") or "") if r.ok else ""
if tok:
    r = requests.get(B + "/api/docs/mail-addresses?ws=private", headers={"Authorization": "Bearer " + tok})
    check(r.status_code in (401, 403), f"an agent token: refused ({r.status_code})")
j = py("import json, app\nfrom kalmido.accounts.supportgrant import sga_may_write\n"
       f"print(json.dumps({{'w': [sga_may_write('{MA}'), sga_may_write('{MA}/a1/renew'), sga_may_write('/api/docs/1/tags')]}}))")
check(j.get("w") == [False, False, True], f"a support session writes no address (contents yes) {j}")

# ---- delete
check(Fr.delete(B + f"/api/docs/mail-addresses/{AID}").ok and [a["id"] for a in named(Fr)] == [], "frida deletes her named address")
check(deliver(NEW) is None, "deleted: no document address any more")

sys.exit(kt.done("p2577_c_docmail"))
