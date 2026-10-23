#!/usr/bin/env python3
"""2.154.0 D (#1876) the industry pack of a new shoot calculation part is chosen when the part is created: only a pack that is
switched on (else 400), without "pack" the film pack (or the first one on), existing parts keep their pack. A second pack
is an own pack file in the data folder. A person without an organisation does the same (freelancer-matrix: office).
usage: p2154_d_pack_test.py <datadir>      (a fresh container; P2154DP_NOSTART=1 = the server already runs)"""
import json
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
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def run(s, tag):
    D = B + "/api/office/docs"
    r = s.put(B + "/api/office/settings", json={"industry_packs": ["film"]})
    check(r.ok, tag + ": film on " + r.text[:200])
    doc = s.post(D, json={"kind": "offer"}).json()
    did = doc["id"]

    def add(**kw):
        return s.post(f"{D}/{did}/parts", json={"kind": "shoot", **kw})

    def pack_of(r):
        return ((r.json().get("part") or {}).get("sheet") or {}).get("pack")
    r = add()
    check(r.status_code == 201 and pack_of(r) == "film", tag + ": default = film " + r.text[:200])
    check(add(pack="docu").status_code == 400, tag + ": a pack that is not switched on = 400")
    check(add(pack=7).status_code == 400, tag + ": a bad pack value = 400")
    r = s.put(B + "/api/office/settings", json={"industry_packs": ["film", "docu"]})
    check(r.ok and "docu" in r.text, tag + ": docu on " + r.text[:200])
    r = add(pack="docu")
    check(r.status_code == 201 and pack_of(r) == "docu", tag + ": chosen pack " + r.text[:200])
    check(pack_of(add()) == "film", tag + ": no choice = film while it is on")
    parts = s.get(f"{D}/{did}").json().get("parts") or []
    packs = [(p.get("sheet") or {}).get("pack") for p in parts if p["kind"] == "shoot"]
    check(packs == ["film", "docu", "film"], tag + f": every part keeps its pack {packs}")


if not os.environ.get("P2154DP_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
# the second pack: an own pack file of the data folder (start.sh wipes the folder, so after it; read again when it changes)
os.makedirs(os.path.join(DATA, "packs", "industry"), exist_ok=True)
src = os.path.join(N, "..", "kalmido", "office", "packs", "industry", "film.json")
d = json.load(open(src, encoding="utf-8"))
d["code"], d["name"] = "docu", {"de": "Dokumentation", "en": "Documentary"}
json.dump(d, open(os.path.join(DATA, "packs", "industry", "docu.json"), "w", encoding="utf-8"))
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "cal,comments,collab,clients,office"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
run(A, "org")

# freelancer-matrix: office
FID, F = freelancer(B, A)
run(F, "freelancer")

print(f"p2154_d_pack: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
