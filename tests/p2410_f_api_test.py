#!/usr/bin/env python3
"""2.41.0 API tests (agent F), own container (start.sh).
 - #1437: vCard import of large files: batches of 200 (each committed), the version row and the book are touched once per
   batch (a parallel write no longer waits for the end of the import), ?background=1 answers 202 {import_id} for a file of
   more than 100 cards and GET /api/books/imports/<id> tells the progress (only the person who started it); a small file
   and the REST API answer as before {created, updated, unchanged, errors}. PERF lines: 1,300 invented contacts with and
   without photos (generated here, no real data)
usage: p2410_f_api_test.py <datadir>"""
import base64
import os
import random
import subprocess
import sys
import threading
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
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


def vcards(n, photos=False, prefix="lv"):
    """n invented contacts (fictional names, example.com addresses); photos: ~12 kB of random bytes each."""
    rnd = random.Random(7)
    giv = ["Anna", "Ben", "Clara", "Dario", "Eva", "Finn", "Greta", "Hugo", "Ida", "Jon"]
    fam = ["Muster", "Beispiel", "Probe", "Testmann", "Fiktiv", "Erfunden"]
    ph = base64.b64encode(bytes(rnd.getrandbits(8) for _ in range(9000))).decode() if photos else ""
    out = []
    for i in range(n):
        g, f = giv[i % len(giv)], fam[i % len(fam)]
        c = ["BEGIN:VCARD", "VERSION:3.0", f"UID:{prefix}-{i}", f"FN:{g} {f} {i}", f"N:{f} {i};{g};;;", f"EMAIL:{g.lower()}.{i}@example.com",
             f"TEL:+49 30 {100000 + i}", f"BDAY:19{50 + i % 50}-0{1 + i % 9}-1{i % 9}" if i % 3 == 0 else "NOTE:fictional"]
        if ph:
            c.append("PHOTO;ENCODING=b;TYPE=JPEG:" + "\r\n ".join(ph[j:j + 74] for j in range(0, len(ph), 74)))
        c.append("END:VCARD")
        out.append("\r\n".join(c))
    return "\r\n".join(out) + "\r\n"


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments", "contacts"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")

# ================================================================== #1437: vCard import
BK = A.post(B + "/api/books", json={"name": "Big"}).json()["id"]
small = vcards(20, prefix="sm")
r = A.post(B + f"/api/books/{BK}/import?background=1", files={"file": ("s.vcf", small, "text/vcard")})
check(r.status_code == 200 and r.json() == {"created": 20, "updated": 0, "unchanged": 0, "errors": 0},
      f"#1437: a small file is answered at once in the old format {r.status_code} {r.text[:200]}")


def timed_write(out):
    time.sleep(0.8)
    t = time.time()
    rr = A.post(B + "/api/tasks", json={"title": "written while importing"})
    out.append((rr.status_code, time.time() - t))


for photos in (False, True):
    BKp = A.post(B + "/api/books", json={"name": f"Perf {photos}"}).json()["id"]
    text = vcards(1300, photos=photos, prefix="p" + str(int(photos)))
    side = []
    th = threading.Thread(target=timed_write, args=(side,))
    t0 = time.time()
    th.start()
    r = A.post(B + f"/api/books/{BKp}/import", files={"file": ("big.vcf", text, "text/vcard")})
    dt = time.time() - t0
    th.join()
    check(r.ok and r.json()["created"] == 1300, f"#1437: 1,300 contacts (photos {photos}) in the synchronous way {r.status_code} {r.text[:200]}")
    print(f"PERF #1437 sync import 1300 contacts photos={photos} size={len(text) // 1024} kB: {dt:.2f} s; a parallel task write took "
          f"{side[0][1]:.2f} s", flush=True)
    check(side and side[0][0] in (200, 201) and side[0][1] < max(1.5, dt * 0.6),
          f"#1437: a parallel write does not wait for the end of the import {side} (import {dt:.2f} s)")

# background
BG = A.post(B + "/api/books", json={"name": "Background"}).json()["id"]
text = vcards(1300, photos=True, prefix="bg")
t0 = time.time()
r = A.post(B + f"/api/books/{BG}/import?background=1", files={"file": ("big.vcf", text, "text/vcard")})
check(r.status_code == 202 and r.json().get("import_id") and r.json()["state"] == "running" and r.json()["total"] == 1300,
      f"#1437: a large file -> 202 with an import id {r.status_code} {r.text[:200]}")
iid = r.json().get("import_id", "x")
check(Bo.get(B + f"/api/books/imports/{iid}").status_code == 404, "#1437: someone else does not see the import")
seen, st = set(), {}
for _ in range(240):
    st = A.get(B + f"/api/books/imports/{iid}").json()
    seen.add(st.get("done"))
    if st.get("state") != "running":
        break
    time.sleep(0.25)
print(f"PERF #1437 background import 1300 contacts with photos: {time.time() - t0:.2f} s until done", flush=True)
check(st.get("state") == "done" and st["created"] == 1300 and st["done"] == 1300 and st["errors"] == 0 and st["ended_at"],
      f"#1437: the background import ends with its counts {st}")
check(len(seen) >= 2, f"#1437: the progress moves {sorted(x for x in seen if x is not None)}")
cnt = [b for b in A.get(B + "/api/books").json()["items"] if b["id"] == BG][0]["count"]
check(cnt == 1300, f"#1437: all contacts stored {cnt}")
r = A.post(B + f"/api/books/{BG}/import?background=1", files={"file": ("big.vcf", text, "text/vcard")})
iid2 = r.json().get("import_id")
for _ in range(240):
    st = A.get(B + f"/api/books/imports/{iid2}").json()
    if st.get("state") != "running":
        break
    time.sleep(0.25)
check(st.get("state") == "done" and st["created"] == 0 and st["updated"] == 1300, f"#1437: importing twice updates, no doubles {st}")
# read-only member: no import
A.put(B + f"/api/books/{BG}/members", json={"user_id": 2, "role": "view"})
r = Bo.post(B + f"/api/books/{BG}/import?background=1", files={"file": ("big.vcf", text, "text/vcard")})
check(r.status_code == 403, f"#1437: a reader cannot import {r.status_code}")
check(A.get(B + "/api/books/imports/nope").status_code == 404, "#1437: unknown import id -> 404")
# a broken card among many: counted as not readable, the rest stored
bad = vcards(150, prefix="br") + "BEGIN:VCARD\r\nVERSION:3.0\r\nNOTE:no name\r\nEND:VCARD\r\n"
BB = A.post(B + "/api/books", json={"name": "Broken"}).json()["id"]
iid3 = A.post(B + f"/api/books/{BB}/import?background=1", files={"file": ("b.vcf", bad, "text/vcard")}).json().get("import_id")
for _ in range(120):
    st = A.get(B + f"/api/books/imports/{iid3}").json()
    if st.get("state") != "running":
        break
    time.sleep(0.25)
check(st.get("state") == "done" and st["created"] == 150 and st["errors"] == 1, f"#1437: a card without a name is not readable {st}")

print(f"p2410_f_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
time.sleep(0.1)
sys.exit(1 if FAILS else 0)
