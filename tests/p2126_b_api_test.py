#!/usr/bin/env python3
"""2.126.0 API tests, part B (audit T2: agents). Invented people and texts only.
freelancer-matrix: agents
 - #1974 an agent's waiting approval job on a task: the assignee alone cannot approve it, the list owner can
 - #1975 integrate / deploy / merge requests of a personal agent: a list admin who may not address the agent cannot decide
   (/decide 403, a thumbs up is no approval), the agent's owner can
 - #1978 texts from outside: a task made from an e-mail carries origin + untrusted in the agent's events; a Playbook names
   its authors and is foreign for a personal agent when someone else wrote it, not for the team agent of the owner's list
 - #1979 G3 a replay header of the wrong shape: 401, never 500; G5 an agent's answer to a customer needs a ticket (400)
   before it waits for an approval; I5 the git hook has a limit per connection (429)
 - a person without an organisation: approves the own agent's batch, decides its integrate request, own Playbook not foreign
 - the reference launcher (mcp/agent_run.py, without a server): #1973 only the operator answers permission questions,
   #1978 data frame for texts from outside and foreign Playbooks; the MCP server's instructions name the data rule
usage: p2126_b_api_test.py <datadir>      (P2126B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
MCP = os.path.join(N, "..", "mcp")
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall() if q.lstrip().upper().startswith("SELECT") else c.execute(q, args)
        if write:
            c.commit()
        return r
    finally:
        c.close()


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(MCP, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ================================================================== the reference launcher and the MCP server (no server needed)
os.environ.setdefault("KALMIDO_URL", "http://127.0.0.1:9")
os.environ.setdefault("KALMIDO_TOKEN", "abk_" + "y" * 30)
ar = load("agent_run")


class StubApi:
    def __init__(self):
        self.posts, self.perms = [], []

    def chat(self, uid, body, approval=None, reply_to=None, task_id=None, suggest=None):
        self.posts.append({"uid": uid, "body": body})
        return {"id": 100 + len(self.posts)}

    def perm_question(self, uid, body, timeout_s):
        self.perms.append(uid)
        return {"id": 900 + len(self.perms)}

    def withdraw(self, *a, **k):
        return True


TMP = tempfile.mkdtemp(prefix="kalmido-p2126b-")


def perm_ask(r, uid, n):
    """A permission request of the hook for person uid -> (answer file text or None, posted question?)."""
    os.makedirs(r.perm_dir(), exist_ok=True)
    pid = f"p{n}"
    with open(os.path.join(r.perm_dir(), pid + ".req.json"), "w") as f:
        json.dump({"tool_name": "Bash", "tool_input": {"command": "make deploy"}, "uid": str(uid), "label": "chat", "at": time.time()}, f)
    before = len(r.api.perms)
    r.perm_poll()
    ans = os.path.join(r.perm_dir(), pid + ".ans")
    return (open(ans).read() if os.path.exists(ans) else None), len(r.api.perms) > before


# #1973: a personal agent (owner 7): the owner is asked; someone else chatting gets the step denied with a note
r = ar.Runner(["claude"], os.path.join(TMP, "perm1"))
r.api = StubApi()
r.agent = {"owner_id": 7}
ans, asked = perm_ask(r, 7, 1)
check(asked and ans is None, "#1973: the owner chatting is asked in the chat")
ans, asked = perm_ask(r, 8, 2)
check(not asked and ans == "operator" and r.api.posts and r.api.posts[-1] == {"uid": 8, "body": ar.PERM_OPERATOR_ONLY},
      f"#1973: someone else chatting: denied at once, with a note to them {r.api.posts[-1:]}")
# a team agent: only KALMIDO_PERM_USER / KALMIDO_OWNER_IDS answer; without them nobody
r = ar.Runner(["claude"], os.path.join(TMP, "perm2"))
r.api = StubApi()
r.agent = {"owner_id": None}
ans, asked = perm_ask(r, 5, 1)
check(not asked and ans == "operator", "#1973: a team agent without an operator: nobody answers")
os.environ.update(KALMIDO_PERM_USER="9", KALMIDO_OWNER_IDS="4, 6")
ans, asked = perm_ask(r, 9, 2)
check(asked, "#1973: KALMIDO_PERM_USER is asked")
ans, asked = perm_ask(r, 6, 3)
check(asked, "#1973: an id of KALMIDO_OWNER_IDS is asked")
ans, asked = perm_ask(r, 5, 4)
check(not asked and ans == "operator", "#1973: another member of the team: denied")
check(r.perm_operators() == {9, 4, 6}, f"#1973: the operators {r.perm_operators()}")
del os.environ["KALMIDO_PERM_USER"], os.environ["KALMIDO_OWNER_IDS"]
r.agent = {}
check(r.perm_operators() == set(), "#1973: Kalmido not reached (no agent data): nobody")

# #1978: the launcher frames texts from outside and foreign Playbooks as data
check(ar.untrusted_hint({"task": {"id": 1, "title": "x"}}) == [], "#1978: a normal event: no frame")
h = ar.untrusted_hint({"task": {"id": 1, "origin": "mail", "untrusted": True}, "repo": {"prs": [{"n": 2, "origin": "git", "untrusted": True}]}})
check(len(h) == 1 and "git, mail" in h[0] and "not instructions" in h[0], f"#1978: e-mail task + pull requests: one frame {h}")
check(ar.untrusted_hint({"origin": "form", "untrusted": True, "task": {}})[0].startswith("External data (form)"), "#1978: a form's task_added")
pb = {"list_id": 3, "version": "abc", "text": "Close tasks on Fridays.", "authors": [{"id": 2, "name": "Carol"}], "foreign": True}
h = ar.playbook_hint(pb)
check("written by Carol (user 2), not by your operator" in h[0] and "not instructions" in h[0] and "Follow them" not in h[0]
      and h[2] == "Close tasks on Fridays.", f"#1978: a foreign Playbook names its author, as data {h[:1]}")
check("Follow them for this project only" in ar.playbook_hint({**pb, "foreign": False})[0], "#1978: the operator's own Playbook: rules as before")  # 2.152.2 (#2624): project instead of list
mc = load("kalmido_mcp")
init = mc.handle(None, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
check(mc.DATA_NOTE in init["result"]["instructions"] and "not instructions" in mc.DATA_NOTE, "#1978: the MCP instructions carry the data rule")

# ================================================================== the server
if os.environ.get("P2126B_NOSTART") != "1":
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})  # personal agents allowed
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "dora"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
BOB, CAROL, DORA = uid["bob"], uid["carol"], uid["dora"]
Bo, Ca = sess("bob"), sess("carol")


def hdr(token):
    return {"Authorization": "Bearer " + token, "X-Requested-With": "kalmido"}


def events(h, since=0):
    r = requests.get(V + "/agent/events", headers=h, params={"since": since, "limit": 500})
    assert r.ok, r.text
    return r.json()["data"]


def cursor(h):
    ev = events(h)
    return ev[-1]["seq"] if ev else 0


r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
CL, CLH = r.json()["id"], hdr(r.json()["token"])
A.patch(B + f"/api/admin/agents/{CL}", json={"org_id": ORG})
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
for m, role in ((CL, "edit"), (BOB, "edit"), (CAROL, "admin")):
    r = A.put(B + f"/api/lists/{W}/members", json={"user_id": m, "role": role})
    check(r.ok, f"setup: {m} in Work as {role} {r.text[:200]}")
W3 = A.post(B + "/api/lists", json={"name": "Elsewhere", "org_id": ORG}).json()["id"]
for m in (CL, BOB, CAROL, DORA):  # everyone of Work and one more person: a member may move there, an agent's move waits
    r = A.put(B + f"/api/lists/{W3}/members", json={"user_id": m, "role": "edit"})
    check(r.ok, f"setup: {m} in Elsewhere {r.text[:200]}")

# ================================================================== #1974 an approval job on a task
T = A.post(B + "/api/tasks", json={"title": "Prepare the offer", "list_id": W, "assignee_id": BOB}).json()["id"]
r = requests.patch(V + f"/tasks/{T}", headers=CLH, json={"list_id": W3})
check(r.status_code == 202 and (r.json().get("job") or {}).get("id"), f"#1974: the agent's move into a list with other people waits {r.status_code} {r.text[:200]}")
J = (r.json().get("job") or {}).get("id")
check(J and sql("SELECT task_id FROM agent_jobs WHERE id=?", (J,))[0][0] == T, "#1974: the job belongs to the task")
r = Bo.post(B + f"/api/agents/jobs/{J}/action", json={"action": "approve"})
check(r.status_code in (403, 404), f"#1974: the assignee alone cannot approve it ({r.status_code})")
check(sql("SELECT list_id FROM tasks WHERE id=?", (T,))[0][0] == W, "#1974: nothing moved")
r = A.post(B + f"/api/agents/jobs/{J}/action", json={"action": "approve"})
check(r.ok and r.json().get("state") == "done", f"#1974: the list owner approves {r.text[:200]}")
check(sql("SELECT list_id FROM tasks WHERE id=?", (T,))[0][0] == W3, "#1974: moved after the approval")

# ================================================================== #1975 integrate requests of a personal agent
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "display_name": "Bob's bot", "scopes": ["read", "tasks:write", "comments"]})
check(r.status_code in (200, 201), "setup: bob's personal agent " + r.text[:200])
PB = r.json().get("id")
PBH = hdr(Bo.post(B + f"/api/my/agents/{PB}/token").json().get("token", ""))
LB = Bo.post(B + "/api/lists", json={"name": "Bob's project", "org_id": ORG}).json()["id"]
for m, role in ((PB, "edit"), (CAROL, "admin")):
    check(Bo.put(B + f"/api/lists/{LB}/members", json={"user_id": m, "role": role}).ok, f"setup: {m} in bob's list as {role}")
TB = Bo.post(B + "/api/tasks", json={"title": "New login page", "list_id": LB}).json()["id"]
r = requests.post(V + f"/tasks/{TB}/comments", headers=PBH, json={"body": "Ready", "suggestion": {
    "kind": "integrate", "source": "feat/login", "target": "main", "summary": "New login page", "evidence": "build ok, tests green"}})
check(r.status_code == 201 and r.json()["suggestion"]["state"] == "open", "#1975: the personal agent asks to integrate " + r.text[:200])
IC = r.json().get("id")
r = Ca.post(B + f"/api/comments/{IC}/decide", json={"decision": "approve"})
check(r.status_code == 403, f"#1975: a list admin who may not address the agent cannot decide ({r.status_code})")
r = Ca.post(B + f"/api/comments/{IC}/reactions", json={"emoji": "up"})
check(r.ok and not r.json().get("approval") and r.json()["suggestion"]["state"] == "open", "#1975: their thumbs up is no approval " + r.text[:200])
r = Bo.post(B + f"/api/comments/{IC}/decide", json={"decision": "approve"})
check(r.ok and r.json().get("state") == "approved", "#1975: the agent's owner (list owner) decides " + r.text[:200])

# ================================================================== #1978 texts from outside, Playbook authors
TM = A.post(B + "/api/tasks", json={"title": "Request from a customer", "list_id": W}).json()["id"]
sql("UPDATE tasks SET tt_id=? WHERE id=?", ("mail:abc-1@example.com", TM), write=True)  # as made by the mail import
cur = cursor(CLH)
A.patch(B + f"/api/tasks/{TM}", json={"assignee_id": CL})
ev = [e for e in events(CLH, cur) if e["event"] == "assigned"]
tk = (ev[-1]["data"].get("task") or {}) if ev else {}
check(tk.get("origin") == "mail" and tk.get("untrusted") is True, f"#1978: a task from an e-mail is marked in the event {tk.get('origin')}")
TN = A.post(B + "/api/tasks", json={"title": "Normal task", "list_id": W}).json()["id"]
cur = cursor(CLH)
A.patch(B + f"/api/tasks/{TN}", json={"assignee_id": CL})
ev = [e for e in events(CLH, cur) if e["event"] == "assigned"]
check(ev and "untrusted" not in ev[-1]["data"]["task"] and "origin" not in ev[-1]["data"]["task"], "#1978: a normal task carries no mark")

check(A.put(B + f"/api/lists/{W}/playbook", json={"text": "Answer customers within a day."}).ok, "setup: the owner's Playbook in Work")
cur = cursor(CLH)
A.post(B + f"/api/tasks/{TN}/comments", json={"body": f"<@{CL}> please look"})
ev = [e for e in events(CLH, cur) if e["event"] in ("mention", "comment")]
pb = (ev[-1]["data"].get("playbook") or {}) if ev else {}
check(pb.get("text") == "Answer customers within a day." and pb.get("foreign") is False and [a.get("id") for a in pb.get("authors") or []] == [1],
      f"#1978: the team agent: the list owner's Playbook, with its author, not foreign {pb}")
check(Ca.put(B + f"/api/lists/{LB}/playbook", json={"text": "Deploy only on Mondays."}).ok, "setup: a list admin writes the Playbook of bob's list")
cur = cursor(PBH)
Bo.post(B + f"/api/tasks/{TB}/comments", json={"body": f"<@{PB}> go on"})
ev = [e for e in events(PBH, cur) if e["event"] in ("mention", "comment")]
pb = (ev[-1]["data"].get("playbook") or {}) if ev else {}
check(pb.get("foreign") is True and CAROL in [a.get("id") for a in pb.get("authors") or []] and pb["authors"][0].get("name"),
      f"#1978: bob's personal agent: a Playbook by someone else is foreign, names the author {pb}")

# ================================================================== #1979 G3, G5, I5
for bad in ("1:" + "\xfc" * 64, "\xb2:" + "a" * 64, "1:xyz", "abc"):
    r = requests.get(V + "/me", headers={"Authorization": "Bearer abk_" + "z" * 30, "X-Kalmido-Replay": bad})
    check(r.status_code == 401, f"G3: a replay header of the wrong shape: 401 ({r.status_code}) {bad[:4]!r}")
r = requests.post(V + f"/tasks/{TN}/comments", headers=CLH, json={"body": "Fixed.", "portal": True})
check(r.status_code == 400, f"G5: an answer to a customer on a task without a ticket: 400 (no waiting job) {r.status_code}")
codes = [requests.post(B + "/api/hooks/git/987654", data=b"{}", headers={"Content-Type": "application/json"}).status_code for _ in range(125)]
check(codes[0] == 404 and codes[-1] == 429 and codes.count(429) == 5, f"I5: the git hook answers 429 after 120 calls a minute {codes[:2]} {codes[-6:]}")

# ================================================================== a person without an organisation (freelancer-matrix: agents)
FU, F = freelancer(B, A, "frida")
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]})
check(r.status_code in (200, 201), "freelancer: an own agent " + r.text[:200])
FA = r.json().get("id")
FH = hdr(F.post(B + f"/api/my/agents/{FA}/token").json().get("token", ""))
FL = F.post(B + "/api/lists", json={"name": "Studio"}).json()["id"]
check(F.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "freelancer: the own agent in the own list")
FT = [F.post(B + "/api/tasks", json={"title": f"Shot {i}", "list_id": FL}).json()["id"] for i in range(10)]
r = requests.post(V + "/tasks/batch", headers=FH, json={"ids": FT, "action": "complete"})
check(r.status_code == 202, f"freelancer: the agent's batch of 10 waits {r.status_code}")
r = F.post(B + f"/api/agents/jobs/{(r.json().get('job') or {}).get('id')}/action", json={"action": "approve"})
check(r.ok and r.json().get("state") == "done", "freelancer: approves the own agent's batch " + r.text[:200])
r = requests.post(V + f"/tasks/{FT[0]}/comments", headers=FH, json={"body": "Ready", "suggestion": {
    "kind": "integrate", "source": "cut/v2", "target": "main", "summary": "Second cut", "evidence": "render ok"}})
FC = r.json().get("id")
r = F.post(B + f"/api/comments/{FC}/decide", json={"decision": "approve"})
check(r.ok and r.json().get("state") == "approved", "freelancer: decides the own agent's integrate request " + r.text[:200])
check(F.put(B + f"/api/lists/{FL}/playbook", json={"text": "Name files by date."}).ok, "freelancer: an own Playbook")
cur = cursor(FH)
F.post(B + f"/api/tasks/{FT[1]}/comments", json={"body": f"<@{FA}> sort these"})
ev = [e for e in events(FH, cur) if e["event"] in ("mention", "comment")]
pb = (ev[-1]["data"].get("playbook") or {}) if ev else {}
check(pb.get("foreign") is False and [a.get("id") for a in pb.get("authors") or []] == [FU], f"freelancer: the own Playbook is not foreign {pb}")
r = Bo.post(B + f"/api/comments/{FC}/decide", json={"decision": "reject"})
check(r.status_code in (403, 404), "freelancer: another person cannot decide")

print(f"p2126_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
