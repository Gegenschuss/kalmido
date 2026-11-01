#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.392.0 D (#3369): what waits for a person and the delivery report, own container (start.sh). Invented people and texts only.
freelancer-matrix: tasks, lists
 - GET /api/inbox and GET /api/v1/me/waiting: the same data, empty when nothing waits
 - each kind once: a waiting job, chat and comment cards, merge / integrate requests, a review with me as the reviewer, my
   blocked task, a one-way step without a yes (only with the list's switch on); settled = gone
 - only who can settle it: a plain member sees no gate or yes, a stranger nothing, an agent of a person gets only what the lists
   shared with it hold and 404 for someone it does not reach, a personal token stays within its lists
 - a list with the lock: the API shows no text, the request's text is gone for the web app too
 - the sidebar key v:mine_wait (with its underscore) saves
 - the delivery report: day / since / default, without a repository, branch, main, released, stuck by a waiting job, a blocked
   task, a stranger 404, a list with the lock 409, both date and since 400, the markdown has fixed headings and the language
 - everything above in the list of a person without an organisation
usage: p2392_d_api_test.py <datadir>"""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as DBX  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
import kt  # noqa: E402
from kt import check, B, dbx, H, done  # noqa: E402

V = B + "/api/v1"


def hdr(tok):
    return {"Authorization": "Bearer " + tok, **H}


def agent(s, name, lid):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "tasks:write", "comments"]})
    assert r.status_code in (200, 201), r.text
    aid = r.json()["id"]
    assert s.put(B + f"/api/lists/{lid}/members", json={"user_id": aid, "role": "edit"}).ok
    return aid, hdr(s.post(B + f"/api/my/agents/{aid}/token").json()["token"])


def task(s, lid, title):
    return s.post(B + "/api/tasks", json={"title": title, "list_id": lid}).json()["id"]


def inbox(s):
    r = s.get(B + "/api/inbox")
    assert r.ok, r.text
    return r.json()


def kinds(d, k):
    return [x for x in d["items"] if x["kind"] == k]


def report(h, lid, **q):
    return requests.get(V + f"/lists/{lid}/delivery-report", headers=h, params=q)


kt.fresh()
A = kt.setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FU, F = freelancer(B, A, "frida")  # a person without an organisation is the main case
GU, G = freelancer(B, A, "gert")
XU, X = freelancer(B, A, "xena")  # a stranger
L = F.post(B + "/api/lists", json={"name": "Release", "kind": "project", "ptype": "software"}).json()["id"]
L2 = F.post(B + "/api/lists", json={"name": "Other", "kind": "project"}).json()["id"]
check(F.put(B + f"/api/lists/{L}/members", json={"user_id": GU, "role": "edit"}).ok, "setup: a plain member")
AID, AH = agent(F, "fridabot", L)
PAT = hdr(F.post(B + "/api/me/tokens", json={"name": "all", "scopes": ["read"]}).json()["token"])

# ================================================================== empty, both routes
d = inbox(F)
check(d["total"] == 0 and d["items"] == [] and d["counts"]["job"] == 0, "nothing waits " + str(d))
r = requests.get(V + "/me/waiting", headers=PAT)
check(r.ok and r.json() == d, "the API gives the same " + r.text[:200])
check(requests.get(V + "/me/waiting", headers=AH).status_code == 400, "an agent names the person")
check(requests.get(V + "/me/waiting", headers=AH, params={"user_id": XU}).status_code == 404, "someone it does not reach: 404")
check(requests.get(V + "/me/waiting", headers=PAT, params={"user_id": GU}).status_code == 404, "a token reads only its own")

# ================================================================== each kind
T1, T2, T3, T4, T5, T6 = (task(F, L, f"Task {i}") for i in range(1, 7))
J = requests.post(V + "/agent/jobs", headers=AH, json={"title": "Please confirm the cut", "task_id": T1, "state": "waiting", "user_id": FU})
check(J.ok, "setup: a waiting job " + J.text[:200])
JID = J.json().get("id") or J.json().get("data", {}).get("id")
C = requests.post(V + f"/agent/chats/{FU}", headers=AH, json={"body": "May I?", "approval": {"title": "Chat card"}})
check(C.ok, "setup: a chat card " + C.text[:200])
K = requests.post(V + f"/tasks/{T2}/comments", headers=AH, json={"body": "May I?", "approval": {"title": "Comment card"}})
check(K.ok, "setup: a comment card " + K.text[:200])
Gt = requests.post(V + f"/tasks/{T3}/comments", headers=AH, json={"body": "Ready", "suggestion": {"kind": "integrate", "evidence": "tests green", "source": "feat/x"}})
check(Gt.ok, "setup: an integrate request " + Gt.text[:200])
GID = Gt.json().get("id")
check(F.post(B + f"/api/tasks/{T4}/review", json={"action": "request", "reviewer_id": FU}).ok, "setup: a review")
F.patch(B + f"/api/tasks/{T5}", json={"assignee_id": FU})
check(F.post(B + "/api/deps", json={"task_id": T5, "blocker_id": T6}).ok, "setup: blocked")
TI = task(F, L, "Drop the old column")
check(requests.patch(V + f"/tasks/{TI}", headers=AH, json={"irreversible": {"reason": "No way back"}}).ok, "setup: the mark")

d = inbox(F)
check(not kinds(d, "irreversible"), "the switch off: no one-way step waits")
check(F.patch(B + f"/api/lists/{L}", json={"irreversible_needs_yes": True}).ok, "setup: the switch")
d = inbox(F)
check(requests.get(V + "/me/waiting", headers=PAT).json() == d, "the API gives the same, now with data")
j = kinds(d, "job")
check([x["id"] for x in j] == [JID] and j[0]["task_id"] == T1 and j[0]["agent_id"] == AID and j[0]["list_name"] == "Release", "the job " + str(j))
ap = {x["title"]: x for x in kinds(d, "approval")}
check(set(ap) == {"Chat card", "Comment card"} and ap["Chat card"]["source"] == "chat" and ap["Comment card"]["source"] == "comment"
      and ap["Comment card"]["task_id"] == T2, "both cards " + str(ap))
g = kinds(d, "gate")
check(len(g) == 1 and g[0]["gate"] == "integrate" and g[0]["branch"] == "feat/x" and g[0]["task_id"] == T3, "the request " + str(g))
check([x["id"] for x in kinds(d, "review")] == [T4], "the review")
b = kinds(d, "blocked")
check([x["id"] for x in b] == [T5] and b[0]["reason"] == "blocked" and b[0]["open_blockers"] == 1, "my blocked task " + str(b))
ir = kinds(d, "irreversible")
check([x["id"] for x in ir] == [TI] and ir[0]["why"] == "No way back", "the one-way step " + str(ir))
check(d["total"] == 7 and sum(d["counts"].values()) == 7 and d["counts"]["approval"] == 2, "counts " + str(d["counts"]))

# ================================================================== only who can settle it
dg = inbox(G)
check(not kinds(dg, "gate") and not kinds(dg, "irreversible") and not kinds(dg, "job") and not kinds(dg, "approval"), "a plain member settles none " + str(dg["counts"]))
check(inbox(X)["total"] == 0, "a stranger sees nothing")
da = requests.get(V + "/me/waiting", headers=AH, params={"user_id": FU}).json()
check(da["counts"]["job"] == 1 and da["counts"]["approval"] == 2 and da["counts"]["gate"] == 1, "her agent, a shared list " + str(da["counts"]))
TO = task(F, L2, "Private work")
F.post(B + f"/api/tasks/{TO}/review", json={"action": "request", "reviewer_id": FU})
ids = [x["id"] for x in requests.get(V + "/me/waiting", headers=AH, params={"user_id": FU}).json()["items"] if x["kind"] == "review"]
check(TO not in ids and TO in [x["id"] for x in kinds(inbox(F), "review")], "a list not shared with the agent stays out " + str(ids))
LT = hdr(F.post(B + "/api/me/tokens", json={"name": "one", "scopes": ["read"], "list_ids": [L2]}).json()["token"])
d2 = requests.get(V + "/me/waiting", headers=LT).json()
check([x["id"] for x in d2["items"]] == [TO], "a token limited to one list: no job or chat card outside it " + str(d2["counts"]))

# ================================================================== settled = gone
check(requests.patch(V + f"/agent/jobs/{JID}", headers=AH, json={"state": "done"}).ok, "the job ends")
check(F.post(B + f"/api/comments/{GID}/decide", json={"decision": "reject"}).ok, "the request is decided")
check(F.post(B + f"/api/tasks/{TI}/irreversible-yes").ok, "the yes")
check(F.post(B + f"/api/tasks/{T4}/review", json={"action": "approve"}).ok, "the review is done")
d = inbox(F)
check(not kinds(d, "job") and not kinds(d, "gate") and not kinds(d, "irreversible") and T4 not in [x["id"] for x in kinds(d, "review")], "all gone " + str(d["counts"]))

# ================================================================== the sidebar key
r = F.patch(B + "/api/settings", json={"fav_items": ["v:today", "v:mine_wait"]})
check(r.ok, "v:mine_wait saves " + r.text[:200])

# ================================================================== the delivery report: no repository
check(report(PAT, L).ok, "default: the last 24 hours")
TD = task(F, L, "Shipped work")
check(F.post(B + f"/api/tasks/{TD}/complete").ok or F.patch(B + f"/api/tasks/{TD}", json={"status": 2}).ok, "setup: a completed task")
TM = task(F, L, "Moves along")
requests.post(V + f"/tasks/{TM}/comments", headers=AH, json={"body": "On it"})
JW = requests.post(V + "/agent/jobs", headers=AH, json={"title": "Stuck job", "task_id": T1, "state": "waiting", "user_id": FU})
r = report(AH, L)
check(r.ok, "an agent reads it in a shared list " + r.text[:200])
m = r.json()
check(m["repository"] is False and m["list"]["id"] == L, "no repository: it still works")
check(TD in [x["id"] for x in m["completed"]] and m["counts"]["completed"] >= 1, "completed " + str(m["counts"]))
check(TM in [x["id"] for x in m["in_progress"]], "in progress: a comment in the period " + str(m["in_progress"])[:300])
st = {x["id"]: x for x in m["stuck"]}
check(st.get(T1, {}).get("reason") == "job", "stuck: a waiting job " + str(st)[:300])
check(st.get(T5, {}).get("reason") == "blocked", "stuck: a blocked task")
check(m["released"] == [] and m["in_main"] == [], "no build states")
check("# Delivery report: Release" in m["markdown"] and "## Stuck" in m["markdown"] and "Shipped work" in m["markdown"], "fixed headings " + m["markdown"][:300])
check("# Lieferbericht: Release" in report(AH, L, lang="de").json()["markdown"], "lang de")
check(report(AH, L, lang="xx").status_code == 400, "an unknown language")
today = str(kt.today())
rd = report(AH, L, date=today)
check(rd.ok and TD in [x["id"] for x in rd.json()["completed"]], "date = today " + rd.text[:200])
check(TD not in [x["id"] for x in report(AH, L, date="2001-02-03").json()["completed"]], "another day: not in it")
fut = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
check(report(AH, L, since=fut).json()["counts"]["completed"] == 0, "since: after the completion")
check(report(AH, L, date=today, since=fut).status_code == 400, "date and since together: 400")
check(report(AH, L, date="not-a-day").status_code == 400, "a bad date: 400")
check(report(AH, L2).status_code == 404, "an agent outside the list: 404")
check(report(hdr(X.post(B + "/api/me/tokens", json={"name": "x", "scopes": ["read"]}).json()["token"]), L).status_code == 404, "a stranger: 404")

# ================================================================== the build states (the poll's tables, filled by hand)
c = DBX.connect(os.path.join(kt.DATA, "tasks.db"))
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
TB, TN, TR, TS = (task(F, L, x) for x in ("On a branch", "On main", "Tagged", "Idle branch"))
cid = c.execute("""INSERT INTO git_conns(list_id, provider, owner, repo, created_by, created_at, default_branch, next_at)
                   VALUES(?, 'github', 'acme', 'app', ?, ?, 'main', 9999999999) RETURNING id""", (L, FU, now)).fetchone()[0]
for tid, sha, branch, tag in ((TN, "aaa", "main", ""), (TR, "bbb", "main", "v1.2.0"), (TB, "ccc", "feat/b", ""), (TS, "ddd", "feat/s", "")):
    c.execute("INSERT INTO git_commits(conn_id, sha, branch, tag, at) VALUES(?,?,?,?,?)", (cid, sha, branch, tag, now))
    c.execute("INSERT INTO git_links(task_id, conn_id, kind, ref, created_at) VALUES(?,?,'commit',?,?)", (tid, cid, sha, now))
c.execute("INSERT INTO git_tags(conn_id, name, seen_at) VALUES(?, 'v1.2.0', ?)", (cid, now))
c.commit()
c.close()
requests.post(V + f"/tasks/{TB}/comments", headers=AH, json={"body": "Still on it"})
m = report(AH, L).json()
check(m["repository"] is True, "a repository")
rel = {x["id"]: x for x in m["released"]}
check(rel.get(TR, {}).get("tag") == "v1.2.0", "released: a tag of the period " + str(rel)[:200])
check(TN in [x["id"] for x in m["in_main"]], "in main " + str(m["in_main"])[:200])
check(TB in [x["id"] for x in m["in_progress"]], "a branch that moved is in progress " + str(m["in_progress"])[:300])
st = {x["id"]: x for x in m["stuck"]}
check(st.get(TS, {}).get("reason") == "branch", "stuck: a branch without a merge that did not move " + str(st)[:300])
check(report(AH, L, since=fut).json()["released"] == [], "a tag before the period is not new")

# ================================================================== a list with the lock
dbx("UPDATE lists SET e2e='on' WHERE id=?", (L,))
r = report(AH, L)
check(r.status_code == 409 and r.json()["error"]["code"] == "list_e2e", "the report: 409 " + r.text[:200])
d = requests.get(V + "/me/waiting", headers=PAT).json()
inl = [x for x in d["items"] if x["list_id"] == L]
check(inl and all(not x["title"] and not x["task_title"] and x.get("encrypted") for x in inl), "the API shows no text of it " + str(inl)[:300])
web = [x for x in inbox(F)["items"] if x["list_id"] == L and x["kind"] == "approval" and x["source"] == "comment"]
check(web and not web[0]["title"], "the web app: no text of the agent's request")

sys.exit(done("p2392_d_api"))
