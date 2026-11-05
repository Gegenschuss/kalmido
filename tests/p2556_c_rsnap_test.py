#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.556.0 C (#4583) API test: the completed copy of a recurring task keeps what its subtasks were (tasks.sub_snapshot,
tasks/lifecycle.rsn_take). Own container. Invented people only (example.com).
freelancer-matrix: tasks (a person without an organisation, the same round)
 - 5 subtasks, 3 done, the task ticked: the copy says 3 of 5 with the titles in their order and their state; it has no
   subtasks of its own; the original's subtasks are all open again and the original carries no snapshot
 - the snapshot stays as it was: renaming / ticking the original's subtasks afterwards does not change it
 - undo: the copy is gone (with its snapshot), the 3 subtasks are done again, the task is back on its day
 - a birthday (FAM_OCC): its gift ideas keep their ticks, the copy has no snapshot
 - a person's API token (REST v1) reads the snapshot on the copy
review (2.556.0 C2, each a regression test, red without its fix):
 - finding 1: an agent never reads it (REST v1 one task / the list, its events); the person still does
 - finding 2: the list lock -- switching it on empties the snapshots there; a list with the lock writes none; moving a copy
   into a list with the lock empties its snapshot
 - finding 3: the copy reopened (one task / multi-select) or given a repeat again: the snapshot goes
 - finding 4: a damaged / oversized stored snapshot goes out in the known shape only (at most 100 items, titles cut)
usage: p2556_c_rsnap_test.py <datadir>"""
import base64
import json
import os
import sys
import requests

import kt
import testclock
from kt import B, check

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

kt.docker_logs_on_first_fail()
kt.fresh()
A = kt.setup()
assert A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"}).ok
FID, Fr = freelancer(B, A, "frieda")
TODAY = testclock.today().isoformat()


def copy_of(lid, tid):
    rows = kt.dbx("SELECT id FROM tasks WHERE list_id=? AND id<>? AND parent_id IS NULL AND status=2 AND deleted_at IS NULL ORDER BY id",
                  (lid, tid))
    return [r[0] for r in rows]


def states(ids):
    st = dict(kt.dbx(f"SELECT id, status FROM tasks WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)))
    return [st.get(i) for i in ids]


def round_of(s, who):
    lid = s.post(B + "/api/lists", json={"name": f"Routine {who}"}).json()["id"]
    r = s.post(B + "/api/tasks", json={"title": f"Weekly review {who}", "list_id": lid, "due": TODAY, "repeat": "FREQ=WEEKLY"})
    assert r.ok, r.text
    tid = r.json()["id"]
    subs = []
    for i in range(1, 6):
        r = s.post(B + "/api/tasks", json={"title": f"Step {i} {who}", "list_id": lid, "parent_id": tid})
        assert r.ok, r.text
        subs.append(r.json()["id"])
    for k in subs[:3]:
        assert s.post(B + f"/api/tasks/{k}/complete", json={}).ok
    j = s.post(B + f"/api/tasks/{tid}/complete", json={}).json()
    check(j.get("next_due") and j["next_due"] > TODAY, f"{who}: ticked, the task moves on {j.get('next_due')}")
    cps = copy_of(lid, tid)
    check(len(cps) == 1, f"{who}: one completed copy {cps}")
    cp = cps[0] if cps else 0
    ss = s.get(B + f"/api/tasks/{cp}").json().get("sub_snapshot") or {}
    items = ss.get("items") or []
    check(ss.get("done") == 3 and ss.get("total") == 5, f"{who}: the copy says 3 of 5 {ss}")
    check([i.get("title") for i in items] == [f"Step {i} {who}" for i in range(1, 6)]
          and [i.get("status") for i in items] == [2, 2, 2, 0, 0] and all(i.get("depth") == 1 for i in items),
          f"{who}: the titles in their order with their state {items}")
    check(not kt.dbx("SELECT 1 FROM tasks WHERE parent_id=?", (cp,)), f"{who}: the copy has no subtasks of its own")
    check(states(subs) == [0] * 5, f"{who}: the original's subtasks are all open again {states(subs)}")
    check("sub_snapshot" not in s.get(B + f"/api/tasks/{tid}").json(), f"{who}: the original carries no snapshot")
    # undo: the copy with its snapshot goes, the round comes back
    u = s.post(B + f"/api/tasks/{tid}/undo", json=j.get("undo") or {})
    check(u.ok and u.json().get("due") == TODAY, f"{who}: undo, back on its day {u.status_code} {u.text[:200]}")
    check(not kt.dbx("SELECT 1 FROM tasks WHERE id=?", (cp,)), f"{who}: undo removed the copy (and its snapshot)")
    check(states(subs) == [2, 2, 2, 0, 0], f"{who}: undo, the 3 subtasks are done again {states(subs)}")
    # once more, then the original's subtasks change: the snapshot stays as it was
    j = s.post(B + f"/api/tasks/{tid}/complete", json={}).json()
    cp = (copy_of(lid, tid) or [0])[0]
    assert s.patch(B + f"/api/tasks/{subs[0]}", json={"title": f"Renamed {who}"}).ok
    assert s.post(B + f"/api/tasks/{subs[4]}/complete", json={}).ok
    ss2 = s.get(B + f"/api/tasks/{cp}").json().get("sub_snapshot") or {}
    check(ss2.get("done") == 3 and (ss2.get("items") or [{}])[0].get("title") == f"Step 1 {who}",
          f"{who}: later changes leave the snapshot as it was {ss2}")
    return cp


ACP = round_of(A, "alice")
FCP = round_of(Fr, "frieda")  # freelancer-matrix: tasks

# ---- REST v1 with a person's token: the snapshot is there for agents / scripts, too
tok = Fr.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read"]}).json().get("token")
r = requests.get(B + f"/api/v1/tasks/{FCP}", headers={"Authorization": "Bearer " + (tok or "")}, timeout=30)
check(r.ok and (r.json().get("sub_snapshot") or {}).get("total") == 5, f"v1: the copy's snapshot {r.status_code} {r.text[:200]}")

# ---- a birthday: the gift ideas keep their ticks, no snapshot
lid = A.post(B + "/api/lists", json={"name": "Birthdays"}).json()["id"]
r = A.post(B + "/api/tasks", json={"title": "Erika", "list_id": lid, "due": TODAY, "repeat": "FREQ=YEARLY"})
O = r.json()["id"]
r = A.patch(B + f"/api/tasks/{O}", json={"fam": {"kind": "birthday", "name": "Erika"}})
check(r.ok, f"a birthday {r.status_code} {r.text[:200]}")
g = [A.post(B + "/api/tasks", json={"title": f"Gift {i}", "list_id": lid, "parent_id": O}).json()["id"] for i in (1, 2)]
A.post(B + f"/api/tasks/{g[0]}/complete", json={})
A.post(B + f"/api/tasks/{O}/complete", json={})
oc = (copy_of(lid, O) or [0])[0]
check(oc and "sub_snapshot" not in A.get(B + f"/api/tasks/{oc}").json(), "birthday: the copy has no snapshot")
check(states(g) == [2, 0], f"birthday: the given gift stays ticked {states(g)}")

# ================================================================== review (2.556.0 C2)
V = B + "/api/v1"
FL = kt.dbx("SELECT list_id FROM tasks WHERE id=?", (FCP,))[0][0]
FR = kt.dbx("SELECT id FROM tasks WHERE list_id=? AND repeat<>'' AND parent_id IS NULL", (FL,))[0][0]


def snap(tid):
    return kt.dbx("SELECT sub_snapshot FROM tasks WHERE id=?", (tid,))[0][0] or ""


def mk_copy(s, lid, title, n=3, done=2, ttl=None):
    """A recurring task with n subtasks, done of them ticked, ticked itself -> (task, its completed copy). ttl(text) = the
    stored form of a text (a list with the lock: a ciphertext)."""
    ttl = ttl or (lambda x: x)
    r = s.post(B + "/api/tasks", json={"title": ttl(title), "list_id": lid, "due": TODAY, "repeat": "FREQ=WEEKLY"})
    assert r.ok, r.text
    tid = r.json()["id"]
    ks = [s.post(B + "/api/tasks", json={"title": ttl(f"{title} step {i}"), "list_id": lid, "parent_id": tid}).json()["id"] for i in range(n)]
    for k in ks[:done]:
        assert s.post(B + f"/api/tasks/{k}/complete", json={}).ok
    before = set(copy_of(lid, tid))
    r = s.post(B + f"/api/tasks/{tid}/complete", json={})
    assert r.ok, r.text
    cp = [x for x in copy_of(lid, tid) if x not in before]
    return tid, (cp[0] if cp else 0)


# ---- finding 1: an agent of the list never reads the snapshot (its data lock may hide those subtasks)
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok
r = Fr.post(B + "/api/my/agents", json={"username": "friedabot", "display_name": "Friedabot", "scopes": ["read", "tasks:write"]})
check(r.status_code in (200, 201), "setup: an agent " + r.text[:200])
AID = r.json().get("id")
check(Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": AID, "role": "edit"}).ok, "setup: the agent in the list")
AH = {"Authorization": "Bearer " + (Fr.post(B + f"/api/my/agents/{AID}/token").json().get("token") or ""), **kt.H}
r = requests.get(V + f"/tasks/{FCP}", headers=AH, timeout=30)
check(r.ok and r.json().get("completed_at") and "sub_snapshot" not in r.json(), f"agent: the copy without its snapshot {r.status_code} {r.text[:200]}")
r = requests.get(V + "/tasks", headers=AH, params={"list_id": FL, "status": "all"}, timeout=30)
rows = (r.json().get("data") or []) if r.ok else []
check(r.ok and any(x.get("id") == FCP for x in rows) and not any("sub_snapshot" in x for x in rows),
      f"agent: the list (with the copy) without snapshots {r.status_code} {len(rows)}")
check((Fr.get(B + f"/api/tasks/{FCP}").json().get("sub_snapshot") or {}).get("total") == 5, "the person still reads it")
# an event about the copy (assigned to the agent): its task part without the snapshot (api/v1.task_for, webhooks too)
check(Fr.patch(B + f"/api/tasks/{FCP}", json={"assignee_id": AID}).ok, "setup: the copy assigned to the agent")
ev = requests.get(V + "/agent/events", headers=AH, params={"since": 0, "limit": 500}, timeout=30).json()
ev = ev.get("data", ev.get("events", [])) if isinstance(ev, dict) else ev
mine = [e for e in ev if (e.get("data") or {}).get("task", {}).get("id") == FCP]
check(mine and not any("sub_snapshot" in e["data"]["task"] for e in mine), f"agent: its event names the copy without the snapshot {len(mine)}")

# ---- finding 3: reopened (one task, multi-select) or a series again: the snapshot goes
L3 = Fr.post(B + "/api/lists", json={"name": "Round three"}).json()["id"]
_, c1 = mk_copy(Fr, L3, "Reopen")
_, c2 = mk_copy(Fr, L3, "Batch")
_, c3 = mk_copy(Fr, L3, "Repeat")
check(c1 and c2 and c3 and all(snap(x) for x in (c1, c2, c3)), "setup: three copies with a snapshot")
check(Fr.post(B + f"/api/tasks/{c1}/reopen", json={}).ok, "the copy reopened")
check(snap(c1) == "" and "sub_snapshot" not in Fr.get(B + f"/api/tasks/{c1}").json(), "reopened: the snapshot goes")
check(Fr.post(B + f"/api/tasks/{c1}/complete", json={}).ok and "sub_snapshot" not in Fr.get(B + f"/api/tasks/{c1}").json(),
      "ticked again (no repeat): no old snapshot comes back")
r = Fr.post(B + "/api/tasks/batch", json={"ids": [c2], "action": "reopen"})
check(r.ok and snap(c2) == "", f"multi-select reopen: the snapshot goes {r.status_code} {r.text[:200]}")
r = Fr.patch(B + f"/api/tasks/{c3}", json={"repeat": "FREQ=WEEKLY"})
check(r.ok and snap(c3) == "" and "sub_snapshot" not in r.json(), f"a repeat again: the snapshot goes {r.status_code} {r.text[:200]}")

# ---- finding 4: a stored snapshot goes out in the known shape only
_, c4 = mk_copy(Fr, L3, "Shape")
bad = {"done": 3, "total": 999999999, "items": [{"title": "Fine", "status": 2, "depth": 1}, {"title": 5, "status": 2, "depth": 1}, "x",
                                                 {"title": "Long " + "y" * 2000, "status": 0, "depth": 2}, {"title": "Odd", "status": 7, "depth": 1},
                                                 {"title": "Flag", "status": True, "depth": 1}, {"title": "Deep", "status": -1, "depth": "1"}]
       + [{"title": f"More {i}", "status": 0, "depth": 1} for i in range(150)]}
kt.dbx("UPDATE tasks SET sub_snapshot=? WHERE id=?", (json.dumps(bad), c4))
ss = Fr.get(B + f"/api/tasks/{c4}").json().get("sub_snapshot") or {}
it = ss.get("items") or []
check(len(it) == 100 and it[0] == {"title": "Fine", "status": 2, "depth": 1} and len(it[1]["title"]) == 500,
      f"at most 100 items, the known ones, titles cut {len(it)} {[str(x)[:30] for x in it[:2]]}")
check(all(isinstance(i, dict) and isinstance(i.get("title"), str) and i.get("status") in (-1, 0, 2) and isinstance(i.get("depth"), int)
          and i["title"] not in ("Odd", "Flag", "Deep") for i in it), "no item of another shape")
check(ss.get("total") == len(it) and ss.get("done") == 1, f"done / total from the items when the stored ones do not fit {ss.get('done')} {ss.get('total')}")
kt.dbx("UPDATE tasks SET sub_snapshot=? WHERE id=?", ('{"items": [[1], "x", {"title": 3}]}', c4))
check("sub_snapshot" not in Fr.get(B + f"/api/tasks/{c4}").json(), "a snapshot without one good item: none")


# ---- finding 2: the list lock
def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def ct(gen):
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(48)}, separators=(",", ":"))


LK = Fr.post(B + "/api/lists", json={"name": "Locked"}).json()["id"]
LO = Fr.post(B + "/api/lists", json={"name": "Open"}).json()["id"]
_, k1 = mk_copy(Fr, LK, "Before the lock")
_, k2 = mk_copy(Fr, LO, "Moves in")
check(k1 and snap(k1) and k2 and snap(k2), "setup: copies with a snapshot in both lists")
assert Fr.put(B + "/api/e2e/keys", json={"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
                                         "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
                                         "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}).ok
r = Fr.post(B + f"/api/lists/{LK}/e2e/start", json={"keys": [{"user_id": FID, "wrapped": {"v": 1, "iv": b64(12), "ct": b64(48)}}]})
check(r.ok, "the lock starts " + r.text[:200])
check(snap(k1) == "", "switching the lock on empties the snapshot (no plain subtask titles under the lock)")
j = Fr.get(B + f"/api/lists/{LK}/e2e/todo").json()
G = j["gen"]
out = {"tasks": [{"id": x["id"], **{k: ct(G) for k, v in x.items() if k != "id" and v is not None}} for x in j["tasks"]]}
check(Fr.post(B + f"/api/lists/{LK}/e2e/bulk", json=out).ok, "the texts encrypted")
r = Fr.post(B + f"/api/lists/{LK}/e2e/finish")
check(r.ok, "the lock is on " + r.text[:200])
_, k3 = mk_copy(Fr, LK, "Under the lock", ttl=lambda x: ct(G))
check(k3 and snap(k3) == "", f"a list with the lock writes no snapshot {k3} {snap(k3)[:60] if k3 else ''}")
r = Fr.patch(B + f"/api/tasks/{k2}", json={"list_id": LK, "title": ct(G)})
check(r.ok and kt.dbx("SELECT list_id FROM tasks WHERE id=?", (k2,))[0][0] == LK, "the copy moves into the locked list " + r.text[:200])
check(snap(k2) == "", "moved in: its plain snapshot goes")

sys.exit(kt.done("p2556_c_rsnap"))
