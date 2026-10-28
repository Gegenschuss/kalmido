#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.373.0 (#3335, #3336) API tests: folder comfort from the review of 2.351. Own container (start.sh), invented names only.
 (a) #3336 learned folder on upload (docs/store.py classify): the model's folder only when the uploading person may edit it --
     alice (admin) gets it filed, carl (accounting, reads the documents folder only) neither filed nor suggested (rollback
     test: before, carl got it as a suggestion); frida without an organisation: her own folder is filed
 (b) #3335 a folder comes back out of the trash, a table in it the restoring person may not edit (an owner-only project
     table): the table stays in the tables' trash and the restore says so -- POST /api/files/nodes/<id>/restore and
     POST /api/files/restore answer stays {"sheet": 1}; the table stays deleted; who may edit it gets stays {} (frida too)
usage: p2373_a_folders_test.py <datadir>
freelancer-matrix: files"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,comments,collab,files,docs,sheets"

if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Example", "admin_id": ALICE}).json()["id"]
SP = f"org:{ORG}"
USERS = {}
for name, role in (("bob", "member"), ("carl", "accounting")):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", "email": f"{name}@example.com"})
    assert r.ok, r.text
    USERS[name] = r.json()["id"]
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{name}@example.com", "role": role}).ok
Bo, Ca = sess("bob"), sess("carl")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": SP})
FID, Fr = freelancer(B, A)  # freelancer-matrix: files
Fr.patch(B + "/api/settings", json={"features": FEAT})


def in_ct(code, timeout=120):
    """Python code inside the server container (the app loaded) -> stdout + stderr."""
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app\n" + code],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def upload(s, name, ws):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Doc " + name), "application/pdf")})
    check(r.status_code == 201, f"upload {name}: {r.status_code} {r.text[:200]}")
    return r.json()["ids"][0] if r.status_code == 201 else None


def read_done(s, did):
    """The document reader runs after the upload: wait for its state (a real state, no fixed time)."""
    st = None
    for _ in range(360):
        st = s.get(B + f"/api/docs/{did}").json().get("state")
        if st in ("done", "failed"):
            return st
        time.sleep(0.25)
    return st


# ---------------------------------------------------------------- (a) #3336 a learned folder only where the uploader edits
D0 = upload(A, "setup-box.pdf", SP)
check(A.patch(B + f"/api/docs/{D0}", json={"folder": "Secret box"}).ok, "(a) setup: the documents folder Secret box")
SB = int(A.get(B + f"/api/docs/{D0}").json()["folder"]["id"])
check(A.put(B + "/api/docs/settings", json={"ws": SP, "levels": {"folder": "learn"}}).ok, "(a) setup: the folder is learned")
DA, DC = upload(A, "learn-a.pdf", SP), upload(Ca, "learn-c.pdf", SP)
F0 = upload(Fr, "setup-own.pdf", "private")
check(Fr.patch(B + f"/api/docs/{F0}", json={"folder": "Own box"}).ok, "(a) setup: frida's documents folder Own box")
FB = int(Fr.get(B + f"/api/docs/{F0}").json()["folder"]["id"])
check(Fr.put(B + "/api/docs/settings", json={"ws": "private", "levels": {"folder": "learn"}}).ok, "(a) setup: frida's folder is learned")
DF = upload(Fr, "learn-f.pdf", "private")
for s, did in ((A, DA), (Ca, DC), (Fr, DF)):
    read_done(s, did)
# the model's answer is fixed (it would pick the folder for sure): what the uploader's right makes of it
PROBE = ("from kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nfrom kalmido.docs import store as S\n"
         "c = connect()\nwith system_ctx(c):\n"
         "    for nid, fid in (({da}, {sb}), ({dc}, {sb}), ({df}, {fb})):\n"
         "        S.CL.predict = lambda model, toks, fid=fid: (str(fid), 0.99)\n"
         "        m = S.meta_row(c, nid)\n"
         "        node = c.execute('SELECT * FROM fs_nodes WHERE id=?', (nid,)).fetchone()\n"
         "        out, sug, auto = S.classify(c, m, node, 'Learned text')\n"
         "        print('cls', nid, out.get('folder'), 'folder' in sug)\n"
         "c.rollback()\nc.close()")
out = in_ct(PROBE.format(da=DA, dc=DC, df=DF, sb=SB, fb=FB))
check(f"cls {DA} {SB} False" in out, "(a) alice (edits Secret box): the learned folder files her upload " + out[-300:])
check(f"cls {DC} None False" in out, "(a) #3336: carl (reads the folder only): neither filed nor suggested -- stays where it lands " + out[-300:])
check(f"cls {DF} {FB} False" in out, "(a) frida without an organisation: her own learned folder files her upload " + out[-300:])

# ---------------------------------------------------------------- (b) #3335 a table without the right stays in the tables' trash
L = A.post(B + "/api/lists", json={"name": "Owner only", "org_id": ORG}).json()["id"]


def sh_folder(s, name, space=SP):
    r = s.post(B + "/api/sheets/folders", json={"name": name, "space": space})
    assert r.status_code == 201, r.text
    return r.json()["folder"]["id"]


def table(s, title, folder, space=SP, **b):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space, "folder_id": folder, **b})
    assert r.status_code == 201, r.text
    return r.json()["id"]


BX1, BX2 = sh_folder(Bo, "Bob box one"), sh_folder(Bo, "Bob box two")
for f in (BX1, BX2):
    check(Bo.post(B + f"/api/files/nodes/{f}/shares", json={"user_id": ALICE, "role": "edit"}).status_code == 201, "(b) setup: bob shares his folder with alice")
T1, T2 = table(A, "Project costs", BX1, list_id=L), table(A, "Project hours", BX2, list_id=L)
check(Bo.get(B + f"/api/sheets/{T1}").ok and not Bo.get(B + f"/api/sheets/{T1}").json().get("can_write"),
      "(b) setup: bob reads alice's project table through his folder only (no right of his own)")
check(A.delete(B + f"/api/files/nodes/{BX1}").ok and A.post(B + "/api/files/trash", json={"ids": [BX2]}).ok
      and A.get(B + f"/api/sheets/{T1}").status_code == 404 and A.get(B + f"/api/sheets/{T2}").status_code == 404,
      "(b) alice puts bob's folders into the trash: her tables go into the tables' trash")
r = Bo.post(B + f"/api/files/nodes/{BX1}/restore")
check(r.ok and r.json().get("stays") == {"sheet": 1}, f"(b) #3335: bob restores one: 1 table stays in the tables' trash ({r.status_code} {r.text[:200]})")
r = Bo.post(B + "/api/files/restore", json={"ids": [BX2]})
check(r.ok and r.json().get("stays") == {"sheet": 1}, f"(b) #3335: the bulk restore says the same ({r.status_code} {r.text[:200]})")
check(A.get(B + f"/api/sheets/{T1}").status_code == 404 and A.get(B + f"/api/sheets/{T2}").status_code == 404,
      "(b) the tables stay in the tables' trash (no automatic fetching)")
BX3 = sh_folder(A, "Alice box")
T3 = table(A, "Alice costs", BX3, list_id=L)
r = A.delete(B + f"/api/files/nodes/{BX3}")
r = A.post(B + f"/api/files/nodes/{BX3}/restore") if r.ok else r
check(r.ok and r.json().get("stays") == {} and A.get(B + f"/api/sheets/{T3}").ok, f"(b) alice (edits the table): it comes back, nothing stays ({r.text[:200]})")
FX = sh_folder(Fr, "Frida box", "private")
FT = table(Fr, "Rates", FX, "private")
r = Fr.post(B + "/api/files/trash", json={"ids": [FX]})
r = Fr.post(B + "/api/files/restore", json={"ids": [FX]}) if r.ok else r
check(r.ok and r.json().get("stays") == {} and Fr.get(B + f"/api/sheets/{FT}").ok, f"(b) frida without an organisation: her table comes back ({r.text[:200]})")

print(f"p2373_a_folders: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
