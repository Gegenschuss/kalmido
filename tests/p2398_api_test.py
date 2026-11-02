#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.398.0 (#3406): review and statistics per workspace (freelancer-matrix: personal)
 - GET /api/life/review and GET /api/stats take ?space=private|org:<id>: only the tasks (and focus / tracked time) of that
   workspace's projects; without it (All workspaces) everything as before
 - the journal is private: never part of an organisation's review, there in Private and All
 - an unknown space is a 400, an organisation one is not a member of a 404 (nothing of it is shown)
 - the workspace gate: the review and the statistics belong to the area review (an organisation's admin may switch it off:
   then 403 in that organisation only), not to Home & life
 - a person without an organisation: ?space=private works the same, with the journal
usage: p2398_api_test.py <datadir>      (KMT_NOSTART=1 / P2398_NOSTART=1: a running server)"""
from freelancer_fixture import FEATURES, freelancer
from kt import B, check, done, fresh, setup

fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2398")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Nordwind", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123", "email": "carol@example.com"}).json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Fremd", "admin_id": CAROL})
check(r.status_code == 201, f"setup: a second organisation without Alice {r.status_code}")
OTHER = r.json()["id"] if r.ok else None
check(OTHER not in [w["id"] for w in A.get(B + "/api/state").json()["me"]["workspaces"]], "setup: Alice is not in Fremd")

A.patch(B + "/api/settings", json={"workspace": "private"})  # a new list goes to the chosen workspace (ws_chosen_org)
PRV = A.post(B + "/api/lists", json={"name": "Garden"}).json()["id"]
ORGL = A.post(B + "/api/lists", json={"name": "Client shoot", "org_id": ORG}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": "all"})
ls = {x["id"]: x.get("org_id") for x in A.get(B + "/api/state").json()["lists"]}
check(ls.get(ORGL) == ORG and not ls.get(PRV), f"setup: Client shoot belongs to Nordwind, Garden is private {ls.get(ORGL)} {ls.get(PRV)}")


def task(lid, title, **kw):
    r = A.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


for lid, t in ((PRV, "Water the roses"), (ORGL, "Send the call sheet")):
    check(A.post(B + f"/api/tasks/{task(lid, t)}/complete", json={}).ok, f"setup: {t} done")
A.put(B + "/api/life/journal/" + A.get(B + "/api/life/review").json()["from"], json={"text": "A quiet day", "mood": 4})


def titles(j, k="done"):
    return sorted(x["title"] for x in j[k])


# ================================================================== the review
allr = A.get(B + "/api/life/review").json()
check(titles(allr) == ["Send the call sheet", "Water the roses"], f"#3406: All: both done tasks {titles(allr)}")
check(any(x.get("text") == "A quiet day" for x in allr.get("journal") or []), "#3406: All: the journal is there")
pr = A.get(B + "/api/life/review?space=private").json()
check(titles(pr) == ["Water the roses"], f"#3406: Private: only the private project's task {titles(pr)}")
check(any(x.get("text") == "A quiet day" for x in pr.get("journal") or []), "#3406: Private: the journal is there")
r = A.get(B + f"/api/life/review?space=org:{ORG}")
check(r.ok, f"#3406: the organisation's review answers {r.status_code} {r.text[:160]}")
orr = r.json()
check(titles(orr) == ["Send the call sheet"], f"#3406: organisation: only its project's task {titles(orr)}")
check("journal" not in orr and "journal_sealed" not in orr, "#3406: organisation: no journal (it is private)")
check(A.get(B + "/api/life/review?space=nope").status_code == 400, "#3406: an unknown space is 400")
if OTHER:
    check(A.get(B + f"/api/life/review?space=org:{OTHER}").status_code == 404, "#3406: an organisation I am not in is 404")
    check(A.get(B + f"/api/stats?space=org:{OTHER}").status_code == 404, "#3406: … for the statistics too")

# ================================================================== the statistics
sa = A.get(B + "/api/stats").json()
check(sa["done"]["today"] == 2, f"#3406: All: 2 done today {sa['done']['today']}")
sp = A.get(B + "/api/stats?space=private").json()
check(sp["done"]["today"] == 1 and [x["id"] for x in sp["done"]["by_list"]] == [PRV], f"#3406: Private: 1 done, by the private project {sp['done']}")
so = A.get(B + f"/api/stats?space=org:{ORG}").json()
check(so["done"]["today"] == 1 and [x["id"] for x in so["done"]["by_list"]] == [ORGL], f"#3406: organisation: 1 done, by its project {so['done']}")
check(A.get(B + "/api/stats?space=org:x").status_code == 400, "#3406: statistics: an unknown space is 400")

# ================================================================== the workspace gate: area review, not Home
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": ["life"]}).ok, "setup: Home switched off in Nordwind")
check(A.get(B + f"/api/life/review?space=org:{ORG}").ok, "#3406: Home off: the organisation's review still answers (area review)")
check(A.get(B + f"/api/stats?space=org:{ORG}").ok, "#3406: Home off: the statistics still answer")
check(A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": ["review"]}).ok, "#3406: an admin may switch the review off in the organisation")
check(A.get(B + f"/api/life/review?space=org:{ORG}").status_code == 403, "#3406: review off: the organisation's review is 403")
check(A.get(B + f"/api/stats?space=org:{ORG}").status_code == 403, "#3406: review off: the organisation's statistics are 403")
check(A.get(B + "/api/life/review?space=private").ok and A.get(B + "/api/stats?space=private").ok, "#3406: review off in the organisation: Private stays open")
A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": []})
A.patch(B + "/api/settings", json={"workspace": "all"})

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
fl = Fr.post(B + "/api/lists", json={"name": "Portfolio"}).json()["id"]
ft = Fr.post(B + "/api/tasks", json={"title": "Edit the reel", "list_id": fl}).json()["id"]
check(Fr.post(B + f"/api/tasks/{ft}/complete", json={}).ok, "freelancer: setup done task")
fr = Fr.get(B + "/api/life/review?space=private")
check(fr.ok and titles(fr.json()) == ["Edit the reel"] and "journal" in fr.json(), f"#3406 freelancer: the review of Private with the journal {fr.status_code}")
fs = Fr.get(B + "/api/stats?space=private")
check(fs.ok and fs.json()["done"]["today"] == 1, f"#3406 freelancer: the statistics of Private {fs.status_code}")
check(Fr.get(B + f"/api/life/review?space=org:{ORG}").status_code == 404, "#3406 freelancer: someone else's organisation is 404")
check("Water the roses" not in str(Fr.get(B + "/api/life/review").json()), "#3406 freelancer: never someone else's tasks")

done("p2398_api")
