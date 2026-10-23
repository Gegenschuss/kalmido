#!/usr/bin/env python3
"""2.217.0 B (#2797) API tests, own container (start.sh): the starts "Office & finance" and "Team" switch the module
Agents on too -- in the first-run setup and when a person picks the purpose -- also for a person without an organisation
(new people get it since 2.22.0 #739 anyway; the setting-up admin and anyone who switched it off did not).
Nothing is migrated: a user who does not pick one of them keeps the modules as they are; the switch "Switch on all
modules" off still means lists and tasks only.
"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402

subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
feats = lambda s: set((s.get(B + "/api/state").json()["settings"].get("features") or "").split(",")) - {""}  # noqa: E731

# ---- the first-run setup with "Office & finance" (no organisation name = private only, a freelancer)
r = A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "purpose": "office",
                                          "modules": ["cal", "timeline", "kanban", "comments", "progress", "deps", "fields", "events", "contacts"]})
check(r.ok, f"setup with the purpose office {r.status_code} {r.text[:200]}")
fa = feats(A)
check({"agents", "clients", "office", "forms", "workload"} <= fa, f"#2797: Office & finance switches Agents on with the business modules {fa}")
check(not (A.get(B + "/api/orgs").json().get("orgs") or []), "#2797: setup without an organisation (P4)")

# ---- people who pick a purpose later (welcome tour / Settings > Modules), none of them in an organisation
for u in ("bob", "carol", "dave"):
    check(A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"}).ok, u)
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
check("agents" in feats(Da), "#739: a new person starts with Agents on (only the setting-up admin did not)")
for s in (Bo, Ca, Da):  # each of them switched Agents off in Settings > Modules
    s.patch(B + "/api/settings", json={"features": ",".join(sorted(feats(s) - {"agents"}))})
check(not any("agents" in feats(s) for s in (Bo, Ca, Da)), "setup: Agents off for bob, carol, dave")
fs = set(Bo.post(B + "/api/me/purpose", json={"purpose": "team", "examples": False}).json()["features"].split(","))
check("agents" in fs and "collab" in fs, f"#2797: Team switches Agents on {fs}")
fs = set(Ca.post(B + "/api/me/purpose", json={"purpose": "office", "examples": False}).json()["features"].split(","))
check({"agents", "office", "clients"} <= fs, f"#2797: Office & finance (a person without an organisation) switches Agents on {fs}")
for p in ("me", "home", "family", "software"):
    fs = set(Da.post(B + "/api/me/purpose", json={"purpose": p, "examples": False}).json()["features"].split(","))
    check("agents" not in fs, f"#2797: {p} leaves Agents as it is (off) {fs}")
check("agents" not in feats(Da), "#2797: dave keeps Agents off")

# ---- the purpose switch never switches Agents off again (an extra module); the switch off still does
fs = set(Bo.post(B + "/api/me/purpose", json={"purpose": "me", "examples": False}).json()["features"].split(","))
check("agents" in fs, f"#2797: back to For me keeps Agents on (extra modules are never switched off by a purpose) {fs}")
fs = set(Bo.post(B + "/api/me/purpose", json={"purpose": "team", "all_modules": False}).json()["features"].split(",")) - {""}
check("agents" not in fs, f"#1591: Team + the switch off = lists and tasks only, Agents too {fs}")

# ---- the client tables say the same (static/js/account.js)
src = open(os.path.join(N, "..", "static", "js", "account.js"), encoding="utf-8").read()
check("const PURPOSE_EXTRA = {office: ['clients', 'workload', 'forms', 'office', 'agents'], team: ['agents']};" in src,
      "#2797: the client's PURPOSE_EXTRA matches the server")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
