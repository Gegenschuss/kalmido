#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.557.0 B (#4670): the server agent - Kalmido calls the model itself with the owner's key (agents/srvagent.py, srvagent_run.py),
against tests/fake_anthropic.py (a stand-in for the Anthropic Messages API inside the test container).
freelancer-matrix: agents (the person without an organisation sets up her own server agent: key, models, runs, chat, Stop)
tenant-matrix: agent (another person neither reads nor changes it; its tool calls see only what is shared with it)
 - GET / PUT /api/agents/<id>/server: defaults (model, instructions), a bad key / unknown field refused, the key stored sealed,
   never in an answer (only its last four characters), delete_key; only the owner (another person, the instance admin for a
   personal agent: 404), a team agent: the instance admin
 - models live from the provider: 409 no_key without a key, the default when offered, else the first Sonnet with a note
 - a chat message starts a run in the worker: the model calls get_task over the MCP tools, the answer lands in the chat, the
   tokens are in agent_runs and in the agent's usage; the provider gets the frame (data, not instructions) and no long poll tool
 - rights: a task of a project not shared with the agent comes back as an error from the tool, its title never reaches the model
 - a mention starts a run that comments through add_comment
 - Stop (POST /api/agents/<id>/abort) ends a slow run at once (state aborted, "Stopped." in the chat)
 - review 2.557.0: the run token keeps the owner's address rule; models 403 while switched off; Stop before the run started drops the request
 - the hard usage limit pauses the agent with its reason (no model call); after the limit is lifted the next event runs
 - the instance switch server_agents_off: PUT 403, no run
 - a key the provider refuses: the run fails with a neutral text, the key (repeated by the provider) is in no answer and no log
usage: p2557_b_srvagent_test.py <datadir>      (KMT_NOSTART=1 / P2557B_NOSTART=1: a running server)"""
import json
import os
import shutil
import subprocess
import time

from kt import B, CT, DATA, check, dbx, done, docker_logs_on_first_fail, fresh, until
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
SKEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (the provider key is sealed with it)
KEY1 = "sk-test-alpha-0123456789-wxyz"
KEY_BAD = "sk-wrong-9876543210-qrst"
KEY_ND = "sk-test-nodefault-55555-mnop"
fresh(env={"KALMIDO_SECRET_KEY": SKEY, "KALMIDO_SRVAGENT_ANTHROPIC_URL": "http://127.0.0.1:8091", "KALMIDO_SRVAGENT_RUN_S": "60",
           "KALMIDO_SRVAGENT_STEPS": "6"}, prefix="P2557B")
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

ANSWERS = []  # every answer text: the key must be in none


def call(s, method, path, **kw):
    r = getattr(s, method)(B + path, **kw)
    ANSWERS.append(r.text)
    return r


def plog():
    try:
        with open(os.path.join(DATA, "anthropic.log"), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except OSError:
        return []


check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok, "personal agents allowed")
FID, Fr = freelancer(B, A)
GID, Gi = freelancer(B, A, "gina")  # another person
ag = Fr.post(B + "/api/my/agents", json={"username": "frida-kki", "display_name": "Kalmido-KI"})
check(ag.status_code == 201, f"her agent {ag.status_code} {ag.text[:160]}")
AID = ag.json()["id"]
L1 = Fr.post(B + "/api/lists", json={"name": "Shared with the KI"}).json()["id"]
L2 = Fr.post(B + "/api/lists", json={"name": "Private only"}).json()["id"]
check(Fr.put(B + f"/api/lists/{L1}/members", json={"user_id": AID, "role": "edit"}).ok, "L1 shared with her agent")
T1 = Fr.post(B + "/api/tasks", json={"title": "Visible pelican task", "list_id": L1}).json()["id"]
T2 = Fr.post(B + "/api/tasks", json={"title": "Secret walrus task", "list_id": L2}).json()["id"]
SRV = f"/api/agents/{AID}/server"

# ---------------------------------------------------------------- settings
r = call(Fr, "get", f"/api/agents/{AID}/server")
j = r.json()
check(r.ok and j["has_key"] is False and j["key_hint"] == "" and j["default_model"] == "claude-sonnet-5-5" and j["model"] == "claude-sonnet-5-5"
      and len(j["default_instructions"]) > 50 and "Kalmido" in j["default_instructions"] and j["enabled_instance"] is True and j["server"] is False,
      f"GET before: defaults, no key {r.text[:300]}")
r = call(Fr, "get", f"/api/agents/{AID}/server/models")
check(r.status_code == 409 and r.json().get("error") == "no_key", f"models without a key: 409 no_key ({r.status_code})")
for bad, what in (({"api_key": "short"}, "too short"), ({"api_key": "sk-test with space"}, "a space"), ({"api_key": KEY1, "delete_key": True}, "key and delete"),
                  ({"nope": 1}, "unknown field"), ({"provider": "other"}, "unknown provider"), ({"model": "bad model!"}, "bad model name"),
                  ({"instructions": "x" * 20001}, "instructions too long")):
    r = call(Fr, "put", f"/api/agents/{AID}/server", json=bad)
    check(r.status_code == 400 and "sk-test" not in r.text, f"PUT refuses {what} ({r.status_code})")
r = call(Fr, "put", f"/api/agents/{AID}/server", json={"api_key": KEY1, "instructions": "Always sign with PELICAN-SIGN."})
j = r.json()
check(r.ok and j["has_key"] is True and j["key_hint"] == "…" + KEY1[-4:] and j["server"] is True and j["instructions"].startswith("Always sign"),
      f"PUT stores the key (hint only) {r.text[:300]}")
row = dbx("SELECT key_sealed, key_hint FROM agent_server WHERE agent_id=?", (AID,))
check(row and row[0][0].startswith("v1.") and KEY1 not in row[0][0] and row[0][1] == KEY1[-4:], "the key is sealed in the database")
check(dbx("SELECT provider, ai FROM agents WHERE user_id=?", (AID,)) == [("kalmido-server", 1)], "the agent is a server agent now")
r = call(Fr, "get", f"/api/agents/{AID}/server/models")
j = r.json()
check(r.ok and "claude-sonnet-5-5" in [m["id"] for m in j["models"]] and j["default"] == "claude-sonnet-5-5" and "fallback_note" not in j,
      f"models live from the provider, the default offered {r.text[:300]}")
check(any(x["path"].startswith("/v1/models") and x["key_ok"] and x["version_ok"] for x in plog()), "the provider got the key and the API version")
for s, who in ((Gi, "another person"), (A, "the instance admin (a personal agent of someone else)")):
    for m, p, kw in (("get", SRV, {}), ("put", SRV, {"json": {"model": "x"}}), ("get", f"/api/agents/{AID}/server/models", {}), ("get", f"/api/agents/{AID}/server/runs", {})):
        r = call(s, m, p, **kw)
        check(r.status_code == 404, f"{who}: {m} {p} 404 ({r.status_code})")
check(dbx("SELECT model FROM agent_server WHERE agent_id=?", (AID,)) == [("",)], "nothing changed by the others")
team = A.post(B + "/api/admin/agents", json={"username": "teamki", "display_name": "Team KI"})
TEAM = team.json().get("id")
r = call(A, "put", f"/api/agents/{TEAM}/server", json={"model": "claude-haiku-5-5"})
check(r.ok and r.json()["model"] == "claude-haiku-5-5" and r.json()["has_key"] is False, f"team agent: the instance admin sets it up {r.text[:200]}")
check(call(Gi, "get", f"/api/agents/{TEAM}/server").status_code == 404, "team agent: a person who is no admin 404")


def last_run():
    rr = dbx("SELECT id, state, steps, tokens_in, tokens_out, error, trigger FROM agent_runs WHERE agent_id=? ORDER BY id DESC LIMIT 1", (AID,))
    return rr[0] if rr else None


def max_mid():
    ms = Fr.get(B + f"/api/agents/{AID}/chat").json()["messages"]
    return max([m["id"] for m in ms] or [0])


def agent_says(after, needle, secs=40):
    def f():
        ms = Fr.get(B + f"/api/agents/{AID}/chat").json()["messages"]
        hit = [m for m in ms if m["from"] == "agent" and m["id"] > after and needle in (m["body"] or "")]
        return hit[-1] if hit else None
    return until(f, secs)


def chat(text):
    after = max_mid()
    r = call(Fr, "post", f"/api/agents/{AID}/chat", json={"body": text})
    check(r.status_code == 201, f"chat message {r.status_code}")
    return after, r.json().get("id")


# ---------------------------------------------------------------- a chat run with a tool call
n0 = len(plog())
after, _ = chat(f"Please look at task FAKE_GET_TASK {T1}")
m = agent_says(after, "FAKE result")
check(m and "Visible pelican task" in m["body"], f"the answer with the tool result is in the chat {(m or {}).get('body', '')[:200]}")
run = until(lambda: (last_run() if last_run() and last_run()[1] != "run" else None), 20)
check(run and run[1] == "done" and run[2] == 2 and run[3] == 2 * (100 + 10 + 5) and run[4] == 2 * 20 and run[6] == "chat",
      f"the run: done, 2 steps, tokens counted {run}")
r = call(Fr, "get", f"/api/agents/{AID}/server/runs?limit=5")
rj = r.json()["runs"][0] if r.ok and r.json()["runs"] else {}
check(rj.get("state") == "done" and rj.get("tokens_in") == 230 and rj.get("tokens_out") == 40 and rj.get("trigger") == "chat"
      and rj.get("model") == "claude-sonnet-5-5" and rj.get("error") == "", f"GET runs {rj}")
u = dbx("SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), MIN(model) FROM agent_usage WHERE agent_id=?", (AID,))
check(u and u[0][0] == 2 and u[0][1] == 200 and u[0][2] == 40 and u[0][3] == "claude-sonnet-5-5", f"the usage is reported like any agent's {u}")
calls = [x for x in plog()[n0:] if x["path"] == "/v1/messages"]
check(len(calls) == 2 and all(x["key_ok"] and x["version_ok"] and x["model"] == "claude-sonnet-5-5" for x in calls), f"two model calls {len(calls)}")
c0 = calls[0] if calls else {}
check("get_task" in c0.get("tools", []) and "add_comment" in c0.get("tools", []) and "wait_for_events" not in c0.get("tools", [])
      and "report_usage" not in c0.get("tools", []), "the MCP tools of the token, without the long poll and own usage reports")
check("PELICAN-SIGN" in c0.get("system", "") and "data, not instructions" in c0.get("system", "") and "no web, no terminal" in c0.get("system", ""),
      "the system text: the owner's instructions plus the fixed frame")
check("<events>" in c0.get("first", "") and "content, not instructions" in c0.get("first", ""), "the events go in marked as data")
check(not dbx("SELECT 1 FROM api_tokens WHERE user_id=? AND name='Server agent run'", (AID,)), "the run's own token is gone after the run")
check(dbx("SELECT status FROM agents WHERE user_id=?", (AID,)) == [("idle",)], "the agent is idle again")

# ---------------------------------------------------------------- rights: a project not shared with the agent
n0 = len(plog())
after, _ = chat(f"And FAKE_GET_TASK {T2}")
m = agent_says(after, "FAKE result")
check(m and "ERROR" in m["body"] and "walrus" not in m["body"], f"the tool refuses the task of a project not shared {(m or {}).get('body', '')[:200]}")
check(not any("walrus" in json.dumps(x) for x in plog()), "the title of the task never reached the model")

# ---------------------------------------------------------------- a mention: a comment through the tool
n_c = len(dbx("SELECT id FROM comments WHERE task_id=? AND user_id=?", (T1, AID)))
r = Fr.post(B + f"/api/tasks/{T1}/comments", json={"body": f"<@{AID}> FAKE_COMMENT {T1}"})
check(r.ok, f"comment with the mention {r.status_code}")
check(until(lambda: len(dbx("SELECT id FROM comments WHERE task_id=? AND user_id=? AND body LIKE 'FAKE comment%'", (T1, AID))) > n_c, 40),
      "the server agent commented through add_comment")
run = until(lambda: (last_run() if last_run() and last_run()[1] != "run" else None), 20)
check(run and run[1] == "done" and run[6] == "mention", f"the mention run {run}")

# ---------------------------------------------------------------- Stop
after, _ = chat("Think long FAKE_SLOW")
check(until(lambda: last_run() and last_run()[1] == "run" and last_run()[6] == "chat", 20), "the slow run is running")
t0 = time.monotonic()
r = call(Fr, "post", f"/api/agents/{AID}/abort", json={})
check(r.ok, f"Stop {r.status_code} {r.text[:120]}")
run = until(lambda: (last_run() if last_run() and last_run()[1] != "run" else None), 15)
check(run and run[1] == "aborted" and time.monotonic() - t0 < 12, f"Stop ends the run at once {run} ({time.monotonic() - t0:.1f} s)")
check(agent_says(after, "Stopped.", 10), "the chat says it stopped")

# ---------------------------------------------------------------- the usage limit pauses
r = call(Fr, "patch", f"/api/my/agents/{AID}", json={"limits": {"period": "day", "metric": "tokens", "hard": 5000}})
check(r.ok, f"the owner sets a hard limit {r.status_code} {r.text[:160]}")
rid0 = (last_run() or [0])[0]
chat("Heavy FAKE_HEAVY")
run = until(lambda: (last_run() if last_run() and last_run()[0] > rid0 and last_run()[1] != "run" else None), 30)
check(run and run[1] == "done" and run[3] > 400000, f"the heavy run counted its tokens {run}")
n0 = len(plog())
rid0 = run[0] if run else rid0
chat("Anything else?")
run = until(lambda: (last_run() if last_run() and last_run()[0] > rid0 and last_run()[1] != "run" else None), 30)
check(run and run[1] == "paused" and run[2] == 0 and "usage limit" in (run[5] or ""), f"over the limit: paused, no model call {run}")
st = dbx("SELECT status, status_text FROM agents WHERE user_id=?", (AID,))
check(st and st[0][0] == "paused" and "usage limit" in st[0][1].lower(), f"the agent shows the pause with its reason {st}")
check(not [x for x in plog()[n0:] if x["path"] == "/v1/messages"], "no model call while paused")
check(call(Fr, "patch", f"/api/my/agents/{AID}", json={"limits": None}).ok, "the owner lifts the limit")
rid0 = run[0] if run else rid0
after, _ = chat("Back again")
check(agent_says(after, "FAKE answer"), "after the limit the next event runs and answers")
check(until(lambda: dbx("SELECT status FROM agents WHERE user_id=?", (AID,)) == [("idle",)], 15), "the pause ended by itself")

# ---------------------------------------------------------------- review 2.557.0: the owner's address rule stays on the run token
r = call(Fr, "patch", f"/api/my/agents/{AID}", json={"allowed_ips": "10.9.9.9"})
check(r.ok, f"the owner restricts the agent to one address {r.status_code} {r.text[:160]}")
after, _ = chat("From the server FAKE_SLOW")
check(until(lambda: last_run() and last_run()[1] == "run", 20), "the run under the address rule is running")
ips = until(lambda: dbx("SELECT allowed_ips FROM api_tokens WHERE user_id=? AND name='Server agent run'", (AID,)), 10)
check(ips and ips[0][0] in ("10.9.9.9", "10.9.9.9/32"), f"the run token keeps the owner's address rule {ips}")
check(call(Fr, "post", f"/api/agents/{AID}/abort", json={}).ok, "Stop the slow run")
run = until(lambda: (last_run() if last_run() and last_run()[1] != "run" else None), 15)
check(run and run[1] == "aborted", f"the run itself passed the rule from the server (else its events call fails) {run}")
check(call(Fr, "patch", f"/api/my/agents/{AID}", json={"allowed_ips": ""}).ok, "the address rule lifted")

# ---------------------------------------------------------------- the instance switch
dbx("INSERT INTO settings(key, value) VALUES('server_agents_off', '1') ON CONFLICT(key) DO UPDATE SET value='1'")
r = call(Fr, "put", f"/api/agents/{AID}/server", json={"model": "claude-haiku-5-5"})
check(r.status_code == 403 and r.json().get("error") == "server_agents_off", f"switch on: PUT 403 server_agents_off ({r.status_code})")
check(call(Fr, "get", f"/api/agents/{AID}/server").json()["enabled_instance"] is False, "GET says the kind is off")
rid0 = (last_run() or [0])[0]
bg0 = (dbx("SELECT COALESCE(MAX(id), 0) FROM bg_jobs WHERE kind='srvagent:run'") or [(0,)])[0][0]
chat("While off")
check(until(lambda: dbx("SELECT 1 FROM bg_jobs WHERE kind='srvagent:run' AND id>? AND state IN ('done', 'failed')", (bg0,)), 20),
      "the queue row ran")
check((last_run() or [0])[0] == rid0, "but no run while the switch is on")
r = call(Fr, "get", f"/api/agents/{AID}/server/models")  # review 2.557.0: no provider call with the key while off
check(r.status_code == 403 and r.json().get("error") == "server_agents_off", f"switch on: models 403 ({r.status_code})")
chat("Queued walrus FAKE_QUEUED")  # review 2.557.0: Stop before the run took its place - it is not done afterwards
check(call(Fr, "post", f"/api/agents/{AID}/abort", json={}).ok, "Stop while the request waits")
dbx("DELETE FROM settings WHERE key='server_agents_off'")
n0 = len(plog())
after, _ = chat("After the switch")
check(agent_says(after, "FAKE answer"), "the next request runs")
check(not any("FAKE_QUEUED" in json.dumps(x) for x in plog()[n0:]), "the stopped request never reached the model")

# ---------------------------------------------------------------- a key the provider refuses
r = call(Fr, "put", f"/api/agents/{AID}/server", json={"api_key": KEY_BAD})
check(r.ok and r.json()["key_hint"] == "…" + KEY_BAD[-4:] and KEY_BAD not in r.text, "the key replaced")
after, _ = chat("With the wrong key")
m = agent_says(after, "could not finish")
check(m and "refused the key" in m["body"] and KEY_BAD not in m["body"], f"the chat says it neutrally {(m or {}).get('body', '')[:200]}")
run = until(lambda: (last_run() if last_run() and last_run()[1] != "run" else None), 20)
check(run and run[1] == "failed" and run[5] == "The provider refused the key", f"the run failed with a neutral text {run}")
check(call(Fr, "get", f"/api/agents/{AID}/server/models").status_code == 502, "models with a refused key: 502")

# ---------------------------------------------------------------- the fallback when the default is not offered
check(call(Fr, "put", f"/api/agents/{AID}/server", json={"api_key": KEY_ND}).ok, "a key without the default model")
j = call(Fr, "get", f"/api/agents/{AID}/server/models").json()
check(j.get("default") == "claude-sonnet-9-0" and "claude-sonnet-5-5" in (j.get("fallback_note") or ""), f"the first Sonnet with a note {j}")

# ---------------------------------------------------------------- delete the key; the key in no answer, no log
r = call(Fr, "put", f"/api/agents/{AID}/server", json={"delete_key": True})
check(r.ok and r.json()["has_key"] is False and r.json()["key_hint"] == "", "delete_key")
check(dbx("SELECT key_sealed FROM agent_server WHERE agent_id=?", (AID,)) == [("",)], "the sealed key is gone")
check(not any(k in t for t in ANSWERS for k in (KEY1, KEY_BAD, KEY_ND)), "no answer ever carried a key")
logs = subprocess.run(["docker", "logs", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
check(not any(k in logs for k in (KEY1, KEY_BAD, KEY_ND)), "no key in the server log")
check(not any(k in json.dumps(dbx("SELECT * FROM agent_runs")) for k in (KEY1, KEY_BAD, KEY_ND)), "no key in the runs")

raise SystemExit(done("p2557_b_srvagent"))
