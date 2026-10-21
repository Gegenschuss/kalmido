#!/usr/bin/env python3
"""2.148.0 API tests, part C (#2472, office: the procedure documentation (GoBD), prefilled, versions, Markdown / PDF), own
container (start.sh, org encryption on). Invented companies and people only. freelancer-matrix: office  tenant-matrix: office
 - an organisation's admin: the template is prefilled (company from the structured company data, members with name and role,
   never mail addresses), gaps are marked; saving = version 1, 2 (base check: 409 on a stale base); the saved data are
   encrypted at rest; an old version reads as it was (own text + the prefilled text of that moment); the versions list;
   Markdown has all five sections, the version and the company; the PDF starts with %PDF; unknown fields / wrong types 400;
   unknown version 404; every save is in the office log
 - a member without the admin role and an accounting member: read (also the exports), never save (403)
 - another organisation: sees none of it (own empty state), a foreign version number is simply unknown (404)
 - a person without organisation (personal office, its own admin): everything works
usage: p2148_c_api_test.py <datadir>"""
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
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs"
P = "/api/office/procdoc"
SECTIONS = ("general", "user", "tech", "ops", "ics")


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


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def field(d, key):
    return next(f for s in d["sections"] for f in s["fields"] if f["key"] == key)


if not (os.environ.get("P2148C_NOSTART") or os.environ.get("KMT_NOSTART")):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Numbers")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
r = A.put(B + f"/api/orgs/{ORG}/members", json={"email": "dave@example.com", "role": "accounting"})
assert r.ok, r.text
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Da, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A, "erin")  # freelancer-matrix: office (the personal office, its own admin)

r = A.put(B + "/api/office/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "street": "Example Road 1", "zip": "12345",
                                                                "city": "Sampletown", "country": "DE"}})
check(r.ok, "company data set " + r.text[:200])

# ---------------------------------------------------------------- the organisation's admin
r = A.get(B + P)
check(r.ok, "GET procdoc " + r.text[:200])
d = r.json()
check(d["version"] == 0 and d["viewing"] == 0 and d["can_edit"] == 1, f"no version yet, the admin may edit {d.get('version')} {d.get('can_edit')}")
check([s["key"] for s in d["sections"]] == list(SECTIONS) and [s["no"] for s in d["sections"]] == ["1", "2", "3", "4", "5"], "five GoBD sections in order")
co = field(d, "company")
check("Alpha Studio GmbH" in co["auto"] and "Sampletown" in co["auto"], "company prefilled from the company data " + co["auto"][:200])
check(d["gap_marker"] in co["auto"] and co["gap"] == 1, "the legal form is a marked gap")
org = field(d, "organisation")["auto"]
check("Alice Admin" in org and "Bob Member" in org and "Dave Numbers" in org and "(Admin)" in org and "(Accounting)" in org, "members with name and role " + org[:300])
check("@example.com" not in json.dumps(d), "no mail addresses in the document")
check(d["gaps"] >= 5, f"gaps counted {d['gaps']}")
check(field(d, "periods")["auto"] and field(d, "numbers")["auto"].count("\n") >= 4, "periods and number ranges prefilled")
check(d["company"] == "Alpha Studio GmbH", "company in the head")

r = A.put(B + P, json={"own": {"company": "GmbH, film production (test v1)", "backup": "Copies kept at an example place"}, "base": 0})
check(r.ok, "save version 1 " + r.text[:200])
d1 = r.json()
check(d1["version"] == 1 and field(d1, "company")["own"] == "GmbH, film production (test v1)" and field(d1, "company")["gap"] == 0, "version 1, the own text fills the gap")
check(A.put(B + P, json={"own": {"company": "stale"}, "base": 0}).status_code == 409, "a stale base: 409")
r = A.put(B + P, json={"own": {"company": "GmbH, film production (test v2)"}, "base": 1})
check(r.ok and r.json()["version"] == 2, "save version 2 " + r.text[:200])
check(A.put(B + P, json={"own": {"nonsense": "x"}}).status_code == 400, "unknown field: 400")
check(A.put(B + P, json={"own": {"company": 5}}).status_code == 400, "a number as text: 400")
check(A.put(B + P, json={"own": {"company": "x" * 20001}}).status_code == 400, "too long: 400")
rows = sql("SELECT version, data FROM office_procdocs WHERE org_id=? ORDER BY version", (ORG,))
check([x[0] for x in rows] == [1, 2] and all(str(x[1]).startswith("kenc1:") for x in rows), f"two versions, encrypted at rest {[x[0] for x in rows]}")
check(A.get(B + P).json()["version"] == 2 and field(A.get(B + P).json(), "company")["own"] == "GmbH, film production (test v2)", "current = version 2")

# an old version reads as it was, also after the company changed
A.put(B + "/api/office/settings", json={"company_fields": {"name": "Alpha Renamed GmbH"}})
r = A.get(B + P + "?version=1")
check(r.ok, "GET version 1 " + r.text[:200])
v1 = r.json()
check(v1["viewing"] == 1 and field(v1, "company")["own"] == "GmbH, film production (test v1)" and "Alpha Studio GmbH" in field(v1, "company")["auto"]
      and field(v1, "backup")["own"] == "Copies kept at an example place", "version 1 as saved (own + prefilled of that moment)")
check("Alpha Renamed GmbH" in field(A.get(B + P).json(), "company")["auto"], "the current state is prefilled anew")
check(A.get(B + P + "?version=99").status_code == 404 and A.get(B + P + "?version=x").status_code == 400, "unknown version 404, bad 400")
vs = A.get(B + P + "/versions").json()["items"]
check([v["version"] for v in vs] == [2, 1] and vs[0]["created_by"] == "Alice Admin", f"versions newest first {vs}")

r = A.get(B + P + ".md")
check(r.ok and "markdown" in r.headers.get("Content-Type", ""), "Markdown export " + str(r.status_code))
md = r.text
check(all(f"\n## {n} " in md for n in "12345") and "Version 2" in md and "Alpha Renamed GmbH" in md, "Markdown: five sections, version, company " + md[:300])
check("GmbH, film production (test v2)" in md and "### 1.1 " in md, "Markdown: own texts and subsections")
md1 = A.get(B + P + ".md?version=1").text
check("Version 1 " in md1 and "test v1" in md1 and "Alpha Studio GmbH" in md1, "Markdown of version 1")
r = A.get(B + P + ".pdf?version=1")
check(r.ok and r.content[:4] == b"%PDF" and r.headers.get("Content-Type") == "application/pdf", "PDF of version 1")
check(A.get(B + P + ".pdf").content[:4] == b"%PDF", "PDF of the current state")
log = sql("SELECT action, target FROM office_doc_log WHERE org_id=? AND target='procdoc'", (ORG,))
check(sum(1 for x in log if x[0] == "procdoc") == 2 and any(x[0] == "export" for x in log), f"saves and exports in the office log {log}")

# ---------------------------------------------------------------- rights
for who, s in (("member", Bo), ("accounting", Da)):
    r = s.get(B + P)
    check(r.ok and r.json()["version"] == 2 and r.json()["can_edit"] == 0, f"{who} reads (can_edit 0) " + r.text[:200])
    check(s.get(B + P + "/versions").ok and s.get(B + P + ".md").ok and s.get(B + P + ".pdf?version=1").ok, f"{who} reads versions and exports")
    check(s.put(B + P, json={"own": {"company": "not allowed"}}).status_code == 403, f"{who} may not save: 403")
check(len(sql("SELECT 1 FROM office_procdocs WHERE org_id=?", (ORG,))) == 2, "no version from the refused saves")

r = Ca.get(B + P)
check(r.ok and r.json()["version"] == 0 and "Alpha" not in json.dumps(r.json()), "another organisation sees none of it")
check(Ca.get(B + P + "?version=1").status_code == 404 and Ca.get(B + P + ".md?version=2").status_code == 404, "another organisation: a foreign version 404")
check(Ca.get(B + P + "/versions").json()["items"] == [], "another organisation: no versions")

# ---------------------------------------------------------------- a person without organisation (P4)
r = Fr.get(B + P)
check(r.ok and r.json()["can_edit"] == 1 and "Personal office" in field(r.json(), "organisation")["auto"], "freelancer: the personal office " + r.text[:200])
check("Erin (Admin)" in field(r.json(), "organisation")["auto"], "freelancer: the owner as admin")
r = Fr.put(B + P, json={"own": {"company": "Sole trader (test)"}, "base": 0})
check(r.ok and r.json()["version"] == 1, "freelancer: version 1 " + r.text[:200])
check(Fr.put(B + P, json={"own": {"company": "Sole trader (test 2)"}}).json()["version"] == 2, "freelancer: version 2")
check("test)" in Fr.get(B + P + "?version=1").text and Fr.get(B + P + "/versions").json()["items"][0]["version"] == 2, "freelancer: old version + list")
check("Sole trader (test 2)" in Fr.get(B + P + ".md").text and Fr.get(B + P + ".pdf").content[:4] == b"%PDF", "freelancer: Markdown + PDF")
check(A.get(B + P).json()["version"] == 2 and "Sole trader" not in A.get(B + P + ".md").text, "the organisation does not see the personal office")
check(Bo.get(B + P + "?version=1").json()["viewing"] == 1 and "Sole trader" not in Bo.get(B + P + "?version=1").text, "versions stay per office area")

# German document language
r = A.get(B + P + "?lang=de")
check(r.ok and r.json()["sections"][0]["title"] == "Allgemeine Beschreibung" and r.json()["gap_marker"] == "[ ... ausfüllen ]", "German template")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
