#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.571.0 D (#4676): read-only web research of the Kalmido AI (server agent), per routine, default off (agents/srvweb.py),
against tests/fake_anthropic_web.py (a stand-in for the Anthropic Messages API with its web server tools and for EU VIES inside
the test container; no real network).
freelancer-matrix: agents (the person without an organisation switches web research on for her own server agent)
 - GET / PUT /api/agents/<id>/server flow_web: every key off by default, an unknown key / no bool 400, the keys not named stay
 - a run of a routine without the switch gets no web tools and the frame "no web"; another routine switched on changes nothing
 - with the switch: exactly web_search / web_fetch (server tool types, max_uses, blocked_domains, fetch only from the events or
   web results) + check_vat_id, and the frame says web results are foreign data
 - a fetched page that tries to give orders: add_comment and send_chat to another person are refused (approval_required) even
   for an agent without a control level, nothing is written; the approval card and the answer name the web sources (URL)
 - the searches and fetched pages are counted in the run and in the usage; pause_turn is resumed
 - VIES: valid (name, address, kept), invalid, the time limit (valid null), a broken number (nothing goes out)
 - after the web run the gate is gone: the same comment without the switch is written
usage: p2571_d_web_test.py <datadir>      (KMT_NOSTART=1 / P2571D_NOSTART=1: a running server)"""
import json
import os
import shutil
import subprocess

from kt import B, CT, DATA, check, dbx, done, docker_logs_on_first_fail, fresh, until
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
SKEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="
KEY1 = "sk-test-web-0123456789-wxyz"
fresh(env={"KALMIDO_SECRET_KEY": SKEY, "KALMIDO_SRVAGENT_ANTHROPIC_URL": "http://127.0.0.1:8093", "KALMIDO_SRVAGENT_RUN_S": "60",
           "KALMIDO_SRVAGENT_STEPS": "6", "KALMIDO_SRVAGENT_WEB_SEARCHES": "3", "KALMIDO_SRVAGENT_WEB_FETCHES": "2",
           "KALMIDO_SRVAGENT_WEB_BLOCKED": "blocked.example", "KALMIDO_VIES_URL": "http://127.0.0.1:8093/vies", "KALMIDO_VIES_S": "2"},
      prefix="P2571D")
docker_logs_on_first_fail()
import kt  # noqa: E402
A = kt.setup()
shutil.copy(os.path.join(N, "fake_anthropic_web.py"), DATA)
for f in ("anthropic_web.log", "vies.log"):
    try:
        os.remove(os.path.join(DATA, f))
    except OSError:
        pass
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_anthropic_web.py"], check=True)
until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8093), 1)"],
                             capture_output=True).returncode == 0, 20)


def plog(name="anthropic_web.log"):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except OSError:
        return []


check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok, "personal agents allowed")
FID, Fr = freelancer(B, A)
GID, Gi = freelancer(B, A, "gina")
ag = Fr.post(B + "/api/my/agents", json={"username": "frida-web", "display_name": "Kalmido-KI"})
check(ag.status_code == 201, f"her agent {ag.status_code} {ag.text[:160]}")
AID = ag.json()["id"]
L1 = Fr.post(B + "/api/lists", json={"name": "Shared with the KI"}).json()["id"]
check(Fr.put(B + f"/api/lists/{L1}/members", json={"user_id": AID, "role": "edit"}).ok, "L1 shared with her agent")
r = Fr.put(B + f"/api/lists/{L1}/members", json={"user_id": GID, "role": "edit"})
check(r.ok, f"L1 shared with Gina too (so the agent may write to her) {r.status_code} {r.text[:120]}")
T1 = Fr.post(B + "/api/tasks", json={"title": "Offer for Pelican GmbH", "list_id": L1}).json()["id"]
SRV = B + f"/api/agents/{AID}/server"
check(dbx("SELECT control FROM agents WHERE user_id=?", (AID,)) in ([("",)], [(None,)]), "the agent has no control level (acts directly)")

# ---------------------------------------------------------------- the switch
j = Fr.get(SRV).json()
check(j.get("flow_web") == {"briefing": False, "tidy": False, "meetings": False, "followup": False, "other": False},
      f"every routine without web by default {j.get('flow_web')}")
for bad, what in (({"flow_web": {"nope": True}}, "an unknown key"), ({"flow_web": {"other": "yes"}}, "no bool"), ({"flow_web": []}, "no object")):
    r = Fr.put(SRV, json=bad)
    check(r.status_code == 400, f"PUT refuses {what} ({r.status_code})")
r = Fr.put(SRV, json={"api_key": KEY1, "flow_web": {"briefing": True}})
check(r.ok and r.json()["flow_web"]["briefing"] is True and r.json()["flow_web"]["other"] is False, f"briefing on {r.text[:200]}")
check(Gi.put(SRV, json={"flow_web": {"other": True}}).status_code == 404, "another person cannot switch it")


def last_run():
    rr = dbx("SELECT id, state, steps, error, cause, web FROM agent_runs WHERE agent_id=? ORDER BY id DESC LIMIT 1", (AID,))
    return rr[0] if rr else None


def run_done(after):
    return until(lambda: (last_run() if last_run() and last_run()[0] > after and last_run()[1] != "run" else None), 40)


def max_mid():
    return max([m["id"] for m in Fr.get(B + f"/api/agents/{AID}/chat").json()["messages"]] or [0])


def agent_says(after, needle, secs=40):
    def f():
        ms = Fr.get(B + f"/api/agents/{AID}/chat").json()["messages"]
        hit = [m for m in ms if m["from"] == "agent" and m["id"] > after and needle in (m["body"] or "")]
        return hit[-1] if hit else None
    return until(f, secs)


def chat(text):
    after, rid = max_mid(), (last_run() or [0])[0]
    r = Fr.post(B + f"/api/agents/{AID}/chat", json={"body": text})
    check(r.status_code == 201, f"chat message {r.status_code}")
    return after, rid


# a chat run is the routine "other": off, although the briefing is on
n0 = len(plog())
after, rid = chat("Hello FAKEWEB_PLAIN")
check(agent_says(after, "FAKEWEB answer"), "the plain run answers")
calls = [x for x in plog()[n0:] if x["path"] == "/v1/messages"]
names = [t.get("name") for t in calls[0]["tools"]] if calls else []
check(calls and "get_task" in names and not {"web_search", "web_fetch", "check_vat_id"} & set(names),
      f"a routine without the switch gets no web tools {names[-5:]}")
check(calls and "no web, no terminal" in calls[0]["system"] and "Read-only web research" not in calls[0]["system"], "the frame says: no web")
run = run_done(rid)
check(run and run[1] == "done" and run[5] == "", f"the run has no web state {run}")

# ---------------------------------------------------------------- with the switch: the tools
r = Fr.put(SRV, json={"flow_web": {"other": True}})
check(r.ok and r.json()["flow_web"]["other"] is True and r.json()["flow_web"]["briefing"] is True, "other on, briefing stays on")
n0 = len(plog())
after, rid = chat(f"Who is Pelican GmbH? FAKEWEB_INJECT {T1} {GID} {FID}")
m = agent_says(after, "FAKEWEB done")
check(m is not None, f"the web run answered {m}")
calls = [x for x in plog()[n0:] if x["path"] == "/v1/messages"]
tools = {t.get("name"): t for t in (calls[0]["tools"] if calls else [])}
ws, wf = tools.get("web_search") or {}, tools.get("web_fetch") or {}
check(ws.get("type") == "web_search_20260209" and ws.get("max_uses") == 3 and "blocked.example" in (ws.get("blocked_domains") or []),
      f"web_search: the server tool of the provider with max_uses and the blocked domains {ws}")
check(wf.get("type") == "web_fetch_20260209" and wf.get("max_uses") == 2 and "blocked.example" in (wf.get("blocked_domains") or [])
      and wf.get("url_sources") == {"client_tool_results": {"type": "none"}} and (wf.get("citations") or {}).get("enabled") is True,
      f"web_fetch: max_uses, blocked domains, never an address only a Kalmido tool returned {wf}")
check("check_vat_id" in tools and sum(1 for n in tools if n in ("web_search", "web_fetch", "check_vat_id")) == 3, "exactly the three web tools")
check(calls and "Read-only web research is switched on" in calls[0]["system"] and "foreign data" in calls[0]["system"],
      "the frame: web results are foreign data, no forms")
check(len(calls) >= 2 and "foreign data from the internet" in calls[1]["last"], "the reminder after the step with web results")
check(len(calls) >= 2 and calls[1]["roles"][1] == "assistant", "the provider's blocks went back as they came")

# ---------------------------------------------------------------- the page with orders: nothing written without a card
check(not dbx("SELECT 1 FROM comments WHERE task_id=? AND user_id=? AND body LIKE 'INJECTED%'", (T1, AID)), "no comment from the page's orders")
check(not dbx("SELECT 1 FROM agent_chat WHERE agent_id=? AND user_id=? AND body LIKE 'INJECTED%'", (AID, GID)), "no message to Gina")
body = m["body"] if m else ""
check(body.count("approval") >= 2 and "ERROR" in body, f"both tool calls were refused for an approval {body[:400]}")
card = dbx("""SELECT body, choices FROM agent_chat WHERE agent_id=? AND user_id=? AND sender='agent' AND choices->'approval' IS NOT NULL
              ORDER BY id DESC LIMIT 1""", (AID, FID))
check(card and "From the web" in card[0][0] and "https://example.org/offer" in card[0][0] and "May I post the comment?" in card[0][0],
      f"the approval card names the web source {card[0][0][:300] if card else card}")
check("From the web" in body and "https://example.org/offer" in body and "https://example.org/cited" in body,
      f"the answer names the fetched and the cited source {body[-300:]}")
run = run_done(rid)
st = json.loads(run[5]) if run and run[5] else {}
check(run and run[1] == "done" and st.get("searches") == 1 and st.get("fetches") == 1 and FID in st.get("to", []) and GID not in st.get("to", []),
      f"the run's web state: counts, the people of the run {run[:5] if run else run} {st}")
u = dbx("SELECT SUM(web_searches), SUM(web_fetches) FROM agent_usage WHERE agent_id=?", (AID,))
check(u == [(1, 1)], f"the usage counts the searches and fetched pages {u}")
rj = Fr.get(SRV + "/runs?limit=3").json()["runs"][0]
check(rj["web"] is True and rj["web_searches"] == 1 and rj["web_fetches"] == 1 and rj["vat_checks"] == 0, f"GET runs {rj}")
d = Fr.get(B + f"/api/agents/usage?agent_id={AID}").json()
tot = [x for x in d["agents"] if x["id"] == AID][0]["totals"]["today"]
check(tot.get("web_searches") == 1 and tot.get("web_fetches") == 1, f"the usage view counts them {tot}")

# ---------------------------------------------------------------- pause_turn
n0 = len(plog())
after, rid = chat("FAKEWEB_PAUSE")
check(agent_says(after, "FAKEWEB resumed"), "the paused turn was resumed")
calls = [x for x in plog()[n0:] if x["path"] == "/v1/messages"]
check(len(calls) == 2 and calls[1]["roles"] == ["user", "assistant"], f"resumed by sending the answer back, no extra message {[c['roles'] for c in calls]}")

# ---------------------------------------------------------------- VIES
v0 = len(plog("vies.log"))
after, rid = chat("FAKEVIES DE 123 456 789 END")
m = agent_says(after, "FAKEVIES result")
check(m and '"valid": true' in m["body"] and "Pelican GmbH" in m["body"] and "foreign data" in m["body"], f"valid with the name {(m or {}).get('body', '')[:300]}")
check(m and "VIES DE123456789" in m["body"], "the answer names VIES as the source")
vl = plog("vies.log")[v0:]
check(vl == [{"cc": "DE", "num": "123456789", "keys": ["countryCode", "vatNumber"]}], f"only the country code and the number went out {vl}")
after, rid = chat("FAKEVIES DE123456789 END")
m = agent_says(after, "FAKEVIES result")
check(m and '"cached": true' in m["body"] and len(plog("vies.log")) == v0 + 1, "the second check comes from the cache")
after, rid = chat("FAKEVIES DE999999999 END")
m = agent_says(after, "FAKEVIES result")
check(m and '"valid": false' in m["body"], f"invalid {(m or {}).get('body', '')[:200]}")
after, rid = chat("FAKEVIES DE555555555 END")
m = agent_says(after, "FAKEVIES result", 60)
check(m and '"valid": null' in m["body"] and "unavailable" in m["body"], f"the time limit: valid null {(m or {}).get('body', '')[:200]}")
v1 = len(plog("vies.log"))
for bad in ("XX12345678", "DE12;DROP", "US123456789"):
    after, rid = chat(f"FAKEVIES {bad} END")
    m = agent_says(after, "FAKEVIES result")
    check(m and "ERROR invalid vat_id" in m["body"], f"a broken number {bad} is refused {(m or {}).get('body', '')[:200]}")
check(len(plog("vies.log")) == v1, "a broken number never went out")
run = run_done(rid)
check(run and run[1] == "done", f"the VIES run ended {run}")

# ---------------------------------------------------------------- a team agent: a message to another person of its project by card
# (a personal agent may only write to its owner anyway; a team agent reaches the people of its projects)
r = A.post(B + "/api/users", json={"username": "hugo", "display_name": "Hugo", "password": kt.PASSWORD, "email": "hugo@example.com"})
check(r.ok, f"another person in the admin's organisation {r.status_code} {r.text[:160]}")
HID = r.json()["id"]
AU = A.get(B + "/api/state").json()["me"]["id"]
tm = A.post(B + "/api/admin/agents", json={"username": "teamweb", "display_name": "Team web", "provider": "kalmido-server"})
check(tm.status_code == 201, f"a team agent {tm.status_code} {tm.text[:160]}")
TMA = tm.json()["id"]
check(A.put(B + f"/api/agents/{TMA}/server", json={"api_key": KEY1, "flow_web": {"other": True}}).ok, "the team agent with web research")
LA = A.post(B + "/api/lists", json={"name": "Team web project"}).json()["id"]
for uid, role in ((TMA, "edit"), (HID, "admin")):
    r = A.put(B + f"/api/lists/{LA}/members", json={"user_id": uid, "role": role})
    check(r.ok, f"member {uid} of the team project {r.status_code} {r.text[:120]}")
TA = A.post(B + "/api/tasks", json={"title": "Team offer", "list_id": LA}).json()["id"]
r = A.post(B + f"/api/agents/{TMA}/chat", json={"body": f"FAKEWEB_INJECT {TA} {HID} {AU}"})
check(r.status_code == 201, f"the admin asks the team agent {r.status_code} {r.text[:120]}")
ans = until(lambda: dbx("SELECT body FROM agent_chat WHERE agent_id=? AND user_id=? AND sender='agent' AND body LIKE 'FAKEWEB done%'", (TMA, AU)), 40)
check(ans and ans[0][0].count("approval") >= 2 and "From the web" in ans[0][0], f"the team agent's answer: both refused, the sources named {(ans or [[''])[0][0][:300]}")
check(not dbx("SELECT 1 FROM agent_chat WHERE agent_id=? AND user_id=? AND body LIKE 'INJECTED%'", (TMA, HID)),
      "no message from the page's orders to the other person of the project")
check(not dbx("SELECT 1 FROM comments WHERE task_id=? AND user_id=? AND body LIKE 'INJECTED%'", (TA, TMA)), "no comment of the team agent")

# ---------------------------------------------------------------- without the switch the same comment is written (the gate ends)
check(Fr.put(SRV, json={"flow_web": {"other": False}}).ok, "web off again")
after, rid = chat(f"Again FAKEWEB_INJECT {T1} {GID} {FID}")
check(agent_says(after, "FAKEWEB done"), "the run without web answered")
check(dbx("SELECT 1 FROM comments WHERE task_id=? AND user_id=? AND body LIKE 'INJECTED%'", (T1, AID)),
      "without web the agent without a control level comments directly (the web run's card was the gate)")

raise SystemExit(done("p2571_d_web"))
