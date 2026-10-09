#!/usr/bin/env python3
"""2.32.0 API tests (agent B: the agent chat), own container (start.sh).
 - #1079 the host reports what it really runs with: PUT /api/v1/agent/status {model, permission_mode, host_permission_mode}
   (validated, unknown fields still refused), stored with the agent (host in GET /api/agents and GET /api/v1/agent), the
   runtime's model next to it (runtime_model)
 - #1081 steps (prose between tool calls): POST /api/v1/agent/progress {text, chat_user_id | job_id}
   * PRIVACY: only the person of the chat run / the job sees them -- never another member of the same organisation, an
     admin, a person of another organisation, another agent (no token reads them back, no foreign job, no foreign chat)
   * the secret filter replaces API keys, tokens, Bearer values, private key blocks, passwords in URLs and long values
     after key / token / secret / password with [entfernt] BEFORE storing (checked in the database); one line, 500
     characters stored, 200 live
   * a chat run: the newest 3 live (newest first), the next chat answer keeps them (steps of that message), a permission
     question does not, a status idle ends a run without answer; /api/version sp moves only for that person
   * a job: only for a job that is for a person (409 else, 409 when ended), progress lines (append_log) are headings,
     GET /api/agents/jobs/{id}/steps (+ ?format=txt) only for that person, the job list counts them only for them; a chat
     message carries job_id (only a job for that person) and job_steps
   * validation (unknown fields, both / none of chat_user_id + job_id, no share, another agent, empty, too long) and the
     rate limit (429 + Retry-After)
 - settings agent_steps_live (default 1) / agent_steps_always (default 0), per person
usage: p2320_b_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys
import time

import requests

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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
# two organisations (instance mode workspaces, as in p2300_tenant_test): carol is only in the other one
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces"))
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en"})
# carol: only in another organisation
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
BETA = r.json().get("id") if r.ok else None
dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG, CAROL), write=True)
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (ORG, ALICE), write=True)
check(BETA is not None, "setup: organisation Beta for carol " + r.text[:100])


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": name, "display_name": name.title()})
    aid = r.json()["id"]
    check(A.patch(B + f"/api/admin/agents/{aid}", json={"org_id": ORG}).ok, "setup: a team agent of the organisation")
    dbx("INSERT OR IGNORE INTO org_members(org_id,user_id,role) VALUES(?,?,'member')", (ORG, aid), write=True)
    return aid, {"Authorization": "Bearer " + r.json()["token"]}


CL, CLH = agent("claude")
OT, OTH = agent("otto")  # a second agent of the same organisation
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
for who in (CL, BOB):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": "edit"}).ok, f"setup: {who} in the list")
W2 = A.post(B + "/api/lists", json={"name": "Other agent", "org_id": ORG}).json()["id"]  # one agent per list: otto works here
A.put(B + f"/api/lists/{W2}/members", json={"user_id": OT, "role": "edit"})
A.patch(B + f"/api/lists/{W}", json={"agent_members": True})  # bob may use the list's agents (he chats with claude too)
T = A.post(B + "/api/tasks", json={"title": "Shared task", "list_id": W}).json()["id"]
LB = Ca.post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json()["id"]


def prog(body, h=CLH):
    return requests.post(V + "/agent/progress", headers=h, json=body)


def chat(s, aid=CL):
    return s.get(B + f"/api/agents/{aid}/chat")


def say(to, body, h=CLH, **kw):
    r = requests.post(V + f"/agent/chats/{to}", headers=h, json={"body": body, **kw})
    return r


def sp(s):
    return s.get(B + "/api/version").json().get("sp")


check(chat(Bo).status_code == 200, "setup: bob chats with claude too (same organisation, list with agent_members)")
check(chat(Ca).status_code == 404, "setup: carol (other organisation) has no chat with claude")

# ================================================================== #1079 host info
r = requests.put(V + "/agent/status", headers=CLH, json={"status": "working", "text": "Answering", "model": "Opus 5.5",
                                                         "permission_mode": "auto", "host_permission_mode": "ask"})
check(r.ok and r.json().get("host", {}).get("model") == "Opus 5.5", "#1079: status with model / modes " + r.text[:160])
ag = {a["id"]: a for a in A.get(B + "/api/agents").json()["agents"]}[CL]
check(ag["host"]["model"] == "Opus 5.5" and ag["host"]["permission_mode"] == "auto" and ag["host"]["host_permission_mode"] == "ask" and ag["host"]["at"],
      "#1079: the person sees what the host runs with " + str(ag.get("host")))
check(ag.get("runtime_model") == "", "#1079: no runtime model set " + repr(ag.get("runtime_model")))
r = requests.put(V + "/agent/status", headers=CLH, json={"status": "working", "text": "Answering"})
ag = {a["id"]: a for a in A.get(B + "/api/agents").json()["agents"]}[CL]
check(ag["host"]["model"] == "Opus 5.5", "#1079: a status without the fields keeps them")
for bad in ({"permission_mode": "yolo"}, {"host_permission_mode": 1}, {"model": "<b>x</b>"}, {"model": "x" * 81}, {"modell": "x"}):
    r = requests.put(V + "/agent/status", headers=CLH, json={"status": "working", **bad})
    check(r.status_code == 400, "#1079: refused " + str(bad)[:60] + " " + str(r.status_code))
A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"model": "sonnet"}})
ag = {a["id"]: a for a in A.get(B + "/api/agents").json()["agents"]}[CL]
check(ag.get("runtime_model") == "sonnet", "#1079: the wished model next to the running one " + repr(ag.get("runtime_model")))
check(requests.get(V + "/agent", headers=CLH).json().get("host", {}).get("model") == "Opus 5.5", "#1079: GET /agent shows it too")

# ================================================================== #1081 chat steps + secret filter
sp_a0, sp_b0 = sp(A), sp(Bo)
r = prog({"text": "I read the failing test first", "chat_user_id": ALICE})
check(r.status_code == 201 and r.json()["text"] == "I read the failing test first" and r.json()["redacted"] is False, "#1081: a step " + r.text[:120])
SECRETS = {
    "anthropic": "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "github": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab",
    "aws": "AKIAIOSFODNN7EXAMPLE",
    "bearer": "Bearer abcDEF1234567890xyzABC",
    "url": "https://deploy:hunter2secretpw@git.example.com/repo.git",
    "kv": "API_KEY=9f8e7d6c5b4a39281706f5e4d3c2b1a0",
    "pw": "password: CorrectHorseBatteryStaple99",
    "pem": "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ\n-----END OPENSSH PRIVATE KEY-----",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
}
VALUES = {"anthropic": "AbCdEfGhIjKlMnOp", "github": "ABCDEFGHIJKLMNOP", "aws": "IOSFODNN7EXAMPLE", "bearer": "abcDEF1234567890",
          "url": "hunter2secretpw", "kv": "9f8e7d6c5b4a3928", "pw": "CorrectHorseBattery", "pem": "b3BlbnNzaC1rZXkt", "jwt": "dozjgNryP4J3jVmN"}
for k, sec in SECRETS.items():
    r = prog({"text": f"Found {sec} in the config, using it now", "chat_user_id": ALICE})
    t = r.json().get("text", "") if r.status_code == 201 else ""
    check(r.status_code == 201 and "[entfernt]" in t and VALUES[k] not in t and r.json()["redacted"] is True, f"#1081: secret filter {k}: " + t[:120])
    time.sleep(0.05)
raw = " ".join(x[0] for x in dbx("SELECT text FROM agent_steps"))
check(raw and not any(v in raw for v in VALUES.values()), "#1081: no secret ever reached the database")
r = prog({"text": "The build of commit abc1234 is green; next I tidy the tests in tests/p2320_b_api_test.py", "chat_user_id": ALICE})
check(r.json().get("redacted") is False and "abc1234" in r.json()["text"], "#1081: plain prose stays as it is " + r.text[:140])
# 2.32 review: German prose with long words and "Token" / "Auth..." stays readable; the filter is fast on the longest input
for t in ("Ich prüfe die Authentifizierung Benutzerverwaltungsmodul", "Keyboard-Layout Datenbankverbindungen prüfen",
          "Das Token funktioniert wieder"):
    r = prog({"text": t, "chat_user_id": ALICE})
    check(r.status_code == 201 and r.json().get("redacted") is False and r.json()["text"] == t, "#1081: prose stays: " + r.text[:120])
    time.sleep(0.05)
t0 = time.time()
r = prog({"text": "key" * 1333, "chat_user_id": ALICE})
check(r.status_code == 201 and time.time() - t0 < 2, f"#1081: the filter is fast on 4000 characters ({time.time() - t0:.2f} s)")
r = prog({"text": "line one\n\n   line two\tand three", "chat_user_id": ALICE})
check(r.json().get("text") == "line one line two and three", "#1081: one line " + repr(r.json().get("text")))
r = prog({"text": "Long " + "word " * 300, "chat_user_id": ALICE})
check(r.status_code == 201 and len(r.json()["text"]) == 500 and r.json()["text"].endswith("…"), "#1081: stored at most 500 characters " + str(len(r.json().get("text", ""))))
j = chat(A).json()
live = j.get("steps_live") or []
check(len(live) == 3 and live[0]["text"].startswith("Long") and len(live[0]["text"]) <= 200 and live[1]["text"] == "line one line two and three",
      "#1081: the newest 3 live, newest first, at most 200 characters " + str([(x["text"][:20], len(x["text"])) for x in live]))
check(sp(A) != sp_a0 and sp(Bo) == sp_b0, "#1081: /api/version sp moves for alice only " + str((sp_a0, sp(A), sp_b0, sp(Bo))))

# ---- privacy: nobody else reads alice's steps
jb = chat(Bo).json()
check(jb.get("steps_live") == [] and not any(m.get("steps") for m in jb["messages"]), "#1081 privacy: bob (same organisation) sees no live steps of alice's run")
check(chat(Ca).status_code == 404, "#1081 privacy: carol (other organisation) cannot open the conversation")
for h, who in ((CLH, "claude itself"), (OTH, "another agent")):
    r = requests.get(B + f"/api/agents/{CL}/chat", headers={**h, **H})
    check(r.status_code in (401, 403, 404) and "steps" not in r.text, f"#1081 privacy: {who} cannot read the person's chat " + str(r.status_code))
    r = requests.get(V + "/agent/chats?since=0", headers=h)
    check(r.ok and "failing test" not in r.text and "steps" not in r.text, f"#1081 privacy: {who}'s chat list carries no steps")
r = prog({"text": "otto writes into claude's run", "chat_user_id": ALICE}, OTH)
check(r.status_code == 201, "setup: otto's own run with alice " + r.text[:80])
live = chat(A).json()["steps_live"]
check(all("otto" not in x["text"] for x in live), "#1081 privacy: another agent's steps never show in claude's conversation")
check(any("otto" in x["text"] for x in chat(A, OT).json()["steps_live"]), "#1081: ... only in its own")
# validation
for bad, code in (({"text": "x", "chat_user_id": ALICE, "user": 1}, 400), ({"text": "x"}, 400), ({"text": "x", "chat_user_id": ALICE, "job_id": 1}, 400),
                  ({"text": "", "chat_user_id": ALICE}, 400), ({"text": "x" * 4001, "chat_user_id": ALICE}, 400), ({"text": 5, "chat_user_id": ALICE}, 400),
                  ({"text": "x", "chat_user_id": CAROL}, 404), ({"text": "x", "chat_user_id": OT}, 404), ({"text": "x", "chat_user_id": 99999}, 404),
                  ({"text": "x", "chat_user_id": True}, 400)):
    r = prog(bad)
    check(r.status_code == code, f"#1081: refused {str(bad)[:60]} -> {code}: {r.status_code}")
check(A.post(V + "/agent/progress", json={"text": "x", "chat_user_id": ALICE}).status_code in (401, 403), "#1081: a person cannot send steps")

# ---- the answer keeps them; a permission question does not
n_live = len(dbx("SELECT 1 FROM agent_steps WHERE agent_id=? AND user_id=? AND state='live'", (CL, ALICE)))
q = say(ALICE, "May I run the tests?", permission=True)
check(q.status_code == 201 and len(chat(A).json()["steps_live"]) == 3, "#1081: a permission question leaves the run's steps live")
m = say(ALICE, "Done: the test is fixed.")
check(m.status_code == 201, "setup: the answer " + m.text[:80])
j = chat(A).json()
mm = {x["id"]: x for x in j["messages"]}[m.json()["id"]]
check(j["steps_live"] == [] and len(mm.get("steps") or []) == n_live and mm["steps"][0]["text"] == "I read the failing test first",
      "#1081: the answer took the run's steps along, oldest first " + str(len(mm.get("steps") or [])) + "/" + str(n_live))
check("steps" not in {x["id"]: x for x in j["messages"]}[q.json()["id"]], "#1081: ... not the permission question")
check("steps" not in m.text, "#1081: the agent's own answer (v1) carries no steps")
jb = chat(Bo).json()
check(not any(x.get("steps") for x in jb["messages"]), "#1081 privacy: bob sees no steps")
# bob's own run: his steps, not alice's
prog({"text": "bob's run: I look at his list", "chat_user_id": BOB})
check([x["text"] for x in chat(Bo).json()["steps_live"]] == ["bob's run: I look at his list"] and chat(A).json()["steps_live"] == [],
      "#1081 privacy: each person sees only the steps of their own run")
# a run without an answer (a task event) ends with idle
requests.put(V + "/agent/status", headers=CLH, json={"status": "idle"})
check(chat(Bo).json()["steps_live"] == [], "#1081: status idle ends a run without an answer")
say(BOB, "Hello Bob")
check(not any(x.get("steps") for x in chat(Bo).json()["messages"]), "#1081: ... its steps do not stick to the next answer")

# ================================================================== #1081 job history
r = requests.post(V + "/agent/jobs", headers=CLH, json={"title": "Nobody's job", "task_id": T})
J0 = r.json()["id"]
check(prog({"text": "x", "job_id": J0}).status_code == 409, "#1081: a job for nobody takes no steps (409)")
r = requests.post(V + "/agent/jobs", headers=CLH, json={"title": "Release 2.32", "task_id": T, "user_id": ALICE, "log": "started"})
JA = r.json()["id"]
requests.patch(V + f"/agent/jobs/{JA}", headers=CLH, json={"append_log": "Build"})
for t in ("I compile the server", "Everything compiles; the key is AKIAIOSFODNN7EXAMPLE"):
    check(prog({"text": t, "job_id": JA}).status_code == 201, "#1081: a job step " + t[:30])
requests.patch(V + f"/agent/jobs/{JA}", headers=CLH, json={"append_log": "Tests"})
prog({"text": "The tests run on the runner", "job_id": JA})
r = A.get(B + f"/api/agents/jobs/{JA}/steps")
st = r.json().get("steps", []) if r.ok else []
check([(x["heading"], x["text"]) for x in st] == [(True, "started"), (True, "Build"), (False, "I compile the server"),
                                                  (False, "Everything compiles; the key is [entfernt]"), (True, "Tests"), (False, "The tests run on the runner")]
      and r.json()["total"] == 6, "#1081: the job's history, grouped by its progress lines " + str([(x["heading"], x["text"][:20]) for x in st]))
r = A.get(B + f"/api/agents/jobs/{JA}/steps?format=txt")
check(r.ok and "attachment" in r.headers.get("Content-Disposition", "") and "I compile the server" in r.text and "## " in r.text and "AKIA" not in r.text,
      "#1081: the whole history as a text file " + r.text[:80].replace("\n", " | "))
jl = {x["id"]: x for x in A.get(B + "/api/agents/jobs").json()["jobs"]}
check(jl[JA]["steps"] == 6 and jl[J0]["steps"] == 0, "#1081: the job list counts the history for alice " + str((jl[JA]["steps"], jl[J0]["steps"])))
# privacy of the job history: bob sees the job (shared task), carol and the agents nothing
jb = {x["id"]: x for x in Bo.get(B + "/api/agents/jobs").json()["jobs"]}
check(JA in jb and jb[JA]["steps"] == 0 and "compile" not in Bo.get(B + "/api/agents/jobs").text, "#1081 privacy: bob sees the job (title, log), no history " + str(jb.get(JA, {}).get("steps")))
check(Bo.get(B + f"/api/agents/jobs/{JA}/steps").status_code == 404 and Bo.get(B + f"/api/agents/jobs/{JA}/steps?format=txt").status_code == 404,
      "#1081 privacy: bob (same organisation, sees the task) cannot read the history")
check(Ca.get(B + f"/api/agents/jobs/{JA}/steps").status_code == 404, "#1081 privacy: carol (other organisation) cannot read it")
for h, who in ((CLH, "claude"), (OTH, "otto")):
    r = requests.get(B + f"/api/agents/jobs/{JA}/steps", headers={**h, **H})
    check(r.status_code in (401, 403, 404) and "compile" not in r.text, f"#1081 privacy: {who}'s token cannot read the history " + str(r.status_code))
check(prog({"text": "otto into claude's job", "job_id": JA}, OTH).status_code == 404, "#1081 privacy: another agent cannot write into the job")
r = requests.get(V + f"/agent/jobs/{JA}", headers=OTH)
check(r.status_code in (403, 404), "#1081 privacy: ... nor read it " + str(r.status_code))
# a job for bob: alice (instance admin) sees the job, never its history
r = requests.post(V + "/agent/jobs", headers=CLH, json={"title": "Bob's report", "task_id": T, "user_id": BOB})
JB = r.json()["id"]
prog({"text": "bob's job: I collect his numbers", "job_id": JB})
check(JB in {x["id"] for x in A.get(B + "/api/agents/jobs").json()["jobs"]}, "setup: alice (admin) sees bob's job")
check(A.get(B + f"/api/agents/jobs/{JB}/steps").status_code == 404 and {x["id"]: x for x in A.get(B + "/api/agents/jobs").json()["jobs"]}[JB]["steps"] == 0,
      "#1081 privacy: an admin of the same organisation cannot read another person's job history")
check(Bo.get(B + f"/api/agents/jobs/{JB}/steps").json().get("total") == 1, "#1081: bob reads his own job's history")
# the result in the chat: job_id
r = say(ALICE, "Release 2.32 is done.", job_id=JA)
check(r.status_code == 201 and r.json().get("job_id") == JA, "#1081: the result message carries its job " + r.text[:120])
mm = {x["id"]: x for x in chat(A).json()["messages"]}[r.json()["id"]]
check(mm.get("job_id") == JA and mm.get("job_steps") == 6, "#1081: alice's chat: job_id + the history size " + str((mm.get("job_id"), mm.get("job_steps"))))
check(say(ALICE, "wrong job", job_id=JB).status_code == 400, "#1081: only a job for that person (bob's job in alice's chat: 400)")
check(say(ALICE, "foreign job", job_id=99999).status_code == 400, "#1081: an unknown job: 400")
r = requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, data={"body": "as a form", "job_id": str(JA)})
check(r.status_code == 201 and r.json().get("job_id") == JA, "#1081: job_id in a multipart message too " + r.text[:100])
requests.patch(V + f"/agent/jobs/{JA}", headers=CLH, json={"state": "done"})
check(prog({"text": "too late", "job_id": JA}).status_code == 409, "#1081: an ended job takes no more steps")

# ================================================================== settings
st = A.get(B + "/api/state").json()["settings"]
check(st.get("agent_steps_live") == "1" and st.get("agent_steps_always") == "0", "#1081: defaults live on, always off " + str((st.get("agent_steps_live"), st.get("agent_steps_always"))))
r = A.patch(B + "/api/settings", json={"agent_steps_always": True, "agent_steps_live": "0"})
st = A.get(B + "/api/state").json()["settings"]
check(r.ok and st["agent_steps_always"] == "1" and st["agent_steps_live"] == "0", "#1081: stored per person " + r.text[:80])
check(Bo.get(B + "/api/state").json()["settings"]["agent_steps_always"] == "0", "#1081: bob keeps his own")
check(A.patch(B + "/api/settings", json={"agent_steps_always": "maybe"}).status_code == 400, "#1081: a bad value is refused")
A.patch(B + "/api/settings", json={"agent_steps_always": "0", "agent_steps_live": "1"})

# ================================================================== rate limit (last: it blocks otto for a minute)
codes = [prog({"text": f"step {i}", "chat_user_id": ALICE}, OTH) for i in range(70)]
lim = [r for r in codes if r.status_code == 429]
check(lim and lim[0].headers.get("Retry-After") and all(r.status_code == 201 for r in codes[:55]), "#1081: at most 60 steps a minute (429 + Retry-After) " + str(sorted({r.status_code for r in codes})))
check(dbx("SELECT COUNT(*) FROM agent_steps WHERE agent_id=? AND text LIKE 'step %'", (OT,))[0][0] <= 60, "#1081: refused steps are not stored")

print(f"p2320_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
