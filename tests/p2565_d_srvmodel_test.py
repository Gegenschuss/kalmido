#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.565.0 D (#4674): the Kalmido AI (server agent, #4670) runs a starter routine with a model of its own, against
tests/fake_anthropic.py (the provider stand-in inside the test container; it logs the model of every call).
freelancer-matrix: agents (the person without an organisation sets the models of her own server agent and sees the usage)
 - GET /api/agents/<id>/server: flow_models with every routine ('' = the agent's model); PUT flow_models: a model of the live
   list is kept, an unknown model (not in the list) -> 400, an unknown routine -> 400, '' = back to the agent's model; another
   person 404 (only who may set the agent up)
 - the starter pack marks its planned jobs with their routine (agent_schedules.srv_flow); a plan of an older pack is found by its
   title and rhythm, a plan of her own with the same title is none
 - "Run now" of the briefing plan: the provider is called with the briefing's model, a chat message with the agent's model
 - a briefing and a chat waiting together: two runs, each with its own model (one routine per run)
 - the usage per routine: agent_runs.flow, agent_usage.flow, GET …/server/runs flow, GET /api/agents/usage flows (also for the
   owner who is no instance admin), the chat header's flows (the usage ring's list)
usage: p2565_d_srvmodel_test.py <datadir>      (KMT_NOSTART=1 / P2565DS_NOSTART=1: a running server)"""
import json
import os
import shutil
import subprocess

from kt import B, CT, DATA, check, dbx, done, docker_logs_on_first_fail, fresh, until
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
SKEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (the provider key is sealed with it)
KEY1 = "sk-test-alpha-0123456789-wxyz"
fresh(env={"KALMIDO_SECRET_KEY": SKEY, "KALMIDO_SRVAGENT_ANTHROPIC_URL": "http://127.0.0.1:8091", "KALMIDO_SRVAGENT_RUN_S": "60",
           "KALMIDO_SRVAGENT_STEPS": "6"}, prefix="P2565DS")
docker_logs_on_first_fail()
import kt  # noqa: E402
A = kt.setup()
shutil.copy(os.path.join(N, "fake_anthropic.py"), DATA)
try:
    os.remove(os.path.join(DATA, "anthropic.log"))
except OSError:
    pass
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_anthropic.py"], check=True)
until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8091), 1)"],
                             capture_output=True).returncode == 0, 20)


def plog():
    try:
        with open(os.path.join(DATA, "anthropic.log"), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except OSError:
        return []


def calls_since(n0):
    return [x for x in plog()[n0:] if x["path"] == "/v1/messages"]


check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok, "personal agents allowed")
FID, Fr = freelancer(B, A)
GID, Gi = freelancer(B, A, "gina")  # another person
ag = Fr.post(B + "/api/my/agents", json={"username": "frida-kki", "display_name": "Kalmido-KI", "provider": "kalmido-server"})
check(ag.status_code == 201, f"her agent {ag.status_code} {ag.text[:160]}")
AID = ag.json()["id"]
L1 = Fr.post(B + "/api/lists", json={"name": "Shared with the KI"}).json()["id"]
check(Fr.put(B + f"/api/lists/{L1}/members", json={"user_id": AID, "role": "edit"}).ok, "L1 shared with her agent")
SRV = f"/api/agents/{AID}/server"

r = Fr.get(B + SRV)
check(r.ok and r.json().get("flow_models") == {"briefing": "", "tidy": "", "meetings": "", "followup": ""},
      f"GET: every routine with '' (the agent's model) {r.text[:300]}")
r = Fr.put(B + SRV, json={"flow_models": {"briefing": "claude-haiku-5-5"}})
check(r.status_code == 400, f"a routine model before a key is stored: 400 ({r.status_code} {r.text[:160]})")
r = Fr.put(B + SRV, json={"api_key": KEY1})
check(r.ok and r.json()["model"] == "claude-sonnet-5-5", f"the key stored, the agent's model is the default {r.text[:200]}")
st = Fr.post(B + f"/api/agents/{AID}/server/starter", json={"items": ["briefing", "followup"]})
check(st.ok and all(x["state"] == "created" for x in st.json()["items"]), f"starter pack: briefing + follow-up {st.text[:300]}")
plans = {x[1]: x[0] for x in dbx("SELECT id, srv_flow FROM agent_schedules WHERE agent_id=? AND user_id=?", (AID, FID))}
check(set(plans) == {"briefing", "followup"}, f"the planned jobs carry their routine {plans}")
d = Fr.get(B + "/api/agents/server/defaults").json()
check(d.get("flows") == ["briefing", "tidy", "meetings", "followup"], f"the defaults name the routines {d.get('flows')}")

# ---------------------------------------------------------------- PUT flow_models: rights and the live list
for bad, what in (({"briefing": "claude-unknown-1-0"}, "a model the provider does not list"), ({"nope": "claude-haiku-5-5"}, "an unknown routine"),
                  ({"docs": "claude-haiku-5-5"}, "docs (no routine of its own)"), ({"briefing": 5}, "not a text"), ("x", "not an object")):
    r = Fr.put(B + SRV, json={"flow_models": bad})
    check(r.status_code == 400, f"PUT flow_models refuses {what} ({r.status_code} {r.text[:120]})")
r = Gi.put(B + SRV, json={"flow_models": {"briefing": "claude-haiku-5-5"}})
check(r.status_code == 404, f"another person may not set it: 404 ({r.status_code})")
r = A.put(B + SRV, json={"flow_models": {"briefing": "claude-haiku-5-5"}})
check(r.status_code == 404, f"the instance admin may not set a personal agent of someone else: 404 ({r.status_code})")
check(dbx("SELECT flow_models FROM agent_server WHERE agent_id=?", (AID,)) == [("{}",)], "nothing stored by the refusals")
r = Fr.put(B + SRV, json={"flow_models": {"briefing": "claude-haiku-5-5", "followup": "claude-opus-5-5"}})
j = r.json()
check(r.ok and j["flow_models"] == {"briefing": "claude-haiku-5-5", "tidy": "", "meetings": "", "followup": "claude-opus-5-5"} and j["model"] == "claude-sonnet-5-5",
      f"the owner sets two routines from the live list, the agent's model stays {r.text[:300]}")
r = Fr.put(B + SRV, json={"instructions": "Be brief."})
check(r.ok and r.json()["flow_models"]["briefing"] == "claude-haiku-5-5", "a PUT without flow_models keeps them")


def runs():
    return dbx("SELECT id, state, cause, flow, model, tokens_in FROM agent_runs WHERE agent_id=? ORDER BY id", (AID,))


def done_runs(n):
    rr = runs()
    return rr if len(rr) >= n and all(x[1] != "run" for x in rr) else None


def max_mid():
    return max([m["id"] for m in Fr.get(B + f"/api/agents/{AID}/chat").json()["messages"]] or [0])


# ---------------------------------------------------------------- the briefing with its model, the chat with the agent's
n0 = len(plog())
r = Fr.post(B + f"/api/agent-schedules/{plans['briefing']}/run", json={})
check(r.ok, f"Run now: the briefing {r.status_code} {r.text[:160]}")
rr = until(lambda: done_runs(1), 40)
check(rr and rr[-1][1] == "done" and rr[-1][2] == "scheduled_job" and rr[-1][3] == "briefing" and rr[-1][4] == "claude-haiku-5-5",
      f"the briefing run: its routine and its model {rr}")
cs = calls_since(n0)
check(cs and all(x["model"] == "claude-haiku-5-5" for x in cs), f"the provider was called with the briefing's model {[x['model'] for x in cs]}")
n0 = len(plog())
r = Fr.post(B + f"/api/agents/{AID}/chat", json={"body": "Hello there"})
check(r.status_code == 201, f"a chat message {r.status_code}")
rr = until(lambda: done_runs(2), 40)
check(rr and rr[-1][2] == "chat" and rr[-1][3] == "" and rr[-1][4] == "claude-sonnet-5-5", f"the chat run: no routine, the agent's model {rr}")
cs = calls_since(n0)
check(cs and all(x["model"] == "claude-sonnet-5-5" for x in cs), f"the provider was called with the agent's model {[x['model'] for x in cs]}")

# ---------------------------------------------------------------- a routine and a chat waiting together: two runs
check(Fr.put(B + SRV, json={"delete_key": True}).ok, "the key deleted: nothing runs, the events wait")
r = Fr.post(B + f"/api/agent-schedules/{plans['followup']}/run", json={})
check(r.ok, f"Run now: the follow-up {r.status_code} {r.text[:160]}")
check(Fr.post(B + f"/api/agents/{AID}/chat", json={"body": "And a question"}).status_code == 201, "a chat message waits behind it")
n0, nr = len(plog()), len(runs())
check(Fr.put(B + SRV, json={"api_key": KEY1}).ok, "the key again")
check(Fr.post(B + f"/api/agents/{AID}/chat", json={"body": "Go on"}).status_code == 201, "one more chat message starts the runs")
rr = until(lambda: done_runs(nr + 2) if len(runs()) >= nr + 2 else None, 60)
new = (rr or [])[nr:]
check(len(new) >= 2 and new[0][3] == "followup" and new[0][4] == "claude-opus-5-5" and new[1][3] == "" and new[1][4] == "claude-sonnet-5-5",
      f"first the follow-up with its model, then the chats with the agent's model {new}")
cs = calls_since(n0)
fu = [x for x in cs if "scheduled_job" in x.get("first", "")]
ch = [x for x in cs if "And a question" in x.get("first", "")]
check(fu and all(x["model"] == "claude-opus-5-5" and "And a question" not in x["first"] for x in fu), f"the follow-up run saw only its routine {[x['model'] for x in fu]}")
check(ch and all(x["model"] == "claude-sonnet-5-5" for x in ch), f"the waiting chat ran with the agent's model {[x['model'] for x in ch]}")

# ---------------------------------------------------------------- a plan of an older starter pack (no srv_flow yet)
dbx("UPDATE agent_schedules SET srv_flow='', last_at=NULL WHERE id=?", (plans["briefing"],))
nr = len(runs())
check(Fr.post(B + f"/api/agent-schedules/{plans['briefing']}/run", json={}).ok, "Run now: the briefing of an older pack")
rr = until(lambda: done_runs(nr + 1), 40)
check(rr and rr[-1][3] == "briefing" and rr[-1][4] == "claude-haiku-5-5", f"an older pack's plan: found by its title and rhythm {(rr or [None])[-1]}")
own = Fr.post(B + f"/api/agents/{AID}/schedules", json={"title": "Morning briefing", "prompt": "Say hello", "freq": "daily", "time": "06:15", "enabled": True})
check(own.status_code in (200, 201), f"a plan of her own with the same title {own.status_code} {own.text[:160]}")
nr = len(runs())
check(Fr.post(B + f"/api/agent-schedules/{own.json()['id']}/run", json={}).ok, "Run now: her own plan")
rr = until(lambda: done_runs(nr + 1), 40)
check(rr and rr[-1][3] == "" and rr[-1][4] == "claude-sonnet-5-5", f"her own plan with that title is no routine: the agent's model {(rr or [None])[-1]}")

# ---------------------------------------------------------------- the usage per routine
u = dict(dbx("SELECT flow, SUM(input_tokens + output_tokens + cache_write_tokens) FROM agent_usage WHERE agent_id=? GROUP BY flow", (AID,)))
check(u.get("briefing", 0) > 0 and u.get("followup", 0) > 0 and u.get("", 0) > 0, f"agent_usage apart per routine {u}")
r = Fr.get(B + f"/api/agents/{AID}/server/runs?limit=10")
check(r.ok and {x["flow"] for x in r.json()["runs"]} >= {"briefing", "followup", ""}, f"GET runs names the routine {[x.get('flow') for x in r.json().get('runs', [])]}")
r = Fr.get(B + f"/api/agents/usage?agent_id={AID}")
fl = {x["flow"]: x["tokens"] for x in r.json().get("flows", [])} if r.ok else {}
check(fl.get("briefing") == u.get("briefing") and fl.get("followup") == u.get("followup") and "" not in fl,
      f"the usage dashboard per routine for the owner without organisation {fl} {r.text[:200]}")
check(sum(x["tokens"] for x in r.json().get("models", [])) == sum(u.values()), "the owner sees the reports without a project too")
r = Gi.get(B + f"/api/agents/usage?agent_id={AID}")
check(r.ok and not r.json().get("flows") and not any(a["id"] == AID for a in r.json().get("agents", [])), "another person sees nothing of it")
hd = Fr.get(B + f"/api/agents/{AID}/chat").json().get("agent", {})
hf = {x["flow"]: x for x in hd.get("flows") or []}
check(hf.get("briefing", {}).get("tokens") == u.get("briefing") and hf.get("briefing", {}).get("model") == "claude-haiku-5-5"
      and hf.get("followup", {}).get("model") == "claude-opus-5-5", f"the chat header (usage ring) lists the routines {hd.get('flows')}")

# ---------------------------------------------------------------- '' = back to the agent's model
r = Fr.put(B + SRV, json={"flow_models": {"briefing": ""}})
check(r.ok and r.json()["flow_models"]["briefing"] == "" and r.json()["flow_models"]["followup"] == "claude-opus-5-5", f"'' resets one routine {r.text[:200]}")
check(json.loads(dbx("SELECT flow_models FROM agent_server WHERE agent_id=?", (AID,))[0][0]) == {"followup": "claude-opus-5-5"}, "only the set routines are stored")

raise SystemExit(done("p2565_d_srvmodel"))
