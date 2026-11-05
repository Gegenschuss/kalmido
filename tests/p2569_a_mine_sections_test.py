#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.569.0 A (#4395) API tests, own container (kt.fresh): the own sections of "My tasks" (/api/mine-sections, kalmido/tasks/mineorder.py).
 - the first opening makes "Recently assigned" (kind recent), "Now", "Soon", "Someday" (now / soon / later) once
 - PUT /api/tasks/mine-order secs: a task put into an own section by hand keeps it in later orders; "Recently assigned" or
   a section of somebody else = none; the list's sections and tasks.sort stay untouched
 - create (at the end / after one), rename, fold, move, delete (tasks into the topmost section left) and its Undo (restore)
 - two devices: A reads, B renames, A renames / deletes with the old version -> 409 with the current section; _prev of the order
 - "Recently assigned" is never renamed or deleted; somebody else's section = 404; agents have none (403)
freelancer-matrix: tasks (frida has no organisation: every route as her)
usage: p2569_a_mine_sections_test.py <datadir>"""
import sys

import requests

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer, login

kt.fresh()
A = kt.setup()
FID, Fr = freelancer(B, A, "frida")
BID, Bo = freelancer(B, A, "bob")
Fr2 = login(B, "frida")  # frida's second device
H = {"X-Requested-With": "kalmido"}


def st(s=Fr):
    return s.get(B + "/api/state").json()


def secs(s=Fr):
    return st(s)["mine_sections"]


def by_kind(lst, k):
    return next((x for x in lst if x["kind"] == k), None)


# ================================================================== 1. the default sections, once
check(secs()["list"] == [] and secs()["tasks"] == {}, "no sections before the first opening")
r = Fr.post(B + "/api/mine-sections/init", json={})
j = r.json()
check(r.ok and j.get("created") is True, f"init makes them {r.status_code} {r.text[:200]}")
L = j["mine_sections"]["list"]
check([x["kind"] for x in L] == ["recent", "now", "soon", "later"] and all(x["name"] == "" for x in L),
      f"Recently assigned on top, then Now, Soon, Someday (translated by the app): {L}")
r = Fr.post(B + "/api/mine-sections/init", json={})
check(r.ok and r.json().get("created") is False and len(r.json()["mine_sections"]["list"]) == 4, "a second init changes nothing")
check(secs(Bo)["list"] == [], "bob sees none of frida's sections")
REC, NOW, SOON, LATER = (by_kind(L, k)["id"] for k in ("recent", "now", "soon", "later"))

# ================================================================== 2. tasks into sections (the list stays as it is)
LID = Fr.post(B + "/api/lists", json={"name": "Home"}).json()["id"]
LSEC = Fr.post(B + "/api/sections", json={"list_id": LID, "name": "Backlog"}).json().get("id")
T = [Fr.post(B + "/api/tasks", json={"title": f"Task {i}", "list_id": LID, **({"section_id": LSEC} if LSEC else {})}).json()["id"] for i in range(4)]
T1, T2, T3, T4 = T
sort0 = {t["id"]: (t["sort"], t.get("section_id")) for t in st()["tasks"] if t["id"] in T}
r = Fr.put(B + "/api/tasks/mine-order", json={"ids": [T1, T2, T3], "secs": {str(T2): SOON, str(T3): REC}})
check(r.ok and r.json().get("count") == 3, f"the order with sections {r.status_code} {r.text[:200]}")
s = secs()
check(s["tasks"].get(str(T2)) == SOON, f"T2 is in Soon by hand: {s['tasks']}")
check(str(T3) not in s["tasks"] and str(T1) not in s["tasks"], "\"Recently assigned\" takes nothing by hand, T1 has no section")
check(Fr.put(B + "/api/tasks/mine-order", json={"ids": [T2, T1, T3]}).ok and secs()["tasks"].get(str(T2)) == SOON,
      "an order without secs keeps the sections")
check(Fr.put(B + "/api/tasks/mine-order", json={"ids": [T2, T1], "secs": {str(T1): 99999999}}).ok and str(T1) not in secs()["tasks"],
      "an unknown section = none")
s0 = st()
check({t["id"]: (t["sort"], t.get("section_id")) for t in s0["tasks"] if t["id"] in T} == sort0, "tasks.sort and the list's sections unchanged")
check(Fr.put(B + "/api/tasks/mine-order", json={"ids": [T1], "secs": "x"}).status_code == 400, "secs must be a map")
check(Fr.put(B + "/api/tasks/mine-order", json={"ids": [T2, T1, T3], "secs": {str(T2): SOON}}).ok, "setup: T3 placed again")
# bob's section is none for frida
r = Bo.post(B + "/api/mine-sections/init", json={})
BNOW = by_kind(r.json()["mine_sections"]["list"], "now")["id"]
check(Fr.put(B + "/api/tasks/mine-order", json={"ids": [T2, T1, T3], "secs": {str(T1): BNOW}}).ok and str(T1) not in secs()["tasks"],
      "somebody else's section = none")

# ================================================================== 3. create, rename, fold, move
r = Fr.post(B + "/api/mine-sections", json={"name": "Errands"})
ERR = r.json().get("id")
L = r.json()["mine_sections"]["list"]
check(r.ok and L[-1]["id"] == ERR and L[-1]["name"] == "Errands" and L[-1]["kind"] == "", f"a new section at the end {r.text[:200]}")
r = Fr.post(B + "/api/mine-sections", json={"name": "Calls", "after": NOW})
CALLS = r.json().get("id")
check([x["id"] for x in r.json()["mine_sections"]["list"]][:3] == [REC, NOW, CALLS], "after Now")
check(Fr.post(B + "/api/mine-sections", json={"name": "  "}).status_code == 400, "an empty name: 400")
v0 = by_kind(secs()["list"], "soon")["updated_at"]
r = Fr.patch(B + f"/api/mine-sections/{SOON}", json={"collapsed": True})
check(r.ok and by_kind(secs()["list"], "soon")["collapsed"] is True, "folded (every device)")
check(by_kind(secs()["list"], "soon")["updated_at"] == v0, "folding is no new version")
r = Fr.patch(B + f"/api/mine-sections/{NOW}", json={"name": "Today's work", "expect_updated_at": by_kind(secs()["list"], "now")["updated_at"]})
check(r.ok and by_kind(secs()["list"], "now")["name"] == "Today's work", f"renamed {r.status_code} {r.text[:200]}")
check(by_kind(secs()["list"], "now")["kind"] == "now", "the kind stays: the rule of Now goes on after renaming")
check(Fr.patch(B + f"/api/mine-sections/{REC}", json={"name": "Inbox"}).status_code == 400, "\"Recently assigned\" is not renamed")
check(Fr.delete(B + f"/api/mine-sections/{REC}").status_code == 400, "\"Recently assigned\" is not deleted")
check(Bo.patch(B + f"/api/mine-sections/{NOW}", json={"name": "x"}).status_code == 404 and Bo.delete(B + f"/api/mine-sections/{NOW}").status_code == 404,
      "somebody else's section: 404")
own = [x["id"] for x in secs()["list"] if x["kind"] != "recent"]
r = Fr.put(B + "/api/mine-sections/order", json={"ids": own[::-1], "_prev": {"ids": own}})
check(r.ok and [x["id"] for x in secs()["list"]] == [REC] + own[::-1], "the sections reordered, Recently assigned stays on top")
r = Fr.put(B + "/api/mine-sections/order", json={"ids": own, "_prev": {"ids": own}})
check(r.ok and r.json().get("order_kept") is True and [x["id"] for x in secs()["list"]] == [REC] + own[::-1], "_prev of another order: nothing changes")
check(Fr.put(B + "/api/mine-sections/order", json={"ids": own, "_prev": {"ids": own[::-1]}}).ok and [x["id"] for x in secs()["list"]] == [REC] + own,
      "back in the first order")

# ================================================================== 4. two devices: the version of rename / delete
seen = by_kind(st(Fr2)["mine_sections"]["list"], "later")  # device B reads
r = Fr.patch(B + f"/api/mine-sections/{LATER}", json={"name": "One day", "expect_updated_at": seen["updated_at"]})  # device A renames
check(r.ok, "device A renames Someday")
r = Fr2.patch(B + f"/api/mine-sections/{LATER}", json={"name": "Maybe", "expect_updated_at": seen["updated_at"]})  # B with the old version
check(r.status_code == 409 and r.json().get("section", {}).get("name") == "One day", f"device B with the old version: 409 with the current one {r.status_code} {r.text[:200]}")
r = Fr2.delete(B + f"/api/mine-sections/{LATER}", json={"expect_updated_at": seen["updated_at"]})
check(r.status_code == 409 and by_kind(secs()["list"], "later") is not None, "deleting with the old version: 409, the section stays")
check(Fr2.patch(B + f"/api/mine-sections/{LATER}", json={"name": "Maybe"}).ok, "without expect_updated_at: the old behaviour")

# ================================================================== 5. delete: the tasks into the topmost section, Undo
check(secs()["tasks"].get(str(T2)) == SOON, "setup: T2 in Soon")
v = by_kind(secs()["list"], "soon")["updated_at"]
r = Fr.delete(B + f"/api/mine-sections/{SOON}", json={"expect_updated_at": v})
j = r.json()
top = [x["id"] for x in j["mine_sections"]["list"] if x["kind"] != "recent"][0]
check(r.ok and j.get("moved_to") == top and secs()["tasks"].get(str(T2)) == top, f"deleted: T2 in the topmost section {r.text[:300]}")
check(by_kind(secs()["list"], "soon") is None, "Soon is gone")
rs = j.get("restore") or {}
check(rs.get("kind") == "soon" and rs.get("tasks") == [T2] and rs.get("collapsed") is True, f"the restore data {rs}")
r = Fr.post(B + "/api/mine-sections", json={"name": rs.get("name"), "restore": rs})
back = by_kind(r.json()["mine_sections"]["list"], "soon")
check(r.ok and back and back["collapsed"] is True and secs()["tasks"].get(str(T2)) == back["id"], f"Undo: Soon is back with T2 {r.text[:200]}")
check([x["kind"] for x in secs()["list"]].index("soon") == rs.get("pos"), "Undo: at its old place")
# delete Now: its kind (the rule) is gone with it
r = Fr.delete(B + f"/api/mine-sections/{NOW}")
check(r.ok and by_kind(secs()["list"], "now") is None, "Now deleted: no section of kind now (the app stops moving due tasks)")
r = Fr.post(B + "/api/mine-sections", json={"name": "", "restore": r.json()["restore"]})
check(r.ok and by_kind(secs()["list"], "now") is not None, "Undo brings Now back with its kind")
r = Fr.post(B + "/api/mine-sections", json={"name": "", "restore": {"kind": "now"}})
check(r.status_code == 400 and sum(1 for x in secs()["list"] if x["kind"] == "now") == 1, "never a second section of kind now")

# ================================================================== 6. agents have none
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "structure"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag.get("token", "x"), **H}
codes = [requests.post(B + "/api/mine-sections/init", headers=AGH, json={}).status_code,
         requests.post(B + "/api/mine-sections", headers=AGH, json={"name": "x"}).status_code,
         requests.put(B + "/api/mine-sections/order", headers=AGH, json={"ids": []}).status_code,
         requests.patch(B + f"/api/mine-sections/{NOW}", headers=AGH, json={"name": "x"}).status_code,
         requests.delete(B + f"/api/mine-sections/{NOW}", headers=AGH).status_code]
check(all(c in (401, 403, 404) for c in codes), f"agents have no own sections {codes}")

# ================================================================== 7. a person of an organisation the same way (alice)
r = A.post(B + "/api/mine-sections/init", json={})
check(r.ok and len(r.json()["mine_sections"]["list"]) == 4, "alice (organisation) gets her own defaults")
check(not {x["id"] for x in secs()["list"]} & {y["id"] for y in r.json()["mine_sections"]["list"]}, "alice's and frida's sections are apart")
# the delta carries them too
v = st()["v"]
Fr.patch(B + f"/api/mine-sections/{ERR}", json={"name": "Errands 2"})
dl = Fr.get(B + f"/api/state/delta?since={v}").json()
check(dl.get("full") or any(x["name"] == "Errands 2" for x in (dl.get("mine_sections") or {}).get("list", [])), "the delta carries the sections")

sys.exit(kt.done("p2569_a_mine_sections"))
