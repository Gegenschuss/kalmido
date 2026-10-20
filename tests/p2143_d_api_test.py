#!/usr/bin/env python3
"""2.143.0 API tests, part D (#2155 #2156 #2259). Own container (start.sh). Invented names only, addresses @example.com.
 - #2155 the appearance of the account (setting "look"): saved, read back, a second session ("device") reads it, unknown keys
   are dropped, wrong values / types are refused (400), '' = never saved; other people keep their own
 - #2156 GET /api/admin/orgs/activity and /api/v1/admin/orgs/activity: admins only (403 otherwise), numbers per organisation +
   the row "private" (people without an organisation), no people or contents in the answer
 - #2259 terms PDFs: the current state stays, a state named by a document stays, one replaced less than 30 days ago stays,
   an old unreferenced one is removed (file gone, current / referenced untouched); the same in the personal office
usage: p2143_d_api_test.py <datadir>      (P2143D_NOSTART=1 = the server already runs)"""
import json
import os
import subprocess
import sys

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
FEAT = "cal,comments,collab,office,clients,docs,time"
T = "/api/office/terms"


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
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def settings(s):
    return s.get(B + "/api/state").json()["settings"]


if not os.environ.get("P2143D_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
for u, n in (("bob", "Bob Member"), ("carol", "Carol Beta")):
    assert A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"}).ok
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})

# ================================================================== #2155 the appearance follows the account
check(settings(A).get("look") == "", f"look: never saved = '' ({settings(A).get('look')!r})")
look = {"theme": "dark", "density": "custom", "densSideV": 30, "fsize": 110, "accent": "teal", "pack": "night", "headShow": False}
r = A.patch(B + "/api/settings", json={"look": json.dumps(look)})
check(r.ok, "look: saved " + r.text[:120])
got = json.loads(settings(A)["look"])
check(got == look, f"look: read back {got}")
A2 = sess("alice")  # a second device
check(json.loads(settings(A2)["look"]) == look, "look: a second session takes it over")
check(settings(Bo).get("look") == "" and settings(Ca).get("look") == "", "look: other people keep their own")
r = A.patch(B + "/api/settings", json={"look": json.dumps({**look, "evil": "x", "theme": "light"})})
check(r.ok and "evil" not in json.loads(settings(A)["look"]) and json.loads(settings(A)["look"])["theme"] == "light", "look: unknown keys are dropped")
before = settings(A)["look"]
for bad in ('["theme"]', "not json", json.dumps({"theme": {"a": 1}}), json.dumps({"theme": "x" * 41}), json.dumps({"fsize": [1]}),
            json.dumps({"theme": None}), "7"):
    r = A.patch(B + "/api/settings", json={"look": bad})
    check(r.status_code == 400, f"look: refused {bad[:30]!r} -> {r.status_code}")
check(settings(A)["look"] == before, "look: refused values store nothing")
check(A.patch(B + "/api/settings", json={"look": {"theme": "dark"}}).status_code == 400, "look: an object instead of the text is refused")
check(A.patch(B + "/api/settings", json={"look": ""}).ok and settings(A)["look"] == "", "look: '' = reset to never saved")
check(A.patch(B + "/api/settings", json={"look": "{}"}).ok and settings(A)["look"] == "{}", "look: '{}' = saved defaults")
# freelancer-matrix: settings
FID, Fr = freelancer(B, A)
check(Fr.patch(B + "/api/settings", json={"look": json.dumps({"accent": "pink"})}).ok and json.loads(settings(Fr)["look"]) == {"accent": "pink"},
      "freelancer: saves and reads the appearance")

# ================================================================== #2156 activity per organisation  # freelancer-matrix: admin (403 for Fr below)
r = A.get(B + "/api/admin/orgs/activity")
check(r.ok, "activity: admin " + r.text[:120])
j = r.json()
check(isinstance(j.get("orgs"), list) and isinstance(j.get("private"), dict), f"activity: shape {list(j)}")
row = next((o for o in j["orgs"] if o["id"] == ORG), None)
check(row and row["name"] == "Alpha Studio" and row["members"] == 2, f"activity: the organisation with its members {row}")
check(row and set(row) == {"id", "name", "members", "last_login", "storage_bytes", "lists", "tasks"}, f"activity: only numbers and the name {row and set(row)}")
check(row and (row["last_login"] or "")[:2] == "20" and len(row["last_login"]) == 10, f"activity: last sign-in is a date {row and row['last_login']}")
check(set(j["private"]) == {"members", "last_login", "storage_bytes", "lists", "tasks"}, "activity: the row without organisation")
check(j["private"]["members"] >= 2, f"activity: people without an organisation are counted (carol, frida) {j['private']}")
txt = r.text.lower()
check(not any(x in txt for x in ("alice", "bob", "carol", "frida", "example.com", "username", "display_name")), "activity: no names or addresses")
check(Bo.get(B + "/api/admin/orgs/activity").status_code == 403 and Fr.get(B + "/api/admin/orgs/activity").status_code == 403, "activity: members get 403")
LS = A.post(B + "/api/lists", json={"name": "Shots", "org_id": ORG}).json()["id"]
A.post(B + "/api/tasks", json={"title": "Plan", "list_id": LS})
row = next(o for o in A.get(B + "/api/admin/orgs/activity").json()["orgs"] if o["id"] == ORG)
check(row["lists"] >= 1 and row["tasks"] >= 1, f"activity: lists and tasks counted {row}")
tk = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "admin-read"], "expires_days": 30}).json()["token"]
r = requests.get(B + "/api/v1/admin/orgs/activity", headers={"Authorization": "Bearer " + tk})
check(r.ok and r.json()["orgs"][0]["name"] == "Alpha Studio", "activity: API v1 with admin-read " + r.text[:100])
tk2 = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "admin-read"], "expires_days": 30}).json().get("token", "")
r = requests.get(B + "/api/v1/admin/orgs/activity", headers={"Authorization": "Bearer " + tk2})
check(r.status_code in (401, 403), f"activity: API v1 refuses a member {r.status_code}")
tk3 = A.post(B + "/api/me/tokens", json={"name": "r", "scopes": ["read"], "expires_days": 30}).json()["token"]
check(requests.get(B + "/api/v1/admin/orgs/activity", headers={"Authorization": "Bearer " + tk3}).status_code == 403, "activity: API v1 without the scope is 403")

# ================================================================== #2259 old terms PDFs go
import hashlib  # noqa: E402


def pdf(tag):
    return b"%PDF-1.4\n% invented terms " + tag.encode() + b"\n" + os.urandom(32).hex().encode() + b"\n%%EOF\n"


def up(s, lang, data, date="2026-09-01"):
    r = s.post(B + f"{T}/{lang}", files={"file": ("AGB.pdf", data, "application/pdf")}, data={"date": date})
    assert r.ok, r.text
    return f"terms-{lang}-{hashlib.sha256(data).hexdigest()[:16]}.pdf"


def where(oid, name):
    return f"/data/office/{oid}/{name}"


def exists(oid, name):
    return subprocess.run(["docker", "exec", CT, "test", "-f", where(oid, name)]).returncode == 0


def age(oid, name, days=40):
    subprocess.run(["docker", "exec", CT, "touch", "-d", f"{days} days ago", where(oid, name)], check=True)


def old_current(oid, lang):  # the current state was set long ago
    r = sql("SELECT data FROM office_settings WHERE org_id=?", (oid,))[0][0]
    d = json.loads(r)
    d["terms"][lang]["uploaded_at"] = "2026-01-01T10:00:00+00:00"
    sql("UPDATE office_settings SET data=? WHERE org_id=?", (json.dumps(d), oid), write=True)


def purge():
    code = ("import app\nfrom kalmido.office.terms import agb_purge_tick\nc = app.connect()\n"
            "try:\n    print('purged', agb_purge_tick(c))\nfinally:\n    c.close()")
    out = subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True)
    return out.stdout + out.stderr


A.put(B + "/api/office/settings", json={"lang": "de", "currency": "EUR", "company_fields": {
    "name": "Studio Nordlicht GmbH", "street": "Hafenstrasse 12", "zip": "20457", "city": "Hamburg", "country": "DE", "email": "hallo@nordlicht.example",
    "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}, "payment_days": 14})
CL = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Koeln", "country": "DE",
                                       "email": "kunde@example.com"}).json()["id"]
t1 = up(A, "de", pdf("1"))
q = A.post(B + "/api/office/docs", json={"client_id": CL, "items": [{"title": "Cut", "qty": 1, "rate": 100}]}).json()["id"]
check(A.post(B + f"/api/office/docs/{q}/finalize").ok, "terms: a quotation finalised with state 1")
t2 = up(A, "de", pdf("2"))
t3 = up(A, "de", pdf("3"))
t4 = up(A, "de", pdf("4"))  # the current one
for n in (t1, t2):
    age(ORG, n)
old_current(ORG, "de")  # t3 keeps its young file time: it was replaced just now
check(all(exists(ORG, n) for n in (t1, t2, t3, t4)), "terms: four files stored")
out = purge()
check("purged 1" in out, "terms: one file purged " + out[-200:])
check(exists(ORG, t1), "terms: the state a quotation names stays")
check(not exists(ORG, t2), "terms: an old state nobody names is gone")
check(exists(ORG, t3), "terms: a state replaced less than 30 days ago stays")
check(exists(ORG, t4) and A.get(B + f"{T}/de/file").status_code == 200, "terms: the current one stays and opens")
age(ORG, t3)
check("purged 1" in purge() and not exists(ORG, t3) and exists(ORG, t1) and exists(ORG, t4), "terms: a month later t3 goes, referenced and current stay")
# a replaced state is aged from when it stopped being current, not from its upload
t5 = up(A, "en", pdf("5"))
t6 = up(A, "en", pdf("6"))
age(ORG, t5, 1)
old_current(ORG, "en")
check("purged 0" in purge() and exists(ORG, t5), "terms: young replaced file stays")
# a person without an organisation  # freelancer-matrix: office: the personal office
f1 = up(Fr, "en", pdf("f1"))
f2 = up(Fr, "en", pdf("f2"))
FO = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
age(FO, f1)
old_current(FO, "en")
out = purge()
check(not exists(FO, f1) and exists(FO, f2), "freelancer: the personal office's old state goes, the current stays " + out[-120:])
check(exists(ORG, t6) and exists(ORG, t5), "freelancer: other offices untouched")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
