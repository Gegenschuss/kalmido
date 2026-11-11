#!/usr/bin/env python3
"""2.233.0 B (#3189): the agent's runtime section "Interim summary" -- when the host ends a chat conversation with a summary.
 - runtime rotate_size (small / medium / large), rotate_runs (10-500), rotate_idle_min (0 = never, 5-1440); defaults = the
   hosts' former fixed values (medium = 0.8 MB / 150000 tokens, 60 runs, 45 minutes); GET /api/v1/agent always fills in
   rotate_mb / rotate_tokens / rotate_idle_mb; the daily summary is the existing nightly_reset (no second field)
 - out of range / wrong type: 400, nothing changes; only the given keys change
 - a team agent: the instance admin saves it, a member gets 403; event runtime_changed carries the values
 - a personal agent: its owner saves it (PATCH /api/my/agents/<id>), another person does not find it
 - a person without an organisation with an own agent (freelancer-matrix: agents)
 - 2.481.0 (#3662): runtime dispatch ("" / dry / on), the switch of the starter's mechanical dispatcher
 - 2.974.0 (#5668): runtime model_split / model_decide / model_routine (the model per run), admin, owner, freelancer; the chat
   header's set model is empty while it is on (only the model of the last run shows)
 - the client file is in the agent bundle and the service worker list (static)
usage: p2233_b_runtime_rotate_test.py <datadir>      (KMT_NOSTART=1 / P2233B_NOSTART=1: a running server)"""
import os
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, done, fresh, sess, setup

N = os.path.dirname(os.path.abspath(__file__))
V = B + "/api/v1"
DEF = {"rotate_size": "medium", "rotate_runs": 60, "rotate_idle_min": 45, "rotate_mb": 0.8, "rotate_tokens": 150000, "rotate_idle_mb": 0.4}

# ---------------------------------------------------------------- static: the client file loads with the agent bundle
ST = os.path.join(N, "..", "static")
check("'agentrotate'" in open(os.path.join(ST, "js", "lazyload.js"), encoding="utf-8").read(), "agentrotate.js is in the agent bundle")
check("/static/js/agentrotate.js" in open(os.path.join(ST, "sw.js"), encoding="utf-8").read(), "agentrotate.js is in the service worker list")


def rot(rt):
    return {k: rt.get(k) for k in DEF}


def events(h, since):
    return requests.get(V + f"/agent/events?since={since}", headers=h).json()["data"]


# ---------------------------------------------------------------- server
fresh(prefix="P2233B")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
check(r.ok, "a member " + r.text[:100])
Bo = sess("bob")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}

# defaults = the former fixed values of the hosts, always filled in
rt = requests.get(V + "/agent", headers=CLH).json()["runtime"]
check(rot(rt) == DEF and rt["nightly_reset"] == "", f"defaults in GET /api/v1/agent: {rt}")
adm = next(a for a in A.get(B + "/api/admin/agents").json()["agents"] if a["id"] == CL)
check(rot(adm["runtime"]) == DEF, "the admin list carries them for the dialog")

# the admin saves; only the given keys change; the event tells the agent
cur = requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]
r = A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"rotate_size": "large", "rotate_runs": 120}})
check(r.ok and rot(r.json()["runtime"]) == {**DEF, "rotate_size": "large", "rotate_runs": 120, "rotate_mb": 1.5, "rotate_tokens": 250000},
      f"admin saves size + runs: {r.status_code} {r.text[:200]}")
ev = [e for e in events(CLH, cur) if e["event"] == "runtime_changed"]
check(len(ev) == 1 and ev[0]["data"]["runtime"]["rotate_size"] == "large" and ev[0]["data"]["runtime"]["rotate_runs"] == 120
      and ev[0]["data"]["runtime"]["rotate_mb"] == 1.5 and ev[0]["data"]["runtime"]["rotate_tokens"] == 250000, f"runtime_changed carries them: {ev}")
r = A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"rotate_idle_min": 0, "nightly_reset": "04:30"}})
rt = requests.get(V + "/agent", headers=CLH).json()["runtime"]
check(r.ok and rt["rotate_idle_min"] == 0 and rt["rotate_size"] == "large" and rt["nightly_reset"] == "04:30", f"pause off, daily summary time: {rt}")
check(A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"rotate_size": "small"}}).ok
      and requests.get(V + "/agent", headers=CLH).json()["runtime"]["rotate_mb"] == 0.4, "small = 0.4 MB")
for bad, what in (({"rotate_size": "huge"}, "unknown size"), ({"rotate_size": None}, "size null"), ({"rotate_runs": 9}, "runs < 10"),
                  ({"rotate_runs": 501}, "runs > 500"), ({"rotate_runs": "60"}, "runs as text"), ({"rotate_runs": True}, "runs bool"),
                  ({"rotate_runs": 60.5}, "runs float"), ({"rotate_idle_min": 4}, "pause 1-4"), ({"rotate_idle_min": 1441}, "pause > 1440"),
                  ({"rotate_idle_min": -1}, "pause negative"), ({"rotate_mb": 3}, "the derived value is read-only")):
    check(A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": bad}).status_code == 400, f"400: {what}")
rt = requests.get(V + "/agent", headers=CLH).json()["runtime"]
check(rt["rotate_size"] == "small" and rt["rotate_runs"] == 120 and rt["rotate_idle_min"] == 0, f"a refused change changed nothing: {rt}")
check(Bo.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"rotate_runs": 10}}).status_code == 403, "a member: 403")
check(requests.patch(V + "/agent", headers=CLH, json={"runtime": {"rotate_runs": 10}}).status_code in (403, 404, 405), "the agent cannot change it itself")
# 2.481.0 (#3662): the switch of the starter's dispatcher ("" off, dry, on), default off; anything else 400
check(requests.get(V + "/agent", headers=CLH).json()["runtime"]["dispatch"] == "", "dispatcher off by default")
r = A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"dispatch": "dry"}})
check(r.ok and requests.get(V + "/agent", headers=CLH).json()["runtime"]["dispatch"] == "dry", "the admin switches the dry run on " + r.text[:120])
for bad in ("yes", True, 1, "ON"):
    check(A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"dispatch": bad}}).status_code == 400, f"dispatch {bad!r}: 400")
check(A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"dispatch": None}}).ok
      and requests.get(V + "/agent", headers=CLH).json()["runtime"]["dispatch"] == "", "null = off")
check("function agd_html" in open(os.path.join(ST, "js", "agentrotate.js"), encoding="utf-8").read(), "the switch is in the runtime section")
# 2.974.0 (#5668): the model per run - off by default, both fields empty; the admin switches it on with two models
rt = requests.get(V + "/agent", headers=CLH).json()["runtime"]
check(rt["model_split"] is False and rt["model_decide"] == "" and rt["model_routine"] == "", f"#5668: off by default: {rt}")
A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"model": "sonnet"}})
cur = requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]
r = A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"model_split": True, "model_decide": " opus ", "model_routine": "claude-haiku-5-5"}})
rt = requests.get(V + "/agent", headers=CLH).json()["runtime"]
check(r.ok and rt["model_split"] is True and rt["model_decide"] == "opus" and rt["model_routine"] == "claude-haiku-5-5" and rt["model"] == "sonnet",
      f"#5668: the admin sets the model per run: {r.status_code} {rt}")
ev = [e for e in events(CLH, cur) if e["event"] == "runtime_changed"]
check(len(ev) == 1 and ev[0]["data"]["runtime"]["model_split"] is True and ev[0]["data"]["runtime"]["model_routine"] == "claude-haiku-5-5",
      f"#5668: runtime_changed carries it: {ev}")
hdr = next(a for a in A.get(B + "/api/agents").json()["agents"] if a["id"] == CL)
check(hdr.get("runtime_model") == "", f"#5668: the chat header has no single set model while it is on: {hdr.get('runtime_model')!r}")
for bad, what in (({"model_split": "yes"}, "split as text"), ({"model_split": 1}, "split as number"), ({"model_decide": "a b"}, "space in a model"),
                  ({"model_routine": "x" * 101}, "model too long"), ({"model_routine": 5}, "model as number"), ({"model_decide": "-opus"}, "leading dash")):
    check(A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": bad}).status_code == 400, f"#5668: 400: {what}")
rt = requests.get(V + "/agent", headers=CLH).json()["runtime"]
check(rt["model_decide"] == "opus" and rt["model_split"] is True, f"#5668: a refused change changed nothing: {rt}")
check(Bo.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"model_split": False}}).status_code == 403, "#5668: a member: 403")
r = A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"model_split": False, "model_decide": None}})
rt = requests.get(V + "/agent", headers=CLH).json()["runtime"]
check(r.ok and rt["model_split"] is False and rt["model_decide"] == "" and rt["model_routine"] == "claude-haiku-5-5", f"#5668: off again, null = empty: {rt}")
hdr = next(a for a in A.get(B + "/api/agents").json()["agents"] if a["id"] == CL)
check(hdr.get("runtime_model") == "sonnet", f"#5668: off = the header compares with the one model again: {hdr.get('runtime_model')!r}")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "robo", "runtime": {"rotate_idle_min": 90}})
check(r.ok and rot(r.json()["runtime"])["rotate_idle_min"] == 90, "created with an interim-summary value " + r.text[:120])

# ---------------------------------------------------------------- a personal agent of a person without an organisation
A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2})
FID, F = freelancer(B, A)  # freelancer-matrix: agents
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot"})
check(r.ok, "the freelancer's own agent " + r.text[:100])
FB, FBH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
mine = next(a for a in F.get(B + "/api/my/agents").json()["agents"] if a["id"] == FB)
check(rot(mine["runtime"]) == DEF, "GET /api/my/agents carries the defaults for the permissions dialog")
r = F.patch(B + f"/api/my/agents/{FB}", json={"runtime": {"rotate_size": "large", "rotate_idle_min": 30, "rotate_runs": 10}})
check(r.ok and rot(r.json()["runtime"])["rotate_size"] == "large", "the owner saves it " + r.text[:120])
rt = requests.get(V + "/agent", headers=FBH).json()["runtime"]
check(rt["rotate_size"] == "large" and rt["rotate_idle_min"] == 30 and rt["rotate_runs"] == 10 and rt["rotate_tokens"] == 250000,
      f"the freelancer's agent reads them: {rt}")
check(F.patch(B + f"/api/my/agents/{FB}", json={"runtime": {"rotate_runs": 1000}}).status_code == 400, "owner: out of range 400")
# 2.481.0 (#3662): a person without an organisation switches the dispatcher of the own agent on
check(F.patch(B + f"/api/my/agents/{FB}", json={"runtime": {"dispatch": "on"}}).ok
      and requests.get(V + "/agent", headers=FBH).json()["runtime"]["dispatch"] == "on", "the freelancer switches the own dispatcher on")
# 2.974.0 (#5668): a person without an organisation sets the model per run of the own agent
r = F.patch(B + f"/api/my/agents/{FB}", json={"runtime": {"model_split": True, "model_decide": "opus", "model_routine": "sonnet"}})
rt = requests.get(V + "/agent", headers=FBH).json()["runtime"]
check(r.ok and rt["model_split"] is True and rt["model_decide"] == "opus" and rt["model_routine"] == "sonnet", f"#5668: the freelancer sets it: {rt}")
check(F.patch(B + f"/api/my/agents/{FB}", json={"runtime": {"model_split": "on"}}).status_code == 400, "#5668: owner: wrong type 400")
check("function agm_html" in open(os.path.join(ST, "js", "agentrotate.js"), encoding="utf-8").read(), "#5668: the owner's dialog has the model section")
_, G = freelancer(B, A, name="gero")
check(G.patch(B + f"/api/my/agents/{FB}", json={"runtime": {"rotate_runs": 20}}).status_code in (403, 404), "another person: not theirs")
check(G.patch(B + f"/api/my/agents/{FB}", json={"runtime": {"model_split": False}}).status_code in (403, 404), "#5668: another person: not theirs")
check(Bo.patch(B + f"/api/my/agents/{FB}", json={"runtime": {"rotate_runs": 20}}).status_code in (403, 404), "a member: not theirs")
check(requests.get(V + "/agent", headers=FBH).json()["runtime"]["rotate_runs"] == 10, "... nothing changed")
sys.exit(done("p2233_b_runtime_rotate"))
