#!/usr/bin/env python3
"""2.153.0 API tests, part A2: review fixes of the correspondence (#2028), own container (start.sh). Invented companies,
people and figures only.
freelancer-matrix: office
tenant-matrix: office
 - A1: the personal office moves into an organisation where the person has a signature already: the transfer works, the
   organisation keeps its own signature, the personal office keeps the other one
 - A2: the letters' links to private documents (answer link, filed PDF) and private address book contacts end when the
   personal office moves (into an organisation, or becomes a new one): the preview names the number, the documents stay
   private and present, the boundary check finds nothing
 - A3: the organisation role accounting reads the bookkeeping but not the letters (403, the document side empty); an
   admin and a person without an organisation read them
usage: p2153_a2_api_test.py <datadir>      (P2153A2_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import json
import os
import subprocess
import sys
import time

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
CHK, MV = "/api/office/move/check", "/api/office/move/org"
BC = ("import json\nfrom kalmido.core.db import connect\nfrom kalmido.accounts.tenancy import boundary_check\nc = connect()\n"
      "print(json.dumps(boundary_check(c)['kinds']))\nc.close()")


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


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall() if not write else c.execute(q, args)
        if write:
            c.commit()
            return None
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


def upload(s, name, text, ws):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text.encode("utf-8"), "text/plain"))])
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    d = until(lambda: (lambda x: x.json() if x.ok and x.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")), 90)
    assert d and d["state"] == "done", d
    return nid


def in_ct(code):
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def ws(s, v):
    r = s.patch(B + "/api/settings", json={"workspace": v})
    assert r.ok, r.text


def private_letter(s, tag):
    """A letter of the personal office shown answering a private document, with a private contact and a filed PDF (a
    second private document) -> (letter id, answered document, filed document, contact)."""
    d1 = upload(s, f"Schreiben {tag}.txt", f"Amt {tag} Beispiel\nDatum: 01.10.2026\nAktenzeichen: AZ-{tag}\n", "private")
    d2 = upload(s, f"Brief {tag}.txt", f"Unser Brief {tag}\nDatum: 02.10.2026\n", "private")
    bk = s.post(B + "/api/books", json={"name": f"Privat {tag}", "org_id": None}).json()["id"]
    ct = s.post(B + "/api/contacts", json={"book_id": bk, "fn": f"Kontakt {tag} Beispiel",
                                           "addresses": [{"street": "Privatweg 1", "city": "Bonn"}]}).json()["id"]
    r = s.post(B + LT, json={"answers": d1})
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    r = s.patch(B + f"{LT}/{lid}", json={"contact_id": ct, "subject": f"Antwort {tag}"})
    check(r.ok, f"setup {tag}: the private contact as recipient " + r.text[:200])
    sql("UPDATE office_letters SET node_id=? WHERE id=?", (d2, lid), write=True)  # the filed letter PDF
    check(sql("SELECT COUNT(*) FROM office_letter_links WHERE letter_id=?", (lid,))[0][0] == 1, f"setup {tag}: the answer link")
    return lid, d1, d2, ct


def detached(lid, docs, tag):
    lk = sql("SELECT COUNT(*) FROM office_letter_links WHERE letter_id=?", (lid,))[0][0]
    row = sql("SELECT node_id, contact_id FROM office_letters WHERE id=?", (lid,))[0]
    check(lk == 0 and row[0] is None and row[1] is None, f"{tag}: the letter's links to private documents and contacts ended {lk} {row}")
    for d in docs:
        n = sql("SELECT org_id, deleted_at FROM fs_nodes WHERE id=?", (d,))
        check(n and n[0][0] is None and n[0][1] is None, f"{tag}: document {d} stays private and present {n}")
    check("letter_link" not in in_ct(BC), f"{tag}: the boundary check finds no letter link across the boundary")


if os.environ.get("P2153A2_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}"
               " -e KALMIDO_DOCS_SCAN_S=1")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Buch", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})

# ================================================================ A1 + A2: the personal office into an organisation
ws(Fr, "private")
check(Fr.get(B + LT).status_code == 200, "A3: a person without an organisation reads the letters")
check(Fr.put(B + LT + "/profile", json={"greeting": "Viele Grüße", "name": "Frida privat"}).ok, "setup: the personal signature")
PB = Fr.get(B + "/api/office/settings").json()["org_id"]
L1, D1, D2, C1 = private_letter(Fr, "eins")
KAP = A.post(B + "/api/admin/orgs", json={"name": "Kappa", "admin_id": FID}).json()["id"]
ws(Fr, f"org:{KAP}")
check(Fr.put(B + LT + "/profile", json={"greeting": "Beste Grüße", "name": "Frida Kappa"}).ok, "setup: the signature in the organisation")
ws(Fr, "private")
j = Fr.get(B + CHK + f"?org={KAP}").json()
check(j.get("ok") is True and not j.get("conflicts"), f"preview: no conflict {j}")
check(any("2 links of letters to private documents" in x for x in j.get("notes") or []), f"A2 preview: the links that end are named {j.get('notes')}")
r = Fr.post(B + MV, json={"org": KAP, "confirm": True})
check(r.ok and r.json().get("letter_links") == 2, "A1: the transfer with a signature in both offices works " + r.text[:300])
pr = sql("SELECT org_id, name FROM office_letter_profiles WHERE user_id=? ORDER BY org_id", (FID,))
check(len(pr) == 2 and {x[0] for x in pr} == {PB, KAP}, f"A1: one signature per office stays {[x[0] for x in pr]}")
check(Fr.get(B + LT + "/profile").json().get("name") == "Frida Kappa", "A1: the organisation keeps its own signature")
check(sql("SELECT org_id FROM office_letters WHERE id=?", (L1,))[0][0] == KAP, "A2: the letter moved")
x = Fr.get(B + f"{LT}/{L1}")
check(x.ok and x.json().get("subject") == "Antwort eins" and x.json().get("rcpt_name") == "Kontakt eins Beispiel",
      "A2: the letter readable in the organisation, the frozen recipient stays " + x.text[:200])
detached(L1, (D1, D2), "A2 into an organisation")
lg = Fr.get(B + "/api/office/log?limit=20").json().get("log") or []
check(any(e.get("action") == "move" and (e.get("detail") or {}).get("letter_links") == 2 for e in lg), f"A2: the number in the office log {lg[:2]}")

# ================================================================ A2: the personal office becomes a new organisation
ws(A, "private")
L2, D3, D4, C2 = private_letter(A, "zwei")
r = A.post(B + "/api/office/move", json={"name": "Neu Studio", "confirm": True})
check(r.ok, "the personal office becomes an organisation " + r.text[:200])
detached(L2, (D3, D4), "A2 new organisation")
check(A.get(B + f"{LT}/{L2}").ok, "A2: the letter stays readable in the new organisation")

# ================================================================ A3: the role accounting
assert Fr.put(B + f"/api/orgs/{KAP}/members", json={"email": "bob@example.com", "role": "accounting"}).ok
ws(Bo, f"org:{KAP}")
check(Bo.get(B + "/api/office/settings").ok, "setup: accounting reads the office")
for path in (LT, f"{LT}/{L1}", LT + "/recipients?q=a", LT + "/profile"):
    check(Bo.get(B + path).status_code == 403, f"A3: accounting gets 403 on {path}")
ws(Fr, f"org:{KAP}")
DK = upload(Fr, "Kappa.txt", "Lieferant Beispiel\nDatum: 03.10.2026\nIhre Bestellung.\n", f"org:{KAP}")
check(Fr.get(B + LT).status_code == 200 and Fr.get(B + f"{LT}/doc/{DK}").json().get("available") is True, "A3: the admin reads the letters")
check(Bo.get(B + f"{LT}/doc/{DK}").json() == {"available": False}, "A3: accounting sees no letters at a document")

print(f"\np2153_a2: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
