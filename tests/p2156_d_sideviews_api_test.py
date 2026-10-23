#!/usr/bin/env python3
"""2.156.0 API tests, part D (#2186): saved views of the sidebar, the user settings side_views (json list of views) and
side_view (the active one, '' = "Everything"). Own container (start.sh), invented people only.
 - a view is stored cleaned (doubles dropped, name trimmed, default icon); invalid values are refused with 400 and nothing
   is stored (wrong types, unknown id shape, too many, double ids, control characters, a bad start page)
 - create, change, delete = one PATCH of side_views each; the active view = side_view, read the same by a second session
   of the same person (another device)
 - another person sees none of it
 - a person without an organisation (the private space) works the same
freelancer-matrix: own
usage: p2156_d_sideviews_api_test.py <datadir>      (a fresh container; P2156D_NOSTART=1: the container runs already)"""
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


def views(s):
    st = s.get(B + "/api/state").json()["settings"]
    return json.loads(st.get("side_views") or "[]"), st.get("side_view")


if os.environ.get("P2156D_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Other", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text

ROAD = {"id": "road1", "name": "  On the road ", "open": ["focus", "lists", "focus"], "fclosed": ["Work"],
        "hide": ["g:views", "v:week", "l:12", "tag:errand", "v:week"], "start": "today"}
PLAN = {"id": "plan1", "name": "Planning", "icon": "cal", "open": ["lists", "views"], "hide": [], "start": "folder/Work%20stuff"}


def run(s, who):
    # ---- invalid values: 400, nothing stored
    base = views(s)[0]
    bad = ['"x"', '{"a":1}', '[1]', '[{"id":"A B","name":"x"}]', '[{"id":"ok","name":""}]', '[{"id":"ok","name":3}]',
           '[{"id":"ok","name":"x","icon":"<b>"}]', '[{"id":"ok","name":"x","open":"lists"}]', '[{"id":"ok","name":"x","open":["Bad Group"]}]',
           '[{"id":"ok","name":"x","hide":["noprefix"]}]', '[{"id":"ok","name":"x","hide":[5]}]', '[{"id":"ok","name":"x","hide":["v:a\\u0001b"]}]',
           '[{"id":"ok","name":"x","start":"javascript:alert(1)\\""}]', '[{"id":"ok","name":"x","fclosed":[""]}]',
           '[{"id":"ok","name":"a"},{"id":"ok","name":"b"}]', json.dumps([{"id": f"v{i}", "name": "x"} for i in range(21)])]
    for b in bad:
        r = s.patch(B + "/api/settings", data='{"side_views":' + b + '}', headers={"Content-Type": "application/json"})
        check(r.status_code == 400, f"{who}: invalid side_views refused: {b[:50]} -> {r.status_code}")
    for b in ('"Not An Id"', '5', '"a-b"'):
        r = s.patch(B + "/api/settings", data='{"side_view":' + b + '}', headers={"Content-Type": "application/json"})
        check(r.status_code == 400, f"{who}: invalid side_view refused: {b} -> {r.status_code}")
    check(views(s)[0] == base, f"{who}: nothing stored after the refusals")
    # ---- create (cleaned), the active one
    r = s.patch(B + "/api/settings", json={"side_views": [ROAD], "side_view": "road1"})
    check(r.ok, f"{who}: a view is stored {r.text[:200]}")
    vs, act = views(s)
    v = vs[0] if vs else {}
    check(v.get("name") == "On the road" and v.get("icon") == "panel" and v.get("open") == ["focus", "lists"]
          and v.get("hide") == ["g:views", "v:week", "l:12", "tag:errand"] and v.get("fclosed") == ["Work"] and v.get("start") == "today",
          f"{who}: stored cleaned (trimmed, default icon, doubles dropped): {v}")
    check(act == "road1", f"{who}: the active view is stored: {act!r}")
    # ---- another device (a second session) reads the same views and the same active one
    s2 = sess(who)
    check(views(s2) == (vs, "road1"), f"{who}: the second session shows the same views and the same active one")
    # ---- change: a second view, the active one switched on the other device, the first one changed
    r = s2.patch(B + "/api/settings", json={"side_views": vs + [PLAN], "side_view": "plan1"})
    check(r.ok, f"{who}: a second view from the other device {r.text[:200]}")
    vs, act = views(s)
    check([x["id"] for x in vs] == ["road1", "plan1"] and act == "plan1", f"{who}: the first session follows: {[x['id'] for x in vs]} {act}")
    check(vs[1]["start"] == "folder/Work%20stuff" and vs[1]["icon"] == "cal", f"{who}: start page and icon kept: {vs[1]}")
    vs[0] = {**vs[0], "name": "Unterwegs", "hide": ["g:views"]}
    check(s.patch(B + "/api/settings", json={"side_views": vs}).ok, f"{who}: a view changed")
    check(views(s2)[0][0]["name"] == "Unterwegs" and views(s2)[0][0]["hide"] == ["g:views"], f"{who}: the change on the other device")
    # ---- back to "Everything", delete
    check(s.patch(B + "/api/settings", json={"side_view": ""}).ok and views(s2)[1] == "", f"{who}: back to Everything")
    check(s.patch(B + "/api/settings", json={"side_views": [vs[1]]}).ok and [x["id"] for x in views(s2)[0]] == ["plan1"], f"{who}: a view deleted")
    return s2


run(A, "alice")
# ---- another person sees nothing of it
vb, ab = views(Bo)
check(vb == [] and ab == "", f"bob notices nothing of alice's views: {vb} {ab!r}")
check(Bo.patch(B + "/api/settings", json={"side_views": [ROAD]}).ok and [x["id"] for x in views(A)[0]] == ["plan1"],
      "bob's own views do not touch alice's")

# ---- a person without an organisation (freelancer-matrix: own): the same
FID, Fr = freelancer(B, A)
run(Fr, "frida")
check([x["id"] for x in views(A)[0]] == ["plan1"] and [x["id"] for x in views(Fr)[0]] == ["plan1"], "freelancer and alice keep their own views")

print(f"p2156_d_sideviews_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
