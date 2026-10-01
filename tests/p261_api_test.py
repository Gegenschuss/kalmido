#!/usr/bin/env python3
"""2.6.1 API, own container (start.sh):
#401 the setting date_confirm (default 0, a flag); #402 the setting agents_hidden (comma list of agent ids, '' = all shown);
#404 the list bell "custom": PUT /api/lists/<id>/bell {mode: custom, custom: {event: {news, push}}} with validation, the choice
in /api/state (bell_custom) and kept while another mode is set; News follow it (a ticked event comes from every task of the
list, an unticked one never, reply / follow count as comment, an event not chosen follows the matrix); the token API
(GET /me, PATCH /me/notifications with {mode: custom, events}).
usage: p261_api_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": "password123"})
    assert r.ok, r.text
    return s


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
requests.post(B + "/api/auth/setup", headers=H, json={"username": "alice", "display_name": "Alice", "password": "password123"})
A = sess("alice")
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
Bo = sess("bob")
for x in (A, Bo):
    x.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ================================================================== #401 / #402 settings
s = Bo.get(B + "/api/state").json()["settings"]
check(s.get("date_confirm") == "0" and s.get("agents_hidden") == "", f"defaults: date_confirm 0, agents_hidden '': {s.get('date_confirm')!r} {s.get('agents_hidden')!r}")
check(Bo.patch(B + "/api/settings", json={"date_confirm": "1"}).ok and Bo.get(B + "/api/state").json()["settings"]["date_confirm"] == "1", "date_confirm on")
check(Bo.patch(B + "/api/settings", json={"date_confirm": True}).ok and Bo.get(B + "/api/state").json()["settings"]["date_confirm"] == "1", "date_confirm: true -> 1")
check(Bo.patch(B + "/api/settings", json={"date_confirm": "maybe"}).status_code == 400, "date_confirm: invalid 400")
check(Bo.patch(B + "/api/settings", json={"date_confirm": "0"}).ok, "date_confirm off")
check(Bo.patch(B + "/api/settings", json={"agents_hidden": "7,3,7"}).ok and Bo.get(B + "/api/state").json()["settings"]["agents_hidden"] == "7,3",
      "agents_hidden stored (duplicates dropped)")
for bad in ("a,b", "1;2", "1" * 20):
    check(Bo.patch(B + "/api/settings", json={"agents_hidden": bad}).status_code == 400, f"agents_hidden invalid 400: {bad}")
check(Bo.patch(B + "/api/settings", json={"agents_hidden": ""}).ok, "agents_hidden cleared")

# ================================================================== #404 the custom bell
L = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok
PRIV = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]


def news(kind=None):
    j = Bo.get(B + "/api/news").json()
    return [x for x in j.get("items", []) if kind is None or x["kind"] == kind]


def ncount(kind):
    return sum(x.get("count", 1) for x in news(kind))


def bell():
    return next(x for x in Bo.get(B + "/api/state").json()["lists"] if x["id"] == L)


check(bell()["bell"] == "default" and bell()["bell_custom"] == {}, "default bell, no choice")
for bad in ({"bogus": {"news": 1}}, {"comment": {"sound": 1}}, {"comment": {"news": 2}}, {"comment": 1}, [1], "x", {"share": {"news": 1}}):
    check(Bo.put(B + f"/api/lists/{L}/bell", json={"mode": "custom", "custom": bad}).status_code == 400, f"custom invalid 400: {bad}")
check(Bo.put(B + f"/api/lists/{PRIV}/bell", json={"mode": "custom", "custom": {}}).status_code == 404, "a list I do not see 404")
check(Bo.put(B + f"/api/lists/{L}/bell", json={"mode": "loud"}).status_code == 400, "unknown mode 400")
r = Bo.put(B + f"/api/lists/{L}/bell", json={"mode": "custom", "custom": {
    "newtask": {"news": True, "push": False}, "comment": {"news": 0, "push": 0}, "mention": {"news": 0, "push": 0},
    "complete": {"news": 1, "push": 0}}})
check(r.ok and r.json()["mode"] == "custom" and r.json()["custom"]["newtask"] == {"news": 1, "push": 0}, f"custom stored: {r.text[:200]}")
b = bell()
check(b["bell"] == "custom" and b["bell_custom"]["comment"] == {"news": 0, "push": 0} and "assign" not in b["bell_custom"], f"state: {b['bell_custom']}")
check(next(x for x in A.get(B + "/api/state").json()["lists"] if x["id"] == L)["bell"] == "default", "only for bob")

# newtask: ticked (the matrix has it off) -> News
T1 = A.post(B + "/api/tasks", json={"title": "Alice adds", "list_id": L}).json()["id"]
time.sleep(0.3)
check(any(x["task_id"] == T1 for x in news("newtask")), "custom newtask ticked: News (matrix default is off)")
# comment unticked: no News even on bob's own task (matrix default on)
BT = Bo.post(B + "/api/tasks", json={"title": "Bobs task", "list_id": L}).json()["id"]
A.post(B + f"/api/tasks/{BT}/comments", json={"body": "a remark"})
time.sleep(0.3)
check(not news("comment"), "custom comment unticked: no News on my own task")
# mention unticked: no News either
A.post(B + f"/api/tasks/{T1}/comments", json={"body": f"<@{BOB}> look"})
time.sleep(0.3)
check(not news("mention"), "custom mention unticked: no News")
# assign: not in the choice -> the matrix (on)
A.patch(B + f"/api/tasks/{T1}", json={"assignee_id": BOB})
time.sleep(0.3)
check(news("assign"), "an event not chosen follows the matrix (assign on)")
# complete ticked: every completion in the list (also a task bob neither created nor got assigned)
T2 = A.post(B + "/api/tasks", json={"title": "Alice only", "list_id": L}).json()["id"]
A.post(B + f"/api/tasks/{T2}/complete")
time.sleep(0.3)
check(any(x["task_id"] == T2 for x in news("complete")), f"custom complete ticked: every completion of the list {[x['kind'] for x in news()]}")
# comment ticked: every comment of the list, also on a task bob never touched
Bo.put(B + f"/api/lists/{L}/bell", json={"mode": "custom", "custom": {"comment": {"news": 1, "push": 0}}})
T3 = A.post(B + "/api/tasks", json={"title": "Elsewhere", "list_id": L}).json()["id"]
A.post(B + f"/api/tasks/{T3}/comments", json={"body": "on a task bob never saw"})
time.sleep(0.3)
check(any(x["task_id"] == T3 for x in news("comment")), "custom comment ticked: every comment of the list")
check(bell()["bell_custom"] == {"comment": {"news": 1, "push": 0}}, "a new choice replaces the old one")
# the choice survives another mode and comes back
check(Bo.put(B + f"/api/lists/{L}/bell", json={"mode": "mute"}).ok and bell()["bell"] == "mute" and bell()["bell_custom"] == {"comment": {"news": 1, "push": 0}},
      "mute keeps the choice")
check(Bo.put(B + f"/api/lists/{L}/bell", json={"mode": "default"}).ok and bell()["bell"] == "default" and bell()["bell_custom"].get("comment", {}).get("news") == 1,
      "default keeps the choice")
n0 = ncount("comment")
A.post(B + f"/api/tasks/{T3}/comments", json={"body": "while on default"})
time.sleep(0.3)
check(ncount("comment") == n0, "on default again: a comment elsewhere does not reach bob")
check(Bo.put(B + f"/api/lists/{L}/bell", json={"mode": "custom"}).ok and bell()["bell"] == "custom" and bell()["bell_custom"]["comment"]["news"] == 1,
      "custom without a choice brings the stored one back")
A.post(B + f"/api/tasks/{T3}/comments", json={"body": "custom again"})
time.sleep(0.3)
check(ncount("comment") > n0, "custom again: comments come")

# ================================================================== token API
tok = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
V = requests.Session()
V.headers.update({"Authorization": "Bearer " + tok})
j = V.get(B + "/api/v1/me").json()["notifications"]
check(j["lists"].get(str(L)) == "custom" and j["custom"][str(L)] == {"comment": {"news": 1, "push": 0}}, f"v1 /me: custom: {j}")
r = V.patch(B + "/api/v1/me/notifications", json={"lists": {str(L): {"mode": "custom", "events": {"status": {"push": True}}}}})
check(r.ok and r.json()["custom"][str(L)] == {"status": {"push": 1}}, f"v1 PATCH custom: {r.text[:200]}")
check(V.patch(B + "/api/v1/me/notifications", json={"lists": {str(L): {"mode": "all", "events": {}}}}).status_code == 400, "v1: a dict must be custom")
check(V.patch(B + "/api/v1/me/notifications", json={"lists": {str(L): {"mode": "custom", "events": {"nope": {"push": True}}}}}).status_code == 400, "v1: unknown event 400")
check(V.patch(B + "/api/v1/me/notifications", json={"lists": {str(L): "default"}}).ok and str(L) not in V.get(B + "/api/v1/me").json()["notifications"]["lists"],
      "v1: default -> left out")

print(f"p261_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
