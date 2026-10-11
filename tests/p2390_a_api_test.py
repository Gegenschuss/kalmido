#!/usr/bin/env python3
"""2.39.0 API tests (agent A), own container (start.sh).
 - #1168 the Playbook of a list / folder: who may write (owner, list admins; not editors, participants, agents; people who do
   not see the list 404), inheritance folder -> subfolder -> list (effective text, l.playbook in the state), versions (no new
   version for the same text, 409 on an old base_version, restore, a version's text), the limit of 8000 characters, folders
   (only their owner, rename / move takes the Playbook along)
 - the agent API: GET /api/v1/lists/<lid>/playbook (a health list and a list outside the agent's list limit: 404), the
   playbook field of GET /lists/<lid>, the playbook in task_added / tidy / mention / job_request (cleanup) events; proposals
   (POST /api/v1/lists/<lid>/playbook/proposals: members only, at most 3 open, News for the owner / admins, apply (edited) /
   discard, event playbook_proposal)
 - the scheduled check of a list: agents to choose, create / validate / at most 5, the watchdog and "Check now" send
   scheduled_job with list_check, open_task_ids and the playbook, not in a person's own plan list, switching off, an agent
   that left the list switches the check off (no_list)
 - list templates carry the Playbook (a new list from it gets version 1, source template), the account export, OpenAPI,
   a backup with the new tables verifies and restores
usage: p2390_a_api_test.py <datadir>"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def wait_for(fn, t=8.0):
    end = time.time() + t
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.4)
    return fn()


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = uid["bob"], uid["carol"], uid["dave"], uid["erin"]
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en"})


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": name,
                                              "display_name": name.title()})
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


CL, CLH = agent("claude")
OT, OTH = agent("otto")
W = A.post(B + "/api/lists", json={"name": "Receipts", "folder": "Home/Money"}).json()["id"]
for who, role in ((BOB, "admin"), (CAROL, "edit"), (DAVE, "participant"), (CL, "edit")):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": role}).ok, f"setup: {who} in Receipts as {role}")
W2 = A.post(B + "/api/lists", json={"name": "Other", "folder": "Home"}).json()["id"]
A.put(B + f"/api/lists/{W2}/members", json={"user_id": CL, "role": "edit"})
TOP = A.post(B + "/api/lists", json={"name": "Loose"}).json()["id"]  # no folder
PB = lambda lid: B + f"/api/lists/{lid}/playbook"  # noqa: E731


def events(h=CLH, kinds=None, since=0):
    d = requests.get(V + "/agent/events", headers=h, params={"since": since, "limit": 500}).json()["data"]
    return [e for e in d if kinds is None or e["event"] in kinds]


def last_seq(h=CLH):
    ev = events(h)
    return ev[-1]["seq"] if ev else 0


# ---- empty, rights
r = A.get(PB(W))
d = r.json()
check(r.ok and d["text"] == "" and d["version"] == 0 and d["can_edit"] is True and d["max"] == 8000 and d["folders"] == [] and d["effective"] == ""
      and d["proposals"] == [] and d["checks"] == [], "#1168: an empty Playbook for the owner " + r.text[:300])
check(Bo.get(PB(W)).json().get("can_edit") is True, "#1168: a list admin may edit")
for s, who in ((Ca, "editor"), (Da, "participant")):
    r = s.get(PB(W))
    check(r.ok and r.json()["can_edit"] is False and r.json()["proposals"] == [] and r.json()["checks"] == [], f"#1168: the {who} reads, cannot edit")
    check(s.put(PB(W), json={"text": "mine"}).status_code == 403, f"#1168: the {who} cannot write (403)")
check(Er.get(PB(W)).status_code == 404 and Er.put(PB(W), json={"text": "x"}).status_code == 404, "#1168: someone who does not see the list: 404")
check(requests.put(PB(W), headers={**CLH, **H}, json={"text": "x"}).status_code in (401, 403, 404), "#1168: an agent token cannot use the web route")

# ---- write, versions, conflict, limit
r = A.put(PB(W), json={"text": "  Receipts: read amount, date, doctor.\r\n"})
check(r.ok and r.json()["version"] == 1 and r.json()["changed"] is True, "#1168: the owner saves version 1 " + r.text[:200])
r = A.put(PB(W), json={"text": "Receipts: read amount, date, doctor."})
check(r.ok and r.json()["version"] == 1 and r.json()["changed"] is False, "#1168: the same text makes no new version")
r = Bo.put(PB(W), json={"text": "Receipts: read amount, date, doctor. Then mark them submitted.", "base_version": 1})
check(r.ok and r.json()["version"] == 2, "#1168: the list admin saves version 2 on base 1")
r = A.put(PB(W), json={"text": "stale edit", "base_version": 1})
check(r.status_code == 409 and r.json().get("current_version") == 2 and r.json().get("error"), "#1168: an old base_version -> 409 " + r.text[:200])
check(A.put(PB(W), json={"text": "x" * 8001}).status_code == 400, "#1168: more than 8000 characters -> 400")
check(A.put(PB(W), json={"text": 5}).status_code == 400, "#1168: a text must be a string")
check(A.put(PB(W), json={"text": "x" * 8000, "base_version": 2}).json().get("version") == 3, "#1168: exactly 8000 characters are fine")
vs = A.get(PB(W) + "/versions").json()["versions"]
check([v["version"] for v in vs] == [3, 2, 1] and vs[1]["by"] == {"id": BOB, "name": "Bob", "kind": "user"} and vs[0]["chars"] == 8000
      and all(v["source"] == "edit" for v in vs), "#1168: the versions, newest first, with who and how long " + str(vs)[:300])
r = Ca.get(PB(W) + "/versions/1")
check(r.ok and r.json()["text"] == "Receipts: read amount, date, doctor." and r.json()["by"]["id"] == ALICE, "#1168: a reader sees an old version")
check(A.get(PB(W) + "/versions/99").status_code == 404, "#1168: an unknown version -> 404")
check(Ca.post(PB(W) + "/restore", json={"version": 2}).status_code == 403, "#1168: an editor cannot restore")
r = A.post(PB(W) + "/restore", json={"version": 2})
check(r.ok and r.json()["version"] == 4, "#1168: restore makes version 4")
d = A.get(PB(W)).json()
check(d["text"].endswith("Then mark them submitted.") and d["version"] == 4 and d["updated_by"]["id"] == ALICE, "#1168: version 2's text is current again")
check(A.get(PB(W) + "/versions").json()["versions"][0]["source"] == "restore", "#1168: its source is restore")
check(A.post(PB(W) + "/restore", json={"version": "2"}).status_code == 400, "#1168: restore needs a number")

# ---- folders + inheritance
F = B + "/api/folders/playbook"
check(A.put(F, json={"folder": "Home", "text": "Household rules: be brief."}).ok, "#1168: the owner writes the folder Home's Playbook")
check(A.put(F, json={"folder": "Home/Money", "text": "Money: never pay anything."}).ok, "#1168: ... and the subfolder's")
r = A.get(F, params={"folder": "Home/Money"})
d = r.json()
check(r.ok and d["text"] == "Money: never pay anything." and d["version"] == 1 and d["can_edit"] and [x["folder"] for x in d["folders"]] == ["Home"]
      and {"id": W, "name": "Receipts"} in d["lists"], "#1168: the folder view: its text, the parent folder, its lists " + r.text[:300])
check(A.put(F, json={"folder": "Home", "text": "old", "base_version": 0}).status_code == 409, "#1168: a folder conflict -> 409")
check(A.get(F + "/versions", params={"folder": "Home"}).json()["versions"][0]["version"] == 1, "#1168: folder versions")
check(A.get(F, params={"folder": ""}).status_code == 400, "#1168: a folder is needed")
check(Bo.get(F, params={"folder": "Home"}).json().get("text") == "", "#1168: another person's folders are their own (bob has none)")
d = Ca.get(PB(W)).json()
eff = d["effective"]
check(eff.startswith("Household rules: be brief.") and "Money: never pay anything." in eff and eff.endswith("Then mark them submitted.")
      and eff.index("Household") < eff.index("Money") < eff.index("Receipts") and [x["folder"] for x in d["folders"]] == ["Home", "Home/Money"],
      "#1168: effective = folder, subfolder, list (outer first) " + eff[:200])
check(A.get(PB(W2)).json()["effective"] == "Household rules: be brief.", "#1168: a list in the top folder inherits only that")
st = {x["id"]: x.get("playbook") for x in A.get(B + "/api/state").json()["lists"]}
check(st.get(W) is True and st.get(W2) is True and st.get(TOP) is False, "#1168: l.playbook in the state " + str(st))
check({x["id"]: x.get("playbook") for x in Ca.get(B + "/api/state").json()["lists"]}.get(W) is True, "#1168: ... also for a member")

# ---- the agent API
r = requests.get(V + f"/lists/{W}/playbook", headers=CLH)
d = r.json()
check(r.ok and d["text"] == eff and d["list_text"].endswith("submitted.") and [x["folder"] for x in d["folders"]] == ["Home", "Home/Money"]
      and isinstance(d["version"], str) and len(d["version"]) == 12 and d["list_version"] == 4, "#1168: GET /lists/{id}/playbook " + r.text[:300])
r = requests.get(V + f"/lists/{W}", headers=CLH)
check(r.ok and r.json().get("playbook") == eff, "#1168: GET /lists/{id} carries the playbook")
check(requests.get(V + f"/lists/{TOP}/playbook", headers=CLH).status_code == 404, "#1168: a list the agent does not see: 404")
check(requests.get(V + f"/lists/{TOP}", headers=CLH).status_code == 404, "#1168: ... GET /lists/{id} too")
A.patch(B + f"/api/admin/agents/{CL}", json={"list_ids": [W]})
check(requests.get(V + f"/lists/{W2}/playbook", headers=CLH).status_code == 404, "#1168: outside the agent's list limit: 404")
check(requests.get(V + f"/lists/{W}/playbook", headers=CLH).ok, "#1168: inside it: 200")
A.patch(B + f"/api/admin/agents/{CL}", json={"list_ids": []})
A.patch(B + "/api/settings", json={"features": "cal,comments,collab,health"})
r = A.post(B + "/api/life/health", json={"type": "appointment", "title": "Dentist", "who": "Lina", "date": "2030-01-02", "time": "09:30"})
HL = next((x["id"] for x in A.get(B + "/api/state").json()["lists"] if x.get("life") == "health"), None)
check(HL and A.put(PB(HL), json={"text": "Health rules"}).ok, "#1168: a health list may have a Playbook")
check(requests.get(V + f"/lists/{HL}/playbook", headers=CLH).status_code == 404, "#1168: an agent never reads a health list's Playbook")
spec = requests.get(V + "/openapi.json", headers=CLH).json()
check("/lists/{id}/playbook" in spec["paths"] and "/lists/{id}/playbook/proposals" in spec["paths"] and "Playbook" in spec["components"]["schemas"]
      and spec["paths"]["/lists/{id}/playbook/proposals"]["post"].get("x-kalmido-scope") == "agent"
      and "playbook_proposal" in str(spec), "#1168: OpenAPI documents the routes and the event")

# ---- the playbook in events
A.patch(B + f"/api/lists/{W}", json={"listen_agent_ids": [CL], "agent_members": True})  # members may address the agent
A.patch(B + f"/api/lists/{W2}", json={"listen_agent_ids": [CL]})
s1 = last_seq()
T1 = Ca.post(B + "/api/tasks", json={"title": "Receipt dentist 80 EUR", "list_id": W}).json()["id"]
ev = wait_for(lambda: events(kinds={"task_added"}, since=s1))
pb = (ev[0]["data"].get("playbook") or {}) if ev else {}
check(ev and pb.get("text") == eff and pb.get("list_id") == W and pb.get("version") == d["version"] and pb.get("updated_at"),
      "#1168: task_added carries the playbook " + str(pb)[:200])
s1 = last_seq()
Ca.post(B + f"/api/tasks/{T1}/comments", json={"body": f"<@{CL}> please read this receipt"})
ev = wait_for(lambda: events(kinds={"mention", "comment"}, since=s1))
check(ev and all((e["data"].get("playbook") or {}).get("text") == eff for e in ev), "#1168: mention / comment carry it " + str([e["event"] for e in ev]))
s1 = last_seq()
A.post(B + "/api/tasks", json={"title": "Loose task", "list_id": W2})
ev = wait_for(lambda: events(kinds={"task_added"}, since=s1))
check(ev and all((e["data"].get("playbook") or {}).get("text") == "Household rules: be brief." for e in ev), "#1168: another list: its own effective Playbook")
check(A.patch(B + f"/api/lists/{W}", json={"agent_tidy": "suggest"}).ok, "setup: tidy suggest")
s1 = last_seq()
Ca.post(B + "/api/tasks", json={"title": "so we need to check the receipt of the pharmacy and also the other one from may", "list_id": W})
ev = wait_for(lambda: events(kinds={"tidy"}, since=s1))
check(ev and (ev[0]["data"].get("playbook") or {}).get("list_id") == W, "#1168: tidy carries the playbook")
s1 = last_seq()
A.patch(B + f"/api/admin/agents/{CL}", json={"proposals": "shared"})
r = A.post(B + "/api/proposals", json={"kind": "cleanup", "list_id": W})
ev = wait_for(lambda: events(kinds={"job_request"}, since=s1))
check(r.status_code in (200, 201) and ev and (ev[0]["data"].get("playbook") or {}).get("text") == eff,
      "#1168: job_request of a cleanup (list_id on top) carries the playbook " + r.text[:200])
check(all("playbook" not in e["data"] for e in events(OTH)), "#1168: nothing for an agent outside the list")

# ---- agent proposals
P = V + f"/lists/{W}/playbook/proposals"
r = requests.post(P, headers=CLH, json={"text": "Receipts: read amount, date, doctor. Then mark them submitted. Add the insurer.",
                                        "note": "The insurer is needed for the claim."})
check(r.status_code == 201 and r.json()["state"] == "open" and r.json()["base_version"] == 4, "#1168: the agent proposes a change " + r.text[:200])
P1 = r.json().get("id")
check(requests.post(P, headers=CLH, json={"text": "x", "secret": 1}).status_code == 400, "#1168: unknown fields -> 400")
check(requests.post(P, headers=CLH, json={"text": "x" * 8001}).status_code == 400, "#1168: too long -> 400")
check(requests.post(P, headers=CLH, json={"text": A.get(PB(W)).json()["text"]}).status_code == 400, "#1168: the same text is no proposal")
check(requests.post(V + f"/lists/{W2}/playbook/proposals", headers=OTH, json={"text": "x"}).status_code == 404, "#1168: an agent outside the list: 404")
check(requests.post(P, headers={"Authorization": "Bearer x"}, json={"text": "x"}).status_code == 401, "#1168: no token: 401")
check(A.get(PB(W)).json()["proposals"][0]["agent"] == {"id": CL, "name": "Claude"} and A.get(PB(W)).json()["proposals"][0]["note"].startswith("The insurer"),
      "#1168: the owner sees the open proposal")
check(Ca.get(PB(W)).json()["proposals"] == [], "#1168: an editor does not")
for who, s in (("alice", A), ("bob", Bo)):
    nw = s.get(B + "/api/news").json()
    items = nw.get("items", nw if isinstance(nw, list) else [])
    check(any(i.get("kind") == "playbook_proposal" and i.get("list_id") == W and (i.get("data") or {}).get("proposal_id") == P1 for i in items),
          f"#1168: {who} gets a News item " + str(items)[:200])
nw = Ca.get(B + "/api/news").json()
check(not any(i.get("kind") == "playbook_proposal" for i in nw.get("items", [])), "#1168: the editor gets none")
P2 = requests.post(P, headers=CLH, json={"text": "proposal two"}).json().get("id")
P3 = requests.post(P, headers=CLH, json={"text": "proposal three"}).json().get("id")
check(requests.post(P, headers=CLH, json={"text": "proposal four"}).status_code == 409, "#1168: at most 3 open proposals per agent and list")
check(Ca.post(PB(W) + f"/proposals/{P1}/apply", json={}).status_code == 403, "#1168: an editor cannot apply")
s1 = last_seq()
r = A.post(PB(W) + f"/proposals/{P1}/apply", json={"text": "Receipts: amount, date, doctor, insurer. Mark them submitted."})
check(r.ok and r.json()["version"] == 5, "#1168: the owner applies an edited version " + r.text[:200])
check(A.get(PB(W) + "/versions").json()["versions"][0]["source"] == "proposal" and A.get(PB(W)).json()["text"].startswith("Receipts: amount"),
      "#1168: source proposal, the edited text")
ev = wait_for(lambda: events(kinds={"playbook_proposal"}, since=s1))
e = ev[0]["data"] if ev else {}
check(e.get("state") == "applied" and e.get("proposal_id") == P1 and e.get("list_id") == W and e.get("version") == 5
      and (e.get("playbook") or {}).get("text", "").endswith("Mark them submitted."), "#1168: event playbook_proposal applied " + str(e)[:300])
check(A.post(PB(W) + f"/proposals/{P1}/apply", json={}).status_code == 409, "#1168: applied twice -> 409")
r = Bo.post(PB(W) + f"/proposals/{P2}/discard")
check(r.ok, "#1168: the list admin discards")
ev = wait_for(lambda: [x for x in events(kinds={"playbook_proposal"}, since=s1) if x["data"]["state"] == "discarded"])
check(ev and ev[0]["data"]["proposal_id"] == P2, "#1168: event playbook_proposal discarded")
check([p["id"] for p in A.get(PB(W)).json()["proposals"]] == [P3], "#1168: one open proposal left")
check(A.post(PB(W2) + f"/proposals/{P3}/apply", json={}).status_code == 404, "#1168: a proposal of another list: 404")

# ---- scheduled checks of a list
C = B + f"/api/lists/{W}/checks"
r = A.get(C)
check(r.ok and r.json()["checks"] == [] and r.json()["agents"] == [{"id": CL, "name": "Claude"}] and r.json()["max"] == 5,
      "#1168: the agents to choose " + r.text[:200])
check(Ca.get(C).status_code == 403, "#1168: an editor cannot plan checks")
check(A.post(C, json={"agent_id": OT, "freq": "daily", "time": "07:00"}).status_code == 400, "#1168: an agent outside the list -> 400")
check(A.post(C, json={"agent_id": CL, "freq": "hourly", "time": "07:00"}).status_code == 400, "#1168: a bad rhythm -> 400")
check(A.post(C, json={"agent_id": CL, "freq": "daily", "time": "07:00", "title": "x"}).status_code == 400, "#1168: unknown fields -> 400")
r = A.post(C, json={"agent_id": CL, "freq": "weekdays", "time": "07:00", "tz": "Europe/Berlin", "prompt": "Match the bank lines."})
k = r.json() if r.status_code == 201 else {}
check(r.status_code == 201 and k["agent"]["id"] == CL and k["by"]["id"] == ALICE and k["title"] == "Playbook check: Receipts" and k["enabled"]
      and k["next_at"] and k["prompt"] == "Match the bank lines.", "#1168: a check is planned " + r.text[:300])
K1 = k.get("id")
r = Bo.post(C, json={"agent_id": CL, "freq": "daily", "time": "08:00"})
K2 = r.json().get("id")
check(r.status_code == 201 and r.json()["prompt"] == "", "#1168: the list admin plans one without a prompt")
check([x["id"] for x in A.get(PB(W)).json()["checks"]] == [K1, K2], "#1168: the checks show in the Playbook view")
plans = A.get(B + f"/api/agents/{CL}/schedules").json()["data"]
check(any(p["id"] == K1 and p["list_check"] for p in plans), "#1168: the agent's manager (admin) still sees them among the plans")
plans = Bo.get(B + f"/api/agents/{CL}/schedules")
check(not any(p["id"] == K2 for p in plans.json().get("data", [])) if plans.ok else plans.status_code == 404,
      "#1168: not in bob's own plan list " + plans.text[:200])
vplans = requests.get(V + "/agent/schedules", headers=CLH).json()["data"]
check(any(p["id"] == K1 and p["list_check"] for p in vplans), "#1168: the agent reads them (list_check true)")
for i in range(3):
    A.post(C, json={"agent_id": CL, "freq": "daily", "time": f"1{i}:00"})
check(A.post(C, json={"agent_id": CL, "freq": "daily", "time": "20:00"}).status_code == 409, "#1168: at most 5 checks per list")
for x in A.get(C).json()["checks"][2:]:
    check(A.delete(B + f"/api/list-checks/{x['id']}").ok, "#1168: delete a check")
check(Ca.patch(B + f"/api/list-checks/{K1}", json={"time": "06:00"}).status_code == 404, "#1168: an editor cannot change it")
r = Bo.patch(B + f"/api/list-checks/{K1}", json={"time": "06:30", "prompt": ""})
check(r.ok and r.json()["time"] == "06:30" and r.json()["prompt"] == "", "#1168: the list admin changes alice's check")
# the watchdog sends it
A.patch(B + f"/api/list-checks/{K2}", json={"enabled": False})
open_ids = sorted(t["id"] for t in A.get(B + "/api/state").json()["tasks"] if t["list_id"] == W and not t.get("parent_id") and t["status"] in (0, "open"))
s1 = last_seq()
past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
dbx("UPDATE agent_schedules SET next_at=? WHERE id=?", (past, K1), write=True)
ev = wait_for(lambda: [x for x in events(kinds={"scheduled_job"}, since=s1) if x["data"]["schedule_id"] == K1])
e = ev[0]["data"] if ev else {}
check(len(ev) == 1 and e.get("list_check") is True and e.get("list_id") == W and (e.get("list") or {}).get("name") == "Receipts"
      and sorted(e.get("open_task_ids") or []) == open_ids and e.get("open_tasks_more") is False
      and e.get("prompt") == "Check the list against its Playbook" and (e.get("playbook") or {}).get("list_id") == W
      and "propose_playbook" in e.get("hint", "") and e.get("by", {}).get("id") == ALICE and e.get("manual") is False,
      "#1168: the watchdog sent scheduled_job with list_check, open_task_ids and the playbook " + str(e)[:500])
r = A.post(B + f"/api/list-checks/{K1}/run")
check(r.status_code == 429, "#1168: Check now right after a run -> 429")
dbx("UPDATE agent_schedules SET last_at=NULL WHERE id=?", (K1,), write=True)
s1 = last_seq()
r = Bo.post(B + f"/api/list-checks/{K1}/run")
ev = wait_for(lambda: events(kinds={"scheduled_job"}, since=s1))
check(r.ok and r.json()["last_state"] == "manual" and ev and ev[0]["data"]["manual"] is True and ev[0]["data"]["manual_by"]["id"] == BOB,
      "#1168: Check now by the list admin " + r.text[:200])
check(A.post(B + f"/api/list-checks/{K2}/run").ok, "#1168: a switched-off check can still be run by hand")
# the agent leaves the list: the check switches itself off
A.delete(B + f"/api/lists/{W}/members/{CL}")
dbx("UPDATE agent_schedules SET last_at=NULL WHERE id=?", (K1,), write=True)
r = A.post(B + f"/api/list-checks/{K1}/run")
k = next((x for x in A.get(C).json()["checks"] if x["id"] == K1), {})
check(r.status_code == 409 and k.get("enabled") is False and k.get("last_state") == "no_list", "#1168: no agent in the list -> the check switches off " + str(k)[:200])
A.put(B + f"/api/lists/{W}/members", json={"user_id": CL, "role": "edit"})

# ---- templates, export, folder rename
r = A.post(B + "/api/templates", json={"list_id": W, "name": "Receipts tpl"})
tpl = r.json()
check(r.ok and tpl["data"].get("playbook", "").startswith("Receipts: amount"), "#1168: a list template carries the list's own Playbook")
r = A.post(B + f"/api/templates/{tpl['id']}/apply", json={"name": "Receipts 2027"})
nl = r.json().get("list_id") or r.json().get("id")
nl = nl or next((x["id"] for x in A.get(B + "/api/state").json()["lists"] if x["name"] == "Receipts 2027"), None)
vs = A.get(PB(nl) + "/versions").json().get("versions", []) if nl else []
check(nl and A.get(PB(nl)).json()["text"].startswith("Receipts: amount") and [v["source"] for v in vs] == ["template"],
      "#1168: the new list from the template gets it as version 1 (source template) " + r.text[:200])
ex = A.get(B + "/api/export.json").json()
check(any(p["list_id"] == W and p["version"] == 5 for p in ex.get("playbooks", [])) and any(p["folder"] == "Home/Money" for p in ex.get("playbooks", []))
      and any(p["id"] == P3 for p in ex.get("playbook_proposals", [])), "#1168: the account export holds the Playbooks and proposals")
check(not any(p.get("owner_id") not in (None, ALICE) for p in Bo.get(B + "/api/export.json").json().get("playbooks", [])), "#1168: only one's own")
check(A.post(B + "/api/folders/rename", json={"old": "Home", "new": "House"}).ok, "setup: rename the folder")
d = A.get(PB(W)).json()
check([x["folder"] for x in d["folders"]] == ["House", "House/Money"] and d["effective"].startswith("Household rules"),
      "#1168: the folder's Playbooks go along with a rename " + str(d["folders"])[:200])
check(A.get(F, params={"folder": "Home"}).json()["text"] == "", "#1168: nothing left under the old name")
# review M3: a removed folder's own Playbook ends with an empty version (a new folder of that name starts without the old rules)
TMPL = A.post(B + "/api/lists", json={"name": "Scratch", "folder": "Tmp"}).json()["id"]
check(A.put(F, json={"folder": "Tmp", "text": "Old rules of Tmp."}).ok, "setup: Playbook of the folder Tmp")
check(A.post(B + "/api/folders/delete", json={"name": "Tmp"}).ok, "setup: remove the folder Tmp")
d = A.get(F, params={"folder": "Tmp"}).json()
check(d["text"] == "" and [v["version"] for v in A.get(F + "/versions", params={"folder": "Tmp"}).json()["versions"]] == [2, 1],
      "#1168: the removed folder's Playbook ends empty, its history stays " + str(d)[:200])

# ---- a backup with the new tables verifies and restores
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, "backup: back up now " + r.text[:100])
items = wait_for(lambda: [x for x in A.get(B + "/api/admin/backups").json().get("items", []) if x["kind"] == "manual"], 30)
name = items[0]["name"] if items else ""
r = A.post(B + f"/api/admin/backups/{name}/verify", json={})
check(r.ok and r.json().get("ok"), "backup: a backup with playbooks verifies " + r.text[:200])
dbx("DELETE FROM playbooks", write=True)
dbx("DELETE FROM playbook_proposals", write=True)
r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "name": name})
check(r.ok and r.json().get("ok"), "backup: restore " + r.text[:200])
A = sess("alice")
d = A.get(PB(W)).json()
check(d.get("version") == 5 and len(A.get(PB(W) + "/versions").json()["versions"]) == 5 and [p["id"] for p in d.get("proposals", [])] == [P3]
      and [x["folder"] for x in d.get("folders", [])] == ["House", "House/Money"], "backup: the Playbooks, versions and proposals are back " + str(d)[:300])

# ---- deleting the list removes its Playbook
A.patch(B + f"/api/lists/{nl}", json={"archived": True})
check(A.delete(B + f"/api/lists/{nl}").ok, "setup: delete the template list")
check(dbx("SELECT COUNT(*) FROM playbooks WHERE list_id=?", (nl,))[0][0] == 0, "#1168: a deleted list takes its Playbook along")

print(f"p2390_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
