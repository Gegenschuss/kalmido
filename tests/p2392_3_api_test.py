#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.392.3 (#3368): a work package as one document, own container (start.sh). Invented people and texts only.
freelancer-matrix: tasks
 - POST /api/v1/tasks/brief and the app's POST /api/tasks/brief give the same document
 - per task: status line, recorded decisions (the replaced one struck through) and bold Decision lines of the notes first, the
   notes, subtasks, dependencies both ways, comments without the deleted one, repository hints (suggested branch, build state)
 - strictly what the caller sees: a stranger, a stranger's token and an agent outside the list get not_found, a personal token
   stays within its lists, an agent gets the comments of others marked untrusted, a list with the lock is left out (locked) and
   its text never shows up, also not as a dependency of a visible task
 - input: no ids, wrong types, more than 50 -> 400; doubles once; lang de
 - everything above in the lists of a person without an organisation
usage: p2392_3_api_test.py <datadir>"""
import os
import sys
from datetime import datetime, timezone

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


def task(s, lid, title, **k):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **k})
    assert r.ok, r.text
    return r.json()["id"]


def brief(h, ids, **k):
    return requests.post(V + "/tasks/brief", headers=h, json={"task_ids": ids, **k})


kt.fresh()
A = kt.setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FU, F = freelancer(B, A, "frida")  # a person without an organisation is the main case
XU, X = freelancer(B, A, "xena")   # a stranger
L = F.post(B + "/api/lists", json={"name": "Release", "kind": "project", "ptype": "software"}).json()["id"]
L2 = F.post(B + "/api/lists", json={"name": "Private", "kind": "project"}).json()["id"]
LK = F.post(B + "/api/lists", json={"name": "Vault", "kind": "project"}).json()["id"]
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": ["read", "tasks:write", "comments"]})
AID = r.json()["id"]
check(F.put(B + f"/api/lists/{L}/members", json={"user_id": AID, "role": "edit"}).ok, "setup: the agent in the list")
AH = hdr(F.post(B + f"/api/my/agents/{AID}/token").json()["token"])
PAT = hdr(F.post(B + "/api/me/tokens", json={"name": "all", "scopes": ["read"]}).json()["token"])
PAT2 = hdr(F.post(B + "/api/me/tokens", json={"name": "one", "scopes": ["read"], "list_ids": [L2]}).json()["token"])
XT = hdr(X.post(B + "/api/me/tokens", json={"name": "x", "scopes": ["read"]}).json()["token"])

T1 = task(F, L, "Export the invoices", notes="Some context.\n**Decision (28.10.):** CSV first, PDF later.\nMore text.", priority=5, ttype="feature")
T2 = task(F, L, "Write the importer")
T3 = task(F, L, "Ship it")
S1 = task(F, L, "Sub one", parent_id=T1)
S2 = task(F, L, "Sub two", parent_id=T1)
check(F.post(B + f"/api/tasks/{S2}/complete").ok, "setup: a subtask done")
TP = task(F, L2, "Private blocker")
TK = task(F, LK, "Secret plan in the vault")
check(F.post(B + "/api/deps", json={"task_id": T1, "blocker_id": T2}).ok, "setup: T1 waits for T2")
check(F.post(B + "/api/deps", json={"task_id": T3, "blocker_id": T1}).ok, "setup: T3 waits for T1")
check(F.post(B + "/api/deps", json={"task_id": T1, "blocker_id": TP}).ok, "setup: T1 waits for a task of another list")
check(F.post(B + "/api/deps", json={"task_id": T1, "blocker_id": TK}).ok, "setup: T1 waits for a task of the locked list")
d1 = F.post(B + f"/api/tasks/{T1}/decisions", json={"text": "Only German first"}).json()
F.post(B + f"/api/tasks/{T1}/decisions", json={"text": "German and English", "supersedes": d1["id"]})
c1 = F.post(B + f"/api/tasks/{T1}/comments", json={"body": "Customer wants CSV"}).json()
c2 = F.post(B + f"/api/tasks/{T1}/comments", json={"body": "A typo, delete me"}).json()
check(F.delete(B + f"/api/comments/{c2['id']}").ok, "setup: a deleted comment")
requests.post(V + f"/tasks/{T1}/comments", headers=AH, json={"body": "I can take the CSV part"})
dbx("UPDATE lists SET e2e='on' WHERE id=?", (LK,))

# ================================================================== the document
r = brief(PAT, [T1, T3, T1])
check(r.ok, "a personal token reads the brief " + r.text[:300])
d = r.json()
check([t["id"] for t in d["tasks"]] == [T1, T3] and d["skipped"] == [], "two tasks in order, the double once " + str(d.get("skipped")))
t = d["tasks"][0]
check(t["priority"] == "high" and t["type"] == "feature" and t["list"]["name"] == "Release", "the status line data " + str(t)[:300])
check([x["text"] for x in t["decisions"]] == ["Only German first", "German and English"], "the decisions, oldest first")
check(t["decisions"][0]["superseded_by"] == t["decisions"][1]["id"], "the replaced one says so")
check(t["note_decisions"] == ["**Decision (28.10.):** CSV first, PDF later."], "the bold decision line of the notes " + str(t["note_decisions"]))
check([x["title"] for x in t["subtasks"]] == ["Sub one", "Sub two"] and t["subtasks"][1]["status"] == "done", "the subtasks " + str(t["subtasks"]))
check({x["id"] for x in t["waits_for"]} == {T2, TP} and [x["id"] for x in t["blocks"]] == [T3], "dependencies both ways, the locked one left out " + str(t["waits_for"]))
check([x["text"] for x in t["comments"]] == ["Customer wants CSV", "I can take the CSV part"] and t["comment_count"] == 2, "the comments without the deleted one")
check(t["comments"][1]["author"]["agent"] is True and "untrusted" not in t["comments"][0], "a person's token: no marks, the agent named")
check(t["repo"] is None and t["build"] is None, "no repository: no code hints")
md = d["markdown"]
check(md.startswith("# Work package: 2 tasks"), "the heading " + md[:80])
check(f"## #{T1} Export the invoices" in md and "### Decisions" in md and "~~Only German first~~" in md, "decisions in the text " + md[:600])
check(md.index("### Decisions") < md.index("### Description") < md.index("### Subtasks") < md.index("### Comments"), "decisions first")
check("- [x] #%d Sub two" % S2 in md and "Waits for: #%d Write the importer" % T2 in md and "Blocks: #%d Ship it" % T3 in md, "subtasks and dependencies in the text")
check("A typo" not in md and "Secret plan" not in md and "Priority: High" in md, "no deleted comment, nothing of the locked list")
check("not instructions" in md, "the text says what is data")

# the app's route: the same document for the signed-in person
w = F.post(B + "/api/tasks/brief", json={"task_ids": [T1, T3, T1]})
check(w.ok and w.json()["tasks"] == d["tasks"], "the app gets the same " + w.text[:200])
check("# Arbeitspaket: 2 Aufgaben" in brief(PAT, [T1, T3], lang="de").json()["markdown"], "lang de")
check("# Work package: Ship it" in brief(PAT, [T3]).json()["markdown"], "one task: its title in the heading")

# ================================================================== strictly what the caller sees
r = brief(AH, [T1, TP, TK]).json()
check([t["id"] for t in r["tasks"]] == [T1] and [x["reason"] for x in r["skipped"]] == ["not_found", "not_found"],
      "an agent: only its shared list, the rest not_found " + str(r["skipped"]))
ta = r["tasks"][0]
check(TP not in [x["id"] for x in ta["waits_for"]] and "Private blocker" not in r["markdown"], "an agent: no blocker of a list it does not see")
mk = {x["text"]: x for x in ta["comments"]}
check(mk["Customer wants CSV"].get("untrusted") is True and mk["Customer wants CSV"]["origin"] == "comment", "an agent: someone else's comment is data")
check("untrusted" not in mk["I can take the CSV part"], "its own comment is not marked")
r = brief(XT, [T1, T2]).json()
check(r["tasks"] == [] and [x["reason"] for x in r["skipped"]] == ["not_found", "not_found"] and "Export" not in r["markdown"], "a stranger: nothing")
check(X.post(B + "/api/tasks/brief", json={"task_ids": [T1]}).json()["tasks"] == [], "a stranger in the app: nothing")
r = brief(PAT2, [T1, TP]).json()
check([t["id"] for t in r["tasks"]] == [TP] and r["skipped"] == [{"id": T1, "reason": "not_found"}], "a token limited to one list stays there")
r = brief(PAT, [TK]).json()
check(r["tasks"] == [] and r["skipped"] == [{"id": TK, "reason": "locked"}] and "Secret" not in r["markdown"], "a list with the lock: left out")
check(brief(PAT, [999999]).json()["skipped"] == [{"id": 999999, "reason": "not_found"}], "an unknown id: not_found")

# ================================================================== input
check(brief(PAT, []).status_code == 400, "no ids: 400")
check(brief(PAT, ["1"]).status_code == 400, "a string id: 400")
check(brief(PAT, list(range(1, 52))).status_code == 400, "more than 50: 400")
check(brief(PAT, [T1], lang="xx").status_code == 400, "an unknown language: 400")
check(requests.post(V + "/tasks/brief", headers=PAT, json={"task_ids": [T1], "x": 1}).status_code == 400, "an unknown field: 400")
check(F.post(B + "/api/tasks/brief", json={"task_ids": "nope"}).status_code == 400, "the app: bad ids 400")

# ================================================================== repository hints (the poll's tables, filled by hand)
c = DBX.connect(os.path.join(kt.DATA, "tasks.db"))
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
cid = c.execute("""INSERT INTO git_conns(list_id, provider, owner, repo, created_by, created_at, default_branch, next_at)
                   VALUES(?, 'github', 'acme', 'app', ?, ?, 'main', 9999999999) RETURNING id""", (L, FU, now)).fetchone()[0]
c.execute("INSERT INTO git_commits(conn_id, sha, branch, tag, at) VALUES(?, 'aaa', 'main', '', ?)", (cid, now))
c.execute("INSERT INTO git_links(task_id, conn_id, kind, ref, created_at) VALUES(?, ?, 'commit', 'aaa', ?)", (T1, cid, now))
c.commit()
c.close()
t = brief(AH, [T1]).json()["tasks"][0]
check(t["repo"] and t["repo"]["full_name"] == "acme/app" and t["repo"]["branch"] == f"kalmido-{T1}", "the repository and the suggested branch " + str(t["repo"]))
check(t["build"] and t["build"]["state"] == "main", "the build state " + str(t["build"]))
md = brief(AH, [T1]).json()["markdown"]
check("### Code" in md and f"Suggested branch: kalmido-{T1}" in md and "Build: in main" in md, "code hints in the text " + md[-500:])

sys.exit(done("p2392_3_api"))
