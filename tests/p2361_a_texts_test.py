#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.361.0 A (#2938): texts that assumed an organisation or an admin. Own container in mode workspaces.
 - backend refusals say "workspace" (not "organisation") for an area's members: leave quota / approval, absences for others
 - a person without an organisation (freelancer fixture; freelancer-matrix: hub) never gets an organisation text back
 - the client code: the old organisation / admin sentences are gone, the private variants exist (clients, dispo, share
   dialogs, newsletter 403 only), every translation file has them
usage: p2361_a_texts_test.py <datadir>      (P2361A_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer, org_join  # noqa: E402

ROOT = os.path.dirname(N)
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402


def src(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def msg(r):
    try:
        return r.json().get("error", "")
    except ValueError:
        return r.text


# ---------------------------------------------------------------- static: backend + client sources
OLD_ADMIN = "Only an admin of this organisation can do this"
for rel in ("office/docs.py", "office/invoices.py", "office/agentdocs.py", "office/ledger.py", "office/otrash.py", "office/timebill.py", "office/model.py", "office/rights.py"):
    s = src("kalmido/" + rel)
    check(OLD_ADMIN not in s and "Only an admin of this workspace can do this" in s, f"{rel}: the refusal names the workspace")
for rel in ("hub/leave.py", "hub/absence.py", "docs/web.py"):
    s = src("kalmido/" + rel)
    check("Only admins of the organisation" not in s and "Only admins of this workspace" in s, f"{rel}: the refusal names the workspace")
OLD_JS = {"clients.js": ["Only people of your organisation", "people of your organisation", "'Organisation'"],
          "dispo.js": ["add people to the organisation", "'Organisation'"], "absence.js": ["admins of the organisation", "'Organisation'"],
          "core.js": ["within your organisation", "person of your organisation"], "chat.js": ["ask an admin to set up"],
          "dashboard.js": ["Ask your admin"], "render.js": ["ask your admin"], "newsletter.js": ["Only admins of the organisation"],
          "dialogs.js": ["An admin can add them"], "sharedlg.js": ["An admin can add them"]}
for f, olds in OLD_JS.items():
    s = src("static/js/" + f)
    check(not any(o in s for o in olds), f"{f}: no organisation / admin sentence left ({[o for o in olds if o in s]})")
check("noPeopleTxt()" in src("static/js/dialogs.js") and "noPeopleTxt()" in src("static/js/sharedlg.js"), "share dialogs use the e-mail way text")
check("e.status === 403" in src("static/js/newsletter.js"), "newsletter: only a 403 says 'admins'")
check("wsCur() === 'private'" in src("static/js/clients.js") and "wsCur() === 'private'" in src("static/js/dispo.js"), "private variants of the empty client / dispo texts")
import json  # noqa: E402
for lg in ("de", "fr", "es", "it", "nl"):
    d = json.load(open(os.path.join(ROOT, "static/i18n", lg + ".json"), encoding="utf-8"))
    for k in ("Nothing to show yet: add equipment in Office & finance.", "No other people yet. Share by e-mail address or invite them.",
              "The newsletter settings could not be loaded.", "Only an admin of this workspace can do this"):
        check(d.get(k), f"{lg}: translated '{k[:40]}'")
check(json.load(open(os.path.join(ROOT, "static/i18n/de.json"), encoding="utf-8"))["Clients sit above your projects: hours, budget and the timesheet per client. Only you see them."].endswith("Nur du siehst sie."),
      "de: 'Nur du siehst sie.' for private clients")

# ---------------------------------------------------------------- runtime
if os.environ.get("P2361A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
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
Ca = sess("carol")
Ca.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "workspace": f"org:{ORG}"})

r = Ca.put(B + "/api/team/leave/quota", json={"user_id": CAROL, "year": 2026, "days": 30, "org": ORG})
check(r.status_code == 403 and "workspace" in msg(r) and "organisation" not in msg(r), f"member: leave quota refused with the workspace text ({r.status_code} {msg(r)})")
r = Ca.put(B + "/api/team/leave/approval", json={"on": True, "org": ORG})
check(r.status_code == 403 and "workspace" in msg(r) and "organisation" not in msg(r), f"member: approval switch refused with the workspace text ({r.status_code} {msg(r)})")
r = Ca.post(B + "/api/team/absences", json={"user_id": BOB, "kind": "vacation", "start_date": "2026-11-02", "org": ORG})
check(r.status_code == 403 and "workspace" in msg(r) and "organisation" not in msg(r), f"member: absence for another person refused ({r.status_code} {msg(r)})")

# freelancer-matrix: hub
FID, Fr = freelancer(B, A)
r = Fr.post(B + "/api/team/absences", json={"user_id": BOB, "kind": "vacation", "start_date": "2026-11-02"})
check(not r.ok and "organisation" not in msg(r).lower(), f"freelancer: an absence for somebody else is refused without an organisation text ({r.status_code} {msg(r)})")
r = Fr.put(B + "/api/team/leave/quota", json={"user_id": FID, "year": 2026, "days": 25})
check(r.ok, f"freelancer: is the admin of the own area and sets the own account ({r.status_code} {msg(r)})")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
