#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.624.0 API tests, part A (#3946): folders hidden in the calendar. Own container (start.sh).
 - the account setting cal_folders_hidden (json list of the person's own sidebar folder paths, next to cal_lists_hidden):
   default "[]", stored sorted without doubles (list or json text), bad values 400 (not a list, numbers, empty names, paths
   not in their stored form, more than 500), another person's settings untouched
 - a renamed / moved folder takes its entry along (also a subfolder below it), a deleted folder leaves the list without
   passing its "hidden" to the parent folder (its subfolder's own entry moves up one level)
 - a person without an organisation (tests/freelancer_fixture.py) stores and reads it the same way
usage: p2624_a_calfolders_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import check, done, sess  # shared helpers (tests/kt.py)
from freelancer_fixture import freelancer

subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,events,timeline"})
A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": "cal"})


def hidden(s):
    return json.loads(s.get(B + "/api/state").json()["settings"]["cal_folders_hidden"])


# ================================================================== the setting
check(A.get(B + "/api/state").json()["settings"].get("cal_folders_hidden") == "[]", "default: no folder hidden")
r = A.patch(B + "/api/settings", json={"cal_folders_hidden": ["Clients/Acme", "Clients", "Clients"]})
check(r.ok, f"a list of paths is stored ({r.status_code} {r.text[:200]})")
check(hidden(A) == ["Clients", "Clients/Acme"], f"stored sorted, without doubles ({hidden(A)})")
check(A.patch(B + "/api/settings", json={"cal_folders_hidden": json.dumps(["Büro / ä"])}).status_code == 400, "a path not in its stored form (spaces around the separator) 400")
check(A.patch(B + "/api/settings", json={"cal_folders_hidden": json.dumps(["Büro/ä"])}).ok and hidden(A) == ["Büro/ä"], f"json text accepted, umlauts kept ({hidden(A)})")
for v in ([1, 2], ["x", 3], [""], ["a//b"], [" a"], [None], "nope", {"a": 1}, [True]):
    r = A.patch(B + "/api/settings", json={"cal_folders_hidden": v})
    check(r.status_code == 400, f"bad value {v!r}: 400 ({r.status_code})")
check(A.patch(B + "/api/settings", json={"cal_folders_hidden": [f"F{i}" for i in range(501)]}).status_code == 400, "more than 500 entries 400")
check(hidden(A) == ["Büro/ä"], f"a refused value stores nothing ({hidden(A)})")
check(hidden(Bo) == [], "another person's setting untouched")
check(A.patch(B + "/api/settings", json={"cal_folders_hidden": ""}).ok and hidden(A) == [], "empty = nothing hidden")
# the list ids stay as they were (cal_lists_hidden only ints)
check(A.patch(B + "/api/settings", json={"cal_lists_hidden": ["Clients"]}).status_code == 400, "cal_lists_hidden still takes no paths")

# ================================================================== rename / move / delete take the entry along
L1 = A.post(B + "/api/lists", json={"name": "Website", "folder": "Clients/Acme"}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Shop", "folder": "Clients/Acme/Shop"}).json()["id"]
check(L1 and L2, "two lists in a folder and its subfolder")
check(A.patch(B + "/api/settings", json={"cal_folders_hidden": ["Clients/Acme", "Clients/Acme/Shop", "Other"]}).ok, "folders hidden")
r = A.post(B + "/api/folders/rename", json={"old": "Clients/Acme", "new": "Clients/Acme Ltd"})
check(r.ok, f"rename ({r.status_code} {r.text[:200]})")
check(sorted(hidden(A)) == ["Clients/Acme Ltd", "Clients/Acme Ltd/Shop", "Other"],
      f"renamed folder and its subfolder keep their entry ({hidden(A)})")
r = A.post(B + "/api/folders/delete", json={"name": "Clients/Acme Ltd"})
check(r.ok, f"delete ({r.status_code} {r.text[:200]})")
check(sorted(hidden(A)) == ["Clients/Shop", "Other"], f"deleted folder: its entry gone, the parent not hidden, the subfolder's entry up one level ({hidden(A)})")
lists = {x["id"]: x for x in A.get(B + "/api/state").json()["lists"]}
check(lists[L1].get("folder") == "Clients" and lists[L2].get("folder") == "Clients/Shop", f"the lists moved up ({lists[L1].get('folder')} {lists[L2].get('folder')})")
check(A.patch(B + "/api/settings", json={"cal_folders_hidden": []}).ok, "back to the default")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
Fr.post(B + "/api/lists", json={"name": "Private project", "folder": "Mine"})
check(Fr.get(B + "/api/state").json()["settings"].get("cal_folders_hidden") == "[]", "freelancer: default")
check(Fr.patch(B + "/api/settings", json={"cal_folders_hidden": ["Mine"]}).ok and hidden(Fr) == ["Mine"], "freelancer: a private folder hidden")
check(Fr.patch(B + "/api/settings", json={"cal_folders_hidden": [7]}).status_code == 400, "freelancer: bad value 400")
check(Fr.post(B + "/api/folders/rename", json={"old": "Mine", "new": "Ours"}).ok and hidden(Fr) == ["Ours"], f"freelancer: rename takes it along ({hidden(Fr)})")
check(hidden(A) == [], "freelancer's setting does not touch the admin's")

sys.exit(done("p2624_a_calfolders"))
