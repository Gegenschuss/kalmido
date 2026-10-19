#!/usr/bin/env python3
"""2.122.3 API tests, part A (#2335): the one-off office imports moved to Settings > Import legacy data keep their routes
and rights. Own container (start.sh), invented companies and people only (@example.com).
freelancer-matrix: office
 - the fixed costs template (GET .../fixed-costs/import/template) is an .xlsx the preview reads (two example rows,
   nothing stored); the leads CSV import: preview (nothing stored) and take over, a duplicate e-mail skipped
 - a person without an organisation does the same in the personal office (own admin)
 - an organisation member without the office admin right: 403 on template, preview and leads import (as before)
usage: p21223_a_api_test.py <datadir>      (a fresh container; P21223A_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
F = "/api/office/fixed-costs"
L = "/api/office/leads/import"
CSV = "Name;Company;E-mail;Phone\nErika Beispiel;Beispiel Studio;erika@example.com;0301234\nMax Muster;Muster AG;max@example.com;\n"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def fixed_count(s):
    r = s.get(B + F)
    return len(r.json().get("items") or r.json().get("fixed") or []) if r.ok else -1


def imports(s, who):
    """template -> preview -> nothing stored; leads preview -> take over (the second run: duplicates skipped)."""
    n0 = fixed_count(s)
    t = s.get(B + F + "/import/template")
    check(t.ok and t.content[:2] == b"PK", f"{who}: the template is an .xlsx ({t.status_code})")
    r = s.post(B + F + "/import/preview", files={"file": ("template.xlsx", t.content)})
    check(r.ok and len(r.json().get("rows") or []) == 2, f"{who}: the preview reads the template's two rows {r.status_code} {r.text[:200]}")
    check(fixed_count(s) == n0, f"{who}: the preview stores nothing")
    r = s.post(B + L, json={"text": CSV})
    check(r.ok and r.json().get("count") == 2, f"{who}: the leads preview {r.status_code} {r.text[:200]}")
    r = s.post(B + L, json={"text": CSV, "commit": True})
    check(r.status_code in (200, 201) and r.json().get("count") == 2, f"{who}: two leads taken over {r.status_code} {r.text[:200]}")
    r = s.post(B + L, json={"text": CSV})
    check(r.ok and r.json().get("count") == 0 and r.json().get("dup_count") == 2, f"{who}: again = duplicates skipped {r.text[:200]}")


if not os.environ.get("P21223A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,clients,office"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})

# ---- the organisation's admin
imports(A, "the admin")

# ---- a member without the office admin right: refused as before
t = A.get(B + F + "/import/template").content
check(Bo.get(B + F + "/import/template").status_code == 403, "a member: template 403")
check(Bo.post(B + F + "/import/preview", files={"file": ("template.xlsx", t)}).status_code == 403, "a member: preview 403")
check(Bo.post(B + F + "/import", json={"items": []}).status_code == 403, "a member: take over 403")
check(Bo.post(B + L, json={"text": CSV}).status_code == 403, "a member: leads import 403")

# ---- a person without an organisation: the personal office, own admin
FID, Fr = freelancer(B, A)
imports(Fr, "the freelancer")

print(f"p21223_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
