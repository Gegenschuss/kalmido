#!/usr/bin/env python3
"""2.184.0 B API tests (#2580, #2585). Invented names only, generated file contents.
 - #2580 moving a document into an organisation: a member without admin rights there uses only the fields that exist (a
   missing field or a missing select option: 409 naming the field, nothing moved, nothing made); an admin makes them
 - #2580 the Paperless import (docs/fields.py df_from_paperless, called in the container, no network): a member uses only
   existing fields, a value without a field stays as a line in the document's text; a full workspace (50 fields) keeps the
   value as a line too; a person without an organisation makes the field in her own space (moving out of an organisation
   is for its admins anyway, files/fsmove.py)
 - #2580 the search finds a custom field value by a word prefix (the portion-wise check of search_ids)
 - #2585 a client with a letter moving from the personal office into an organisation: the letter stays in its office and
   keeps a client of its own office (the boundary check "letter_client" finds nothing); a letter bound to a client of
   another office is counted by the boundary check
freelancer-matrix: documents
usage: p2184_b_fields_test.py <datadir>      (a fresh container; P2184B_NOSTART=1: the container runs already)"""
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
from freelancer_fixture import freelancer, org_join  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FEAT = "cal,comments,collab,office,clients,docs,contacts,files"
LT = "/api/office/letters"
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


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        r = c.execute(sql, args).fetchall() if sql.lstrip().upper().startswith("SELECT") else c.execute(sql, args)
        c.commit()
        return r
    finally:
        c.close()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def in_ct(code):
    # importing kalmido next to the running server may meet its start-up DDL (a Postgres deadlock now and then): try again
    for _ in range(4):
        r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=120)
        if r.returncode == 0 or "deadlock detected" not in (r.stdout + r.stderr).lower():
            break
        time.sleep(2)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


BC = ("import json\nfrom kalmido.core.db import connect\nfrom kalmido.accounts.tenancy import boundary_check\nc = connect()\n"
      "print(json.dumps(boundary_check(c)['kinds']))\nc.close()")


def pl_fields(ws, nid, uid, doc, fields):
    """docs/fields.py df_from_paperless on document nid, as Paperless' import calls it (its definitions keyed by id)."""
    code = ("import json\nfrom kalmido.core.db import connect\nfrom kalmido.docs.fields import df_from_paperless\nc = connect()\n"
            f"n = df_from_paperless(c, {ws!r}, {int(nid)}, json.loads({json.dumps(doc)!r}), "
            f"{{int(k): v for k, v in json.loads({json.dumps(fields)!r}).items()}}, {int(uid)})\n"
            "c.commit()\nprint(json.dumps({'n': n}))\nc.close()")
    return in_ct(code)["n"]


def doc(s, ws, name, text):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text.encode(), "text/plain"))])
    assert r.status_code in (200, 201), r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 120)
    return nid


def cf(s, nid):
    return {x["name"]: x for x in s.get(B + f"/api/docs/{nid}").json().get("custom_fields") or []}


def add(s, ws, name, typ, **kw):
    r = s.post(B + "/api/docs/fields", json={"ws": ws, "name": name, "type": typ, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def move(s, nid, to):
    return s.post(B + "/api/files/move-space", json={"ids": [nid], "to": to, "parent": None})


def ws_of(nid):
    return one("SELECT ws FROM doc_meta WHERE node_id=?", (nid,))


def names(ws):
    return {x[0] for x in dbx("SELECT name FROM doc_fields WHERE ws=?", (ws,))}


# ---- setup: alice (instance admin), Alpha = bob (admin) + carol (member), frida without an organisation
if not os.environ.get("P2184B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY=" + KEY
               + " -e KALMIDO_ORGCRYPT_DELAY=0")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
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
dbx("DELETE FROM org_members WHERE org_id=? AND user_id NOT IN (?,?)", (ORG, BOB, CAROL))
FRIDA, Fr = freelancer(B, A)
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca, Fr):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
OWS, CWS, FWS = f"o{ORG}", f"u{CAROL}", f"u{FRIDA}"

# ==== #2580: moving into Alpha -- a member uses only the fields Alpha has
D1 = doc(Ca, "private", "akte.txt", "Akte Beispiel eins")
CAKTE = add(Ca, "private", "Akte", "text")
check(Ca.patch(B + f"/api/docs/{D1}", json={"custom_fields": {str(CAKTE): "A-77"}}).ok, "setup: carol's private document with a value")
r = move(Ca, D1, f"org:{ORG}")
check(r.status_code == 409 and "Akte" in (r.json().get("error") or ""), f"a member: a missing field -> 409 naming it ({r.status_code} {r.text[:200]})")
check(ws_of(D1) == CWS and "Akte" not in names(OWS), "nothing moved, no field made in Alpha")
check(cf(Ca, D1).get("Akte", {}).get("value") == "A-77", "the value stays on the private document")

ASTAT = add(Bo, f"org:{ORG}", "Status", "select", options="Aktiv")
D3 = doc(Ca, "private", "status.txt", "Status Beispiel drei")
CSTAT = add(Ca, "private", "Status", "select", options="Ruhend")
Ca.patch(B + f"/api/docs/{D3}", json={"custom_fields": {str(CSTAT): cf(Ca, D3)["Status"]["options"][0]["id"]}})
r = move(Ca, D3, f"org:{ORG}")
opts = json.loads(one("SELECT options FROM doc_fields WHERE id=?", (ASTAT,)) or "{}").get("options") or []
check(r.status_code == 409 and "Status" in (r.json().get("error") or "") and [o["name"] for o in opts] == ["Aktiv"],
      f"a member: a missing select option -> 409, Alpha's options untouched ({r.status_code} {opts})")

add(Bo, f"org:{ORG}", "Akte", "text")
r = move(Ca, D1, f"org:{ORG}")
check(r.ok and ws_of(D1) == OWS, f"once the admin made the field, the member's move works ({r.status_code} {r.text[:200]})")
check(cf(Ca, D1).get("Akte", {}).get("value") == "A-77" and names(OWS) == {"Status", "Akte"}, f"the value uses Alpha's field ({names(OWS)})")

D2 = doc(Bo, "private", "neu.txt", "Neu Beispiel zwei")
BNEU = add(Bo, "private", "Neufeld", "text")
Bo.patch(B + f"/api/docs/{D2}", json={"custom_fields": {str(BNEU): "Zebrafant-42"}})
r = move(Bo, D2, f"org:{ORG}")
check(r.ok and "Neufeld" in names(OWS) and cf(Bo, D2).get("Neufeld", {}).get("value") == "Zebrafant-42",
      f"the admin: the missing field is made in Alpha ({r.status_code} {r.text[:200]})")

# ==== #2580: the search finds a field value by a word prefix (portion-wise check)
hits = Bo.get(B + "/api/docs?ws=all&q=zebraf").json()
check(D2 in [d["id"] for d in hits.get("docs") or hits.get("data") or []], f"the search finds a field value by its prefix ({str(hits)[:200]})")
hits = Bo.get(B + "/api/docs?ws=all&q=zebrafx").json()
check(D2 not in [d["id"] for d in hits.get("docs") or hits.get("data") or []], "a longer word that does not match finds nothing")

# ==== #2580: the Paperless import -- a member uses only existing fields, the rest stays in the text
PLF = {"1": {"name": "Projektcode", "type": "string"}, "2": {"name": "Akte", "type": "string"}, "3": {"name": "Voll", "type": "string"}}
DP = doc(Ca, f"org:{ORG}", "import.txt", "Import Beispiel fuenf")
n = pl_fields(OWS, DP, CAROL, {"custom_fields": [{"field": 1, "value": "P-9"}, {"field": 2, "value": "A-200"}]}, PLF)
d = Ca.get(B + f"/api/docs/{DP}").json()
check(n == 1 and "Projektcode" not in names(OWS), f"a member: no field made by the import ({n}, {names(OWS)})")
check({x["name"]: x["value"] for x in d.get("custom_fields") or []}.get("Akte") == "A-200", "the existing field takes its value")
check("Projektcode: P-9" in (d.get("text") or ""), f"the value without a field stays as a line in the text ({(d.get('text') or '')[-120:]})")
hits = Ca.get(B + "/api/docs?ws=all&q=projektcode").json()
check(DP in [x["id"] for x in hits.get("docs") or hits.get("data") or []], "the line is in the search")

# a full workspace (50 fields): the admin's import keeps the value as a line
have = one("SELECT COUNT(*) FROM doc_fields WHERE ws=?", (OWS,))
for i in range(50 - have):
    dbx("INSERT INTO doc_fields(org_id, ws, name, type, options, sort, created_by, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (ORG, OWS, f"Feld {i}", "text", "{}", 100 + i, BOB, "2026-10-23T00:00:00Z"))
DQ = doc(Bo, f"org:{ORG}", "voll.txt", "Voll Beispiel sechs")
n = pl_fields(OWS, DQ, BOB, {"custom_fields": [{"field": 3, "value": "V-3"}]}, PLF)
check(n == 0 and one("SELECT COUNT(*) FROM doc_fields WHERE ws=?", (OWS,)) == 50, "full: no 51st field")
check("Voll: V-3" in (Bo.get(B + f"/api/docs/{DQ}").json().get("text") or ""), "full: the value stays as a line in the text")

# freelancer-matrix: documents -- a person without an organisation is the admin of her own documents
DF = doc(Fr, "private", "frida.txt", "Frida Beispiel sieben")
n = pl_fields(FWS, DF, FRIDA, {"custom_fields": [{"field": 1, "value": "P-10"}]}, PLF)
check(n == 1 and "Projektcode" in names(FWS) and cf(Fr, DF).get("Projektcode", {}).get("value") == "P-10",
      f"freelancer: the import makes the field in her own space ({n}, {names(FWS)})")

# ==== #2585: a client with a letter from the personal office into Alpha
Bo.patch(B + "/api/settings", json={"workspace": "private"})
CL = Bo.post(B + "/api/clients", json={"name": "Kunde Beispiel"}).json().get("id")
r = Bo.post(B + LT, json={"client_id": CL, "subject": "Angebot Beispiel"})
check(r.status_code == 201, f"setup: a letter to the private client ({r.status_code} {r.text[:200]})")
LID = r.json().get("id")
PB = one("SELECT org_id FROM office_letters WHERE id=?", (LID,))
check("letter_client" not in in_ct(BC), "a personal office's letter to the owner's private client is no boundary case")
r = Bo.post(B + "/api/office/move-space", json={"what": "clients", "ids": [CL], "to": f"org:{ORG}"})
check(r.ok, f"the client moves into Alpha ({r.status_code} {r.text[:300]})")
lc = one("SELECT client_id FROM office_letters WHERE id=?", (LID,))
row = dbx("SELECT org_id, created_by FROM clients WHERE id=?", (lc,)) if lc else []
check(one("SELECT org_id FROM office_letters WHERE id=?", (LID,)) == PB, "the letter stays in the personal office")
check(lc is None or (row and row[0][0] is None and row[0][1] == BOB), f"the letter keeps no client of another office ({lc}, {row})")
check("letter_client" not in in_ct(BC), "the boundary check finds no letter bound across offices")
# a letter of Alpha's office bound to bob's private client is counted
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = Bo.post(B + LT, json={"subject": "Alpha Beispiel"})
LA = r.json().get("id")
Bo.patch(B + "/api/settings", json={"workspace": "private"})
CP = Bo.post(B + "/api/clients", json={"name": "Privat Beispiel"}).json().get("id")
dbx("UPDATE office_letters SET client_id=? WHERE id=?", (CP, LA))
check(in_ct(BC).get("letter_client") == 1, "a letter bound to a client of another office is counted")
dbx("UPDATE office_letters SET client_id=NULL WHERE id=?", (LA,))

print(f"p2184_b_fields: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
