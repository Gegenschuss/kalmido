#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.657.0 A (#5018): the organisation import puts the values of a 'link to documents' field onto the new documents instead of
leaving them out. Invented names only.
 - an organisation with three documents and a link field: D1 -> D2,D3 (set in the app), D3 -> D1 + a Paperless reference
   + a document of the TARGET organisation + an id that exists nowhere (written into the source like an older archive),
   D2 -> only a Paperless reference
 - exported and imported into another organisation: D1 links the two NEW documents, D3 only the new D1 (never the raw id of
   the target's own document, nor the Paperless reference), D2 has no value; the report counts the links left out
 - a person without an organisation imports the same export privately: the links point at the private new documents
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2657A_NOSTART=1 = the server already runs like that).
usage: p2657_a_orgimport_test.py <datadir>"""
# freelancer-matrix: files
# tenant-matrix: own
import base64
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess, su_get, until  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "docs,files"
LEFT = "Links to documents that did not come along were left out"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


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
    return iid


def run(s, iid, target):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    return wait(s, iid)


def links(s, nid, name):
    f = next((x for x in s.get(B + f"/api/docs/{nid}").json().get("custom_fields") or [] if x.get("name") == name), {})
    return [x["id"] for x in f.get("links") or []], f.get("value")


def warned(j, text):
    return sum(w.get("count") or 0 for w in (j.get("result") or {}).get("warnings") or [] if (w.get("text") if isinstance(w.get("text"), str) else (w.get("text") or [""])[0]) == text)


def node(space, name):
    if space:
        r = sql("SELECT n.id FROM fs_nodes n JOIN doc_meta m ON m.node_id=n.id WHERE n.org_id=? AND n.name=? AND n.deleted_at IS NULL",
                (space, name))
    else:
        r = sql("SELECT n.id FROM fs_nodes n JOIN doc_meta m ON m.node_id=n.id WHERE n.org_id IS NULL AND n.owner_id=? AND n.name=?"
                " AND n.deleted_at IS NULL", (FID, name))
    return r[0][0] if r else 0


if os.environ.get("P2657A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}"
               " -e KALMIDO_DOCS_SCAN_S=1")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Ablage", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Akten", "admin_id": ALICE}).json()["id"]
GAM = A.post(B + "/api/admin/orgs", json={"name": "Gamma Ziel", "admin_id": ALICE}).json()["id"]
SP = f"org:{ORG}"

# ---------------------------------------------------------------- the source: three documents, a link field
ws(A, SP)
D1, D2, D3 = (doc(A, f"{n}.txt", f"Akte {n}\nDatum: 01.10.2026\n", SP) for n in ("akte-eins", "akte-zwei", "akte-drei"))
r = A.post(B + "/api/docs/fields", json={"ws": SP, "name": "Bezug", "type": "documentlink"})
check(r.status_code == 201, "setup: a link field " + r.text[:200])
FD = r.json().get("id") if r.ok else 0
r = A.patch(B + f"/api/docs/{D1}", json={"custom_fields": {str(FD): f"{D2},{D3}"}})
check(r.ok and links(A, D1, "Bezug")[0] == [D2, D3], f"setup: D1 links D2 and D3 {r.status_code} {r.text[:200]}")
ws(A, f"org:{GAM}")
GOWN = doc(A, "eigen.txt", "Eigenes Dokument des Ziels\n", f"org:{GAM}")  # the target's own document: its id is no source id
ws(A, SP)
# values the app does not let anyone set (an older archive, a Paperless import of the source): written sealed into the source
code = ("from kalmido.core.db import connect\nfrom kalmido.docs import store as S\nc = connect()\n"
        f"w = c.execute('SELECT ws FROM doc_fields WHERE id=?', ({FD},)).fetchone()[0]\n"
        f"for nid, v in (({D3}, '{D1},pl:7,{GOWN},987654321'), ({D2}, 'pl:8')):\n"
        "    c.execute('DELETE FROM doc_field_values WHERE node_id=? AND field_id=?', (nid, " + str(FD) + "))\n"
        "    c.execute('INSERT INTO doc_field_values(node_id, field_id, org_id, ws, value) VALUES(?,?,?,?,?)',"
        " (nid, " + str(FD) + ", S.ws_org(w), w, S.doc_seal(c, w, 'doc_field_values.value', v)))\n"
        "c.commit()\nprint('ok')\n")
ct = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True)
check(ct.stdout.split() == ["ok"], f"setup: the raw values written {ct.stdout} {ct.stderr[-400:]}")
check(len(sql("SELECT 1 FROM doc_field_values WHERE field_id=?", (FD,))) == 3, "setup: three values in the source")

# ---------------------------------------------------------------- export -> import into the other organisation
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, "organisation export started " + r.text[:120])
until(lambda: A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running", 120)
OX = su_get(A, B + f"/api/orgs/{ORG}/export/file").content
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
check(OX[:13] == b"KALMIDO-ORGX\n" and RK, "organisation export + recovery key")
iid = opened(A, OX, RK)
j = run(A, iid, GAM)
check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')} {(j.get('result') or {}).get('warnings')}")

ws(A, f"org:{GAM}")
G1, G2, G3 = node(GAM, "akte-eins.txt"), node(GAM, "akte-zwei.txt"), node(GAM, "akte-drei.txt")
check(G1 and G2 and G3 and not {G1, G2, G3} & {D1, D2, D3}, f"the three documents came along with new ids {G1} {G2} {G3}")
got, raw = links(A, G1, "Bezug")
check(got == [G2, G3] and raw == f"{G2},{G3}", f"#5018: D1 links the two new documents, not the source's ids {got} {raw}")
got, raw = links(A, G3, "Bezug")
check(got == [G1] and raw == str(G1), f"#5018: D3 links only the new D1 (no raw id, no Paperless reference) {got} {raw}")
check(GOWN not in got and str(GOWN) not in str(raw), "#5018: the target's own document is never linked by a source id")
gf = sql("SELECT id FROM doc_fields WHERE ws=? AND name='Bezug'", (f"o{GAM}",))
GF = gf[0][0] if gf else 0
check(GF and not sql("SELECT 1 FROM doc_field_values WHERE node_id=? AND field_id=?", (G2, GF)),
      "#5018: D2 (only a Paperless reference) has no value in the target")
check(all(v[0].startswith("kenc1:") for v in sql("SELECT value FROM doc_field_values WHERE field_id=?", (GF,))), "#5018: the values are sealed at rest")
check(warned(j, LEFT) == 4, f"#5018: the report counts the four links left out {(j.get('result') or {}).get('warnings')}")
check(warned(j, "Field values not imported") == 1, f"#5018: the value left with nothing counts as not imported {(j.get('result') or {}).get('warnings')}")
A.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- a person without an organisation imports it privately
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
ws(Fr, "private")
iid = opened(Fr, OX, RK)
j = run(Fr, iid, "private")
check(j.get("state") == "done", f"freelancer: import done {j.get('error')} {(j.get('result') or {}).get('warnings')}")
P1, P2, P3 = node(None, "akte-eins.txt"), node(None, "akte-zwei.txt"), node(None, "akte-drei.txt")
check(P1 and P2 and P3, f"freelancer: the documents are private {P1} {P2} {P3}")
check(links(Fr, P1, "Bezug")[0] == [P2, P3] and links(Fr, P3, "Bezug")[0] == [P1],
      f"freelancer: the links point at the private new documents {links(Fr, P1, 'Bezug')} {links(Fr, P3, 'Bezug')}")
check(A.get(B + f"/api/docs/{P1}").status_code in (403, 404), "freelancer: alice cannot open the private document")

if FAILS:
    print(subprocess.run(["docker", "logs", "--tail", "80", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True).stdout[-8000:], flush=True)
print(f"p2657_a: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
