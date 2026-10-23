#!/usr/bin/env python3
"""2.184.0 part A (#2579 #2628): the organisation export / import carries the correspondence and the documents' custom
fields; sent letters count as records to keep. Invented names only.
 - an organisation with a sent letter (answering a document, signed with a signature picture), a draft, a text block and
   two custom document fields (text + select with a value) -> exported -> imported into another organisation that already
   has a select field of the same name: letters readable, the link to the (new) document, the filed PDF on the new file,
   the text block and the signature, the text value, the select value on the target's option (the missing option added)
 - #2628: the sent letter (not the draft) counts in the retention info, the retention ZIP has letters/letters.csv and the
   PDF; the organisation's delete info keeps it by law
 - undo removes the letters, the made field and the values (the target's own field stays)
 - a person without any organisation imports the same export into the private space: letters in the personal office,
   fields in the private documents; the retention info of the person counts the sent letter
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2184A_NOSTART=1 = the server already runs like that).
usage: p2184_a_export_test.py <datadir>"""
# freelancer-matrix: office
# freelancer-matrix: own
# tenant-matrix: own
import base64
import hashlib
import io
import os
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
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs,contacts,files"
LT = "/api/office/letters"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)
        if len(FAILS) == 1:
            print(subprocess.run(["docker", "logs", "--tail", "80", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True).stdout[-8000:], flush=True)


def EH(email):
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def one(q, args=()):
    r = sql(q, args)
    return r[0] if r else None


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def ws(s, v):
    r = s.patch(B + "/api/settings", json={"workspace": v})
    assert r.ok, r.text


def doc(s, name, text, space):
    r = s.post(B + "/api/docs", data={"ws": space}, files=[("files", (name, text.encode("utf-8"), "text/plain"))])
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 90)
    return nid


def upload(s, data, name="alpha.kalmido-export"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid, secs=240):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def opened(s, data, rk):
    iid = upload(s, data)
    j = wait(s, iid)
    check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {j.get('error')}")
    check(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
    j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    return iid, j.get("preview") or {}


def run(s, iid, target, people=None):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": target, "people": people or {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    return wait(s, iid)


def fields(s, nid):
    return {f["name"]: f for f in s.get(B + f"/api/docs/{nid}").json().get("custom_fields") or []}


def zip_names(s, url):
    r = s.get(B + url)
    check(r.ok and r.content[:2] == b"PK", f"retention ZIP {url} {r.status_code}")
    try:
        return zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    except zipfile.BadZipFile:
        return []


if os.environ.get("P2184A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}"
               " -e KALMIDO_DOCS_SCAN_S=1")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Ablage", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Briefe", "admin_id": ALICE}).json()["id"]
GAM = A.post(B + "/api/admin/orgs", json={"name": "Gamma Ziel", "admin_id": ALICE}).json()["id"]
SP = f"org:{ORG}"

# ---------------------------------------------------------------- the organisation's correspondence + fields
ws(A, SP)
D1 = doc(A, "schreiben.txt", "Amt Beispiel\nDatum: 01.10.2026\nAktenzeichen: AZ-77\n", SP)
r = A.put(B + LT + "/profile", json={"greeting": "Beste Grüße", "name": "Alice Ablage",
                                     "image": "data:image/png;base64," + base64.b64encode(PNG).decode()})
check(r.ok, "setup: the signature with a picture " + r.text[:200])
r = A.post(B + "/api/office/letter-blocks", json={"name": "Widerspruch", "body": "Hiermit widerspreche ich fristgerecht."})
check(r.status_code == 201, "setup: a text block " + r.text[:200])
r = A.post(B + LT, json={"answers": D1})
check(r.status_code == 201, "setup: a letter answering the document " + r.text[:200])
L1 = r.json()["id"]
check(A.patch(B + f"{LT}/{L1}", json={"rcpt_name": "Amt Beispiel", "rcpt_address": "Amtsweg 1\n12345 Musterstadt",
                                       "subject": "Widerspruch AZ-77", "body": "Sehr geehrte Damen und Herren, ..."}).ok, "setup: the letter text")
r = A.post(B + f"{LT}/{L1}/sent", json={"channel": "post"})
check(r.ok, "setup: the letter is sent (its PDF filed) " + r.text[:200])
LD = A.post(B + LT, json={"subject": "Entwurf bleibt Entwurf"}).json()["id"]
row = one("SELECT node_id, status, sign_image FROM office_letters WHERE id=?", (L1,))
check(row and row[0] and row[1] == "sent", f"setup: sent with a filed PDF {row}")
LPDF = row[0] if row else 0
check(one("SELECT subject FROM office_letters WHERE id=?", (L1,))[0].startswith("kenc1:"), "setup: the subject is sealed at rest")
r = A.post(B + "/api/docs/fields", json={"ws": SP, "name": "Aktenzeichen", "type": "text"})
check(r.status_code == 201, "setup: a text field " + r.text[:200])
FT = r.json()["id"]
r = A.post(B + "/api/docs/fields", json={"ws": SP, "name": "Stand", "type": "select", "options": "Offen, Erledigt"})
check(r.status_code == 201, "setup: a select field " + r.text[:200])
FS = r.json()["id"]
OPT = {o["name"]: o["id"] for o in next(f for f in r.json()["fields"] if f["id"] == FS)["options"]}
r = A.patch(B + f"/api/docs/{D1}", json={"custom_fields": {str(FT): "AZ-77", str(FS): OPT["Erledigt"]}})
check(r.ok, "setup: the field values " + r.text[:200])
check(fields(A, D1).get("Stand", {}).get("label") == "Erledigt", "setup: the select value reads")

# ---------------------------------------------------------------- #2628: the retention info and ZIP of the organisation
ri = A.get(B + f"/api/retention/org/{ORG}").json()
check((ri.get("counts") or {}).get("letters") == 1, f"#2628: the sent letter counts, the draft not {ri.get('counts')}")
check("6 years" in (ri.get("note") or "") and (ri.get("years") or {}).get("letters") == 6, f"#2628: the note names sent letters 6 years {ri.get('note')}")
names = zip_names(A, f"/api/retention/org/{ORG}/export.zip")
check("letters/letters.csv" in names and any(n.startswith("letters/") and n.endswith(".pdf") for n in names),
      f"#2628: the retention ZIP has the letters' list and PDF {[n for n in names if n.startswith('letters/')]}")
di = A.get(B + f"/api/admin/orgs/{ORG}/delete-info").json()
check((di.get("kept") or {}).get("letters") == 1 and di.get("retain_until"), f"#2628: the delete info keeps the letter by law {di.get('kept')}")

# the target already has a select field "Stand" with one option (the import adds the missing one)
r = A.post(B + "/api/docs/fields", json={"ws": f"org:{GAM}", "name": "Stand", "type": "select", "options": "Offen"})
check(r.status_code == 201, "setup: the target's own select field " + r.text[:200])
GFS = r.json()["id"]

# ---------------------------------------------------------------- export -> import into the other organisation
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, "organisation export started " + r.text[:120])
until(lambda: A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running", 120)
OX = A.get(B + f"/api/orgs/{ORG}/export/file").content
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
check(OX[:13] == b"KALMIDO-ORGX\n" and RK, "organisation export + recovery key")
iid, pv = opened(A, OX, RK)
taken = {x.get("what") for x in pv.get("taken_areas") or []}
check("Letters" in taken, f"the preview names the letters {taken}")
nt = " ".join(str(x) for x in pv.get("not_taken") or [])
check("fields" not in nt.lower(), f"the custom fields are not named as skipped {nt}")
j = run(A, iid, GAM)
check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')} {(j.get('result') or {}).get('warnings')}")
IMP = (j.get("result") or {}).get("import_id")

ws(A, f"org:{GAM}")
gl = one("SELECT id, node_id, status, followup_task_id FROM office_letters WHERE org_id=? AND status='sent'", (GAM,))
check(gl is not None, "the sent letter came along")
GL = gl[0] if gl else 0
d = A.get(B + f"{LT}/{GL}").json()
check(d.get("subject") == "Widerspruch AZ-77" and "Amtsweg 1" in str(d.get("rcpt_address") or ""), f"the letter reads in the target {d.get('subject')}")
check(one("SELECT subject FROM office_letters WHERE id=?", (GL,))[0].startswith("kenc1:"), "the letter is sealed again at rest")
gnode = one("SELECT org_id FROM fs_nodes WHERE id=?", (gl[1] if gl else 0,))
check(gl and gl[1] and gl[1] != LPDF and gnode and gnode[0] == GAM, f"the filed PDF points at the new file {gl}")
check(sql("SELECT COUNT(*) FROM office_letters WHERE org_id=? AND status='draft'", (GAM,))[0][0] == 1, "the draft came along")
gd = one("SELECT n.id FROM fs_nodes n JOIN doc_meta m ON m.node_id=n.id WHERE n.org_id=? AND n.name='schreiben.txt'", (GAM,))
GD = gd[0] if gd else 0
lk = sql("SELECT node_id, kind FROM office_letter_links WHERE letter_id=?", (GL,))
check([tuple(x) for x in lk] == [(GD, "answers")], f"the letter answers the new document {lk} {GD}")
bl = A.get(B + "/api/office/letter-blocks").json()
bl = bl.get("blocks", bl) if isinstance(bl, dict) else bl
check(any(b.get("name") == "Widerspruch" and "fristgerecht" in str(b.get("body")) for b in bl or []), f"the text block came along {bl}")
pr = A.get(B + LT + "/profile").json()
check(pr.get("name") == "Alice Ablage" and pr.get("greeting") == "Beste Grüße", f"the signature came along {pr}")
check(one("SELECT image FROM office_letter_profiles WHERE org_id=? AND user_id=?", (GAM, ALICE))[0].startswith("kenc1:"),
      "the signature picture is sealed again")
fv = fields(A, GD)
check(fv.get("Aktenzeichen", {}).get("value") == "AZ-77", f"the text value reads {fv.get('Aktenzeichen')}")
check(fv.get("Stand", {}).get("id") == GFS and fv.get("Stand", {}).get("label") == "Erledigt",
      f"the select value is on the target's own field, its missing option added {fv.get('Stand')}")
check(sorted(o["name"] for o in fv.get("Stand", {}).get("options") or []) == ["Erledigt", "Offen"], "the target's field has both options once")
check(all(v[0].startswith("kenc1:") for v in sql("SELECT value FROM doc_field_values WHERE node_id=?", (GD,))), "the values are sealed at rest")
check(sql("SELECT COUNT(*) FROM office_letters WHERE org_id=?", (ORG,))[0][0] == 2, "the source keeps its letters")
r = A.post(B + f"/api/imports/{IMP}/undo")
check(r.ok, "undo " + r.text[:160])
check(not sql("SELECT 1 FROM office_letters WHERE org_id=?", (GAM,)) and not sql("SELECT 1 FROM office_letter_blocks WHERE org_id=?", (GAM,)),
      "undo removes the letters and text blocks")
gf = [x[0] for x in sql("SELECT name FROM doc_fields WHERE ws=?", (f"o{GAM}",))]
check(gf == ["Stand"], f"undo removes the field it made, the target's own stays {gf}")
check(not sql("SELECT 1 FROM doc_field_values WHERE ws=?", (f"o{GAM}",)), "undo removes the values")
A.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- a person without an organisation imports it privately
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
ws(Fr, "private")
iid, pv = opened(Fr, OX, RK)
j = run(Fr, iid, "private")
check(j.get("state") == "done", f"freelancer: import done {j.get('error')} {(j.get('result') or {}).get('warnings')}")
PB = one("SELECT id FROM orgs WHERE personal_of=?", (FID,))
PB = PB[0] if PB else 0
fl = one("SELECT id, node_id FROM office_letters WHERE org_id=? AND status='sent'", (PB,))
check(PB and fl, "freelancer: the sent letter is in the personal office")
d = Fr.get(B + f"{LT}/{fl[0] if fl else 0}").json()
check(d.get("subject") == "Widerspruch AZ-77", f"freelancer: the letter reads {d.get('subject')}")
fn = one("SELECT org_id, owner_id FROM fs_nodes WHERE id=?", (fl[1] if fl else 0,))
check(fn and fn[0] is None and fn[1] == FID, f"freelancer: the filed PDF is a private file {fn}")
check(A.get(B + f"{LT}/{fl[0] if fl else 0}").status_code in (403, 404), "alice cannot open the freelancer's letter")
fd = one("SELECT n.id FROM fs_nodes n JOIN doc_meta m ON m.node_id=n.id WHERE n.owner_id=? AND n.name='schreiben.txt'", (FID,))
fv = fields(Fr, fd[0] if fd else 0)
check(fv.get("Aktenzeichen", {}).get("value") == "AZ-77" and fv.get("Stand", {}).get("label") == "Erledigt",
      f"freelancer: the field values read in the private documents {fv}")
check(not sql("SELECT 1 FROM doc_fields WHERE ws=? AND org_id IS NOT NULL", (f"u{FID}",)), "freelancer: the fields are private")
ri = Fr.get(B + "/api/retention/me").json()
check((ri.get("counts") or {}).get("letters") == 1, f"#2628 freelancer: the sent letter counts in the own records {ri.get('counts')}")
names = zip_names(Fr, "/api/retention/me/export.zip")
check("letters/letters.csv" in names and any(n.startswith("letters/") and n.endswith(".pdf") for n in names),
      f"#2628 freelancer: the retention ZIP has the letter {[n for n in names if n.startswith('letters/')]}")
r = Fr.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok and not sql("SELECT 1 FROM office_letters WHERE org_id=?", (PB,)) and not sql("SELECT 1 FROM doc_fields WHERE ws=?", (f"u{FID}",)),
      "freelancer: undo removes the letters and the fields")

print(f"p2184_a: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
