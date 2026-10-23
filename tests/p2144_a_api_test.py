#!/usr/bin/env python3
"""2.144.0 API tests, part A (#2412 stop a running agent answer), own container. Invented people only (example.com).
tenant-matrix: own
freelancer-matrix: agents
 - POST /api/agents/{id}/abort: the agent gets the event 'abort' {user, source: chat}; with job_id (a running job of that
   agent) also job_id + job; job_id of another agent / unknown 404, not a number 400, an ended job 409; a person who may not
   write the agent 404; an agent token 404 / 403
 - POST /api/v1/agent/aborted {seq?, job_id?}: without job_id the status goes back to idle (typing ends); with job_id the
   status stays; unknown field / foreign job 400; a person's token 403; the OpenAPI entry carries x-kalmido-scope
 - GET /api/v1/agent names the event 'abort'
 - a person without an organisation stops their own agent the same way
 - 2.144.0 A2: a body that is no JSON object 400 (both routes); the reference launcher (mcp/agent_run.py, no server) ends a
   running answer only for the person it is for or an operator, someone else's Stop is ignored (no confirmation)
usage: p2144_a_api_test.py <datadir>      (P2144A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import importlib.util
import os
import subprocess
import tempfile
import sys
import time

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


if os.environ.get("P2144A_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com", "orgs": []})
assert r.ok, r.text
Ca = sess("carol")
for s in (A, Ca):
    feats = set(((s.get(B + "/api/state").json().get("settings") or {}).get("features") or "").split(",")) - {""}
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": ",".join(sorted(feats | {"agents"}))}).ok
me = A.get(B + "/api/state").json()["me"]
ORG = me["workspaces"][0]["id"]


def agent(name):
    ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": name, "display_name": name.title()}).json()
    A.patch(B + f"/api/admin/agents/{ag['id']}", json={"org_id": ORG})
    lid = A.post(B + "/api/lists", json={"name": "Work " + name, "org_id": ORG}).json()["id"]
    assert A.put(B + f"/api/lists/{lid}/members", json={"user_id": ag["id"], "role": "edit"}).ok  # a shared list: Alice may write it
    return ag["id"], bearer(ag["token"])


def events(tok, since=0):
    r = tok.get(V + "/agent/events", params={"since": since})
    assert r.ok, r.text
    return r.json().get("data") or []


def last_abort(tok, since=0):
    evs = [e for e in events(tok, since) if e.get("event") == "abort"]
    return evs[-1] if evs else None


CL, T1 = agent("devbot")
OT, T2 = agent("otherbot")
check("abort" in (T1.get(V + "/agent").json().get("events") or []), "GET /agent names the event abort")

# ---------------------------------------------------------------- the app: Stop -> event 'abort'
r = A.post(B + f"/api/agents/{CL}/abort", json={})
check(r.ok and r.json().get("ok") and r.json().get("seq"), f"abort: {r.status_code} {r.text[:200]}")
SEQ = (r.json() or {}).get("seq")
ev = last_abort(T1)
d = (ev or {}).get("data") or {}
check(ev and (d.get("user") or {}).get("id") == me["id"] and d.get("source") == "chat" and "job_id" not in d,
      f"the agent gets abort {{user, source}}: {ev}")
check(ev and ev.get("seq") == SEQ, "the event's seq is the one the app got back")
check(last_abort(T2) is None, "another agent gets nothing")
check(Ca.post(B + f"/api/agents/{CL}/abort", json={}).status_code == 404, "a person who may not write the agent: 404")
check(requests.post(B + f"/api/agents/{CL}/abort", json={}, headers={"Authorization": T1.headers["Authorization"]}).status_code in (401, 403, 404),
      "an agent token on the app route: refused")

# a job of the agent: only its step
J = T1.post(V + "/agent/jobs", json={"title": "Knox: Release 2.144 stop", "user_id": me["id"], "state": "running"}).json()["id"]
JO = T2.post(V + "/agent/jobs", json={"title": "Other: job", "user_id": me["id"], "state": "running"}).json()["id"]
cur = max([e["seq"] for e in events(T1)] or [0])
r = A.post(B + f"/api/agents/{CL}/abort", json={"job_id": J})
check(r.ok, f"abort with job_id: {r.status_code} {r.text[:200]}")
ev = last_abort(T1, cur)
d = (ev or {}).get("data") or {}
check(d.get("job_id") == J and (d.get("job") or {}).get("id") == J, f"the event carries job_id + job: {d}")
jst = {j["id"]: j["state"] for j in A.get(B + "/api/agents/jobs?limit=50").json()["jobs"]}
check(jst.get(J) == "running", f"the job itself keeps running: {jst.get(J)}")
check(A.post(B + f"/api/agents/{CL}/abort", json={"job_id": JO}).status_code == 404, "job_id of another agent: 404")
check(A.post(B + f"/api/agents/{CL}/abort", json={"job_id": 999999}).status_code == 404, "unknown job: 404")
check(A.post(B + f"/api/agents/{CL}/abort", json={"job_id": "x"}).status_code == 400, "job_id not a number: 400")
check(A.post(B + f"/api/agents/{CL}/abort", json=[1]).status_code == 400, "A2: a body that is no JSON object: 400")
check(T1.post(V + "/agent/aborted", json=[1]).status_code == 400, "A2: aborted with a body that is no JSON object: 400")
T1.patch(V + f"/agent/jobs/{J}", json={"state": "done"})
check(A.post(B + f"/api/agents/{CL}/abort", json={"job_id": J}).status_code == 409, "an ended job: 409")

# ---------------------------------------------------------------- the agent confirms
check(T1.put(V + "/agent/status", json={"status": "working", "text": "Answering in the chat"}).ok, "status working")
check(T1.post(V + "/agent/typing", json={"chat_user_id": me["id"]}).ok, "typing")
r = T1.post(V + "/agent/aborted", json={"seq": SEQ, "job_id": JO})
check(r.status_code == 400, f"a job of another agent: 400 ({r.status_code})")
check(T1.post(V + "/agent/aborted", json={"why": "x"}).status_code == 400, "unknown field: 400")
check(T1.post(V + "/agent/aborted", json={"seq": "x"}).status_code == 400, "seq not a number: 400")
r = T1.post(V + "/agent/aborted", json={"seq": SEQ, "job_id": J})
check(r.ok and r.json().get("status") == "working", f"with job_id the status stays: {r.status_code} {r.text[:200]}")
r = T1.post(V + "/agent/aborted", json={"seq": SEQ})
check(r.ok and r.json().get("status") == "idle", f"confirmed: idle {r.status_code} {r.text[:200]}")
ag = next((a for a in A.get(B + "/api/agents").json().get("agents", []) if a["id"] == CL), {})
check(ag.get("status") == "idle" and not ag.get("status_text"), f"the person sees the agent idle: {ag.get('status')}")
check(not ag.get("typing") or ag.get("typing", 0) <= 0, f"the typing dots end: {ag.get('typing')}")
check(T1.post(V + "/agent/aborted", json={}).ok, "an empty confirmation is fine (nothing was running)")
tok = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "tasks:write"]}).json()["token"]
check(bearer(tok).post(V + "/agent/aborted", json={}).status_code == 403, "a person's token: 403")
spec = requests.get(V + "/openapi.json").json()
op = ((spec.get("paths") or {}).get("/agent/aborted") or {}).get("post") or {}
check(op.get("x-kalmido-scope"), f"OpenAPI: /agent/aborted with x-kalmido-scope ({op.get('x-kalmido-scope')})")

# ---------------------------------------------------------------- a person without an organisation
# freelancer-matrix: agents
FID, F = freelancer(B, A)
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})  # personal agents allowed
fa = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]})
check(fa.status_code in (200, 201), f"freelancer: an own agent {fa.status_code} {fa.text[:200]}")
FA = fa.json().get("id")
FT = bearer(F.post(B + f"/api/my/agents/{FA}/token").json().get("token", ""))
r = F.post(B + f"/api/agents/{FA}/abort", json={})
check(r.ok and r.json().get("seq"), f"freelancer: abort the own agent {r.status_code} {r.text[:200]}")
ev = last_abort(FT)
check(ev and ((ev.get("data") or {}).get("user") or {}).get("id") == FID, f"freelancer: the own agent gets abort: {ev}")
FT.put(V + "/agent/status", json={"status": "working", "text": "x"})
r = FT.post(V + "/agent/aborted", json={"seq": (ev or {}).get("seq")})
check(r.ok and r.json().get("status") == "idle", f"freelancer: the agent confirms {r.status_code} {r.text[:200]}")
check(F.post(B + f"/api/agents/{CL}/abort", json={}).status_code == 404, "freelancer: someone else's agent 404")

# ---------------------------------------------------------------- 2.144.0 A2: the reference launcher stops only that person's run
os.environ.setdefault("KALMIDO_URL", "http://127.0.0.1:9")
os.environ.setdefault("KALMIDO_TOKEN", "abk_" + "y" * 30)
os.environ.pop("KALMIDO_OWNER_IDS", None)
os.environ.pop("KALMIDO_PERM_USER", None)
spec = importlib.util.spec_from_file_location("agent_run", os.path.join(N, "..", "mcp", "agent_run.py"))
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)


class StubApi:
    def __init__(self):
        self.calls = []

    def soft(self, *a, **k):
        self.calls.append(a)
        return 200

    def status(self, *a, **k):
        self.calls.append(("status",) + a)


class Proc:
    def poll(self):
        return None


class St:
    aborted = False


killed = []
ar.kill_tree = lambda p: killed.append(p)
r = ar.Runner(["claude"], tempfile.mkdtemp(prefix="kalmido-p2144a-"))
r.api, r.agent = StubApi(), {"owner_id": 7}
ab = lambda uid, seq=5: {"event": "abort", "seq": seq, "data": {"user": {"id": uid}, "source": "chat"}}
r.proc, r.cur_st, r.cur_uid = Proc(), St(), 5
r.abort(ab(6))
check(not r.cur_st.aborted and not killed and not r.api.calls, "launcher: Stop by someone else for person 5's run: ignored, not confirmed")
r.abort(ab(5))
check(r.cur_st.aborted and len(killed) == 1 and r.abort_ev and r.abort_ev["seq"] == 5, "launcher: Stop by the person the run is for ends it")
r.proc, r.cur_st, r.cur_uid = Proc(), St(), None
r.abort(ab(6))
check(not r.cur_st.aborted and len(killed) == 1, "launcher: a task run is not stopped by someone who is no operator")
r.abort(ab(7))
check(r.cur_st.aborted and len(killed) == 2, "launcher: the agent's owner may stop any run")
r.proc = None
r.abort(ab(6, 9))
check(any(c[:2] == ("POST", "/agent/aborted") for c in r.api.calls), "launcher: nothing running: confirmed at once")

print(f"p2144_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
