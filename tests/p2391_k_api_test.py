#!/usr/bin/env python3
"""2.39.1 API tests (agent K).
 - #1219 the inbox is shown as "Basket" (German "Korb"): a new person's inbox is named in their language, the old default
   names ("Inbox", "Eingang", ...) still count as default names (shown in the viewer's language); is_inbox stays
 - #1185 the sidebar setting knows the new group "areas" (and still refuses unknown groups)
 - #1221 the user setting group_order: json route key -> [group ids], validated, '' / {} = back to the default
usage: p2391_k_api_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})

# ================= #1219 the basket
st = A.get(B + "/api/state").json()
names = st.get("inbox_names") or []
for n in ("Basket", "Korb", "Inbox", "Eingang", "Boîte de réception", "Panier", "Cesta", "Raccolta", "Mand"):
    check(n in names, "#1219: a default name of the inbox: " + n + " " + json.dumps(names, ensure_ascii=False))
ib = [x for x in st["lists"] if x.get("is_inbox")]
check(len(ib) == 1, "#1219: one inbox, is_inbox stays")
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "lang": "de"})
check(r.ok, "a second person " + r.text[:200])
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "de"})
bib = [x for x in Bo.get(B + "/api/state").json()["lists"] if x.get("is_inbox")]
check(len(bib) == 1 and bib[0]["name"] in ("Eingang", "Basket"), "#1219: a new inbox gets the new default name " + json.dumps(bib, ensure_ascii=False)[:200])
check(A.delete(B + f"/api/lists/{ib[0]['id']}").status_code in (400, 403) and "basket" in A.delete(B + f"/api/lists/{ib[0]['id']}").text.lower(),
      "#1219: the error names the basket")

# ================= #1185 the sidebar: "areas"
r = A.patch(B + "/api/settings", json={"sidebar": json.dumps({"order": ["views", "areas", "lists", "focus"], "hidden": ["g:areas", "e:office"]})})
check(r.ok, "#1185: the group areas is a known group " + r.text[:200])
check(json.loads(A.get(B + "/api/state").json()["settings"]["sidebar"])["order"][:2] == ["views", "areas"], "#1185: stored")
check(A.patch(B + "/api/settings", json={"sidebar": json.dumps({"order": ["nope"], "hidden": []})}).status_code == 400, "#1185: an unknown group is refused")

# ================= #1221 group_order
check(A.get(B + "/api/state").json()["settings"].get("group_order") in ("{}", "", None), "#1221: no own order by default")
r = A.patch(B + "/api/settings", json={"group_order": json.dumps({"assigned": ["l:3", "l:1", "l:3"], "tag:x": ["l:2"], "all": []})})
check(r.ok, "#1221: an own order is stored " + r.text[:200])
go = json.loads(A.get(B + "/api/state").json()["settings"]["group_order"])
check(go == {"assigned": ["l:3", "l:1"], "tag:x": ["l:2"]}, "#1221: doubles dropped, an empty list removes the view " + json.dumps(go))
check(A.patch(B + "/api/settings", json={"group_order": {"assigned": ["l:1"]}}).ok, "#1221: an object is fine too")
for bad in ("[1]", json.dumps({"assigned": "l:1"}), json.dumps({"assigned": [1]}), json.dumps({"": ["l:1"]}), "{x"):  # 2.40.0 (#1334): too long / too many are cut, see p2400_v_api_test
    check(A.patch(B + "/api/settings", json={"group_order": bad}).status_code == 400, "#1221: refused " + bad[:60])
check(A.patch(B + "/api/settings", json={"group_order": ""}).ok and A.get(B + "/api/state").json()["settings"]["group_order"] == "{}", "#1221: '' resets")
check(Bo.get(B + "/api/state").json()["settings"].get("group_order") in ("{}", "", None), "#1221: per person")

print(f"{OKS[0]} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
