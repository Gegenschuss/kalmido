#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.569.0 B (#4675): the Kalmido AI (server agent) in team projects (kalmido/agents/srvteam.py), against tests/fake_anthropic.py.
freelancer-matrix: agents (the person without an organisation: her personal server agent in a project she shares with another
  person takes orders only from her; she has no team agent and no limit per member)
tenant-matrix: agent (another organisation's admin neither creates in, reads nor addresses the team agent, sees no proposal)
 - an organisation's admin (no instance admin) creates a team agent on the server and stores the key; a member, another
   organisation's admin and a person without an organisation cannot (404)
 - "Members may see and use the agent" off: a member's mention reaches the team agent not at all, the chat reaches it not
   (2.777.0: Kalmido's fixed answer instead of a refusal); the
   project's owner gives it orders
 - switched on: a member's mention starts a run that works for that member (agent_runs.asked_by, agent_usage.asked_by)
 - a limit per member (PUT /api/agents/<id>/server/team): only the admin; the member over it gets a clear answer and no model
   call, the next member's request in the same queue still runs; the agent itself does not pause
 - the circle limit: sharing the team agent into a project with other people is refused (409 agent_bridge)
 - a proposal of the team agent in the team project: a member with write rights sees it (GET, the project's list, Waiting for me)
   and applies it; a read-only member, another organisation and a person without one see nothing (404)
 - a personal server agent in a shared project (listening in): the other person's new task never starts a run (no queue row),
   its owner's does; the other person cannot chat with it
usage: p2569_b_srvteam_test.py <datadir>      (KMT_NOSTART=1 / P2569B_NOSTART=1: a running server)"""
import json
import os
import shutil
import subprocess

from kt import B, CT, DATA, check, dbx, done, docker_logs_on_first_fail, fresh, sess, until
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
SKEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (the provider key is sealed with it)
KEY_ORG = "sk-test-orgkey-0123456789-oooo"
KEY_FR = "sk-test-frida-0123456789-ffff"
fresh(env={"KALMIDO_SECRET_KEY": SKEY, "KALMIDO_SRVAGENT_ANTHROPIC_URL": "http://127.0.0.1:8091", "KALMIDO_SRVAGENT_RUN_S": "60",
           "KALMIDO_SRVAGENT_STEPS": "6"}, prefix="P2569B")
docker_logs_on_first_fail()
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


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok, "personal agents allowed")
uid = {}
for u, rk in (("bob", "admin"), ("carl", "member"), ("dora", "member"), ("rita", "member"), ("eve", "member")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rk}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as {rk} " + r.text[:200])
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
r = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]})
check(r.ok, "setup: another organisation with olga as its admin " + r.text[:200])
ORG2 = r.json().get("id")
S = {u: sess(u) for u in ("bob", "carl", "dora", "rita", "eve", "olga")}
Bo, Ca, Do, Ri, Ev, Ol = (S[u] for u in ("bob", "carl", "dora", "rita", "eve", "olga"))
for s in S.values():
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "comments,collab"})
FID, Fr = freelancer(B, A)
GID, Gi = freelancer(B, A, "gina")

# ---------------------------------------------------------------- the organisation's admin creates the team agent
for s, who in ((Ca, "a member"), (Ol, "another organisation's admin"), (Fr, "a person without an organisation")):
    r = s.post(B + f"/api/orgs/{ORG}/server-agents", json={"username": "nope" + who[:3].strip(), "display_name": "Nope"})
    check(r.status_code == 404, f"{who} creates no team agent in the organisation ({r.status_code})")
r = Bo.post(B + f"/api/orgs/{ORG}/server-agents", json={"username": "teamki", "display_name": "Team KI"})
check(r.status_code == 201 and r.json().get("org_id") == ORG and r.json().get("provider") == "kalmido-server", f"bob (organisation admin) creates it {r.status_code} {r.text[:200]}")
TK = r.json().get("id")
check(dbx("SELECT owner_id, org_id, provider FROM agents WHERE user_id=?", (TK,)) == [(None, ORG, "kalmido-server")], "a team agent of the organisation")
r = Bo.put(B + f"/api/agents/{TK}/server", json={"api_key": KEY_ORG})
check(r.ok and r.json()["has_key"] is True and KEY_ORG not in r.text, f"bob stores the organisation's key {r.status_code} {r.text[:160]}")
for s, who in ((Ca, "a member"), (Ol, "another organisation"), (Fr, "a person without an organisation")):
    check(s.get(B + f"/api/agents/{TK}/server").status_code == 404, f"{who}: its server settings 404")
    check(s.get(B + f"/api/agents/{TK}/server/team").status_code == 404, f"{who}: its member limits 404")

P = Bo.post(B + "/api/lists", json={"name": "Team project", "org_id": ORG}).json()["id"]
for u, role in (("carl", "edit"), ("dora", "edit"), ("rita", "view")):
    check(Bo.put(B + f"/api/lists/{P}/members", json={"user_id": uid[u], "role": role}).ok, f"setup: {u} in the project ({role})")
check(Bo.put(B + f"/api/lists/{P}/members", json={"user_id": TK, "role": "edit"}).ok, "the team agent joins the project")
T1 = Bo.post(B + "/api/tasks", json={"title": "Team pelican task", "list_id": P}).json()["id"]
T2 = Bo.post(B + "/api/tasks", json={"title": "Team heron task", "list_id": P}).json()["id"]


def runs(aid=TK):
    return dbx("SELECT id, state, cause, asked_by, error, steps FROM agent_runs WHERE agent_id=? ORDER BY id", (aid,))


def agent_comments(tid, aid=TK):
    # 2.972.0 (#5272): the task comments are rows of the core's obj_comments (kind 'task', ref_id = the task)
    return dbx("SELECT id FROM obj_comments WHERE kind='task' AND ref_id=? AND user_id=? AND body LIKE 'FAKE comment%'", (tid, aid))


def settled(n):
    """The runs once n of them ended."""
    def f():
        rr = runs()
        return rr if len(rr) >= n and all(x[1] != "run" for x in rr) else None
    return until(f, 40)


# ---------------------------------------------------------------- "Members may see and use the agent" off
n_ev = dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=?", (TK,))[0][0]
check(Ca.post(B + f"/api/tasks/{T1}/comments", json={"body": f"<@{TK}> CARL-NORIGHT FAKE_COMMENT {T1}"}).ok, "carl mentions the agent")
check(dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=? AND payload LIKE '%CARL-NORIGHT%'", (TK,))[0][0] == 0,
      "switch off: a member's mention reaches the team agent not at all")
# 2.777.0 (#5378): a member of the team agent's organisation may write to it without a project opened to him - Kalmido answers
# with a fixed text, nothing reaches the agent (was: refused)
r = Ca.post(B + f"/api/agents/{TK}/chat", json={"body": "Hello CARL-CHAT"})
check(r.status_code == 201 and dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=? AND payload LIKE '%CARL-CHAT%'", (TK,))[0][0] == 0,
      f"switch off: the member's chat never reaches the agent, Kalmido answers ({r.status_code})")
check(Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": f"<@{TK}> FAKE_COMMENT {T1}"}).ok, "the owner mentions it")
check(until(lambda: agent_comments(T1), 40), "the owner's order: the agent commented")
rr = settled(1)
check(rr and len(rr) == 1 and rr[0][1] == "done" and rr[0][3] == uid["bob"], f"one run, for bob {rr}")
check(not any("CARL-CHAT" in json.dumps(x) for x in plog()), "carl's chat never reached the model (his comment on the task is data of the task)")
check(dbx("SELECT COUNT(*), MIN(asked_by), MAX(asked_by) FROM agent_usage WHERE agent_id=?", (TK,)) == [(2, uid["bob"], uid["bob"])],
      "its usage counts for bob")

# ---------------------------------------------------------------- switched on: members give orders, counted per member
check(Bo.patch(B + f"/api/lists/{P}", json={"agent_members": True}).ok, "bob opens the agent to the members")
check(Ca.post(B + f"/api/tasks/{T2}/comments", json={"body": f"<@{TK}> FAKE_COMMENT {T2}"}).ok, "carl mentions it")
check(until(lambda: agent_comments(T2), 40), "carl's order: the agent commented")
rr = settled(2)
check(rr and rr[-1][1] == "done" and rr[-1][3] == uid["carl"], f"the run works for carl {rr}")
use = dict(dbx("SELECT asked_by, SUM(input_tokens + output_tokens + cache_write_tokens) FROM agent_usage WHERE agent_id=? GROUP BY asked_by", (TK,)))
check(use.get(uid["carl"]) == 250 and use.get(uid["bob"]) == 250, f"usage per member {use}")

# ---------------------------------------------------------------- a limit per member
for s, who in ((Ca, "a member"), (Ol, "another organisation")):
    check(s.put(B + f"/api/agents/{TK}/server/team", json={"member_limit": {"period": "day", "hard": 200}}).status_code == 404,
          f"{who} sets no limit (404)")
for bad in ({"member_limit": {"period": "week", "hard": 200}}, {"member_limit": {"period": "day", "metric": "cost", "hard": 2}},
            {"member_limit": {"period": "day"}}, {"nope": 1}):
    check(Bo.put(B + f"/api/agents/{TK}/server/team", json=bad).status_code == 400, f"a bad limit refused {bad}")
r = Bo.put(B + f"/api/agents/{TK}/server/team", json={"member_limit": {"period": "day", "hard": 200}})
j = r.json()
check(r.ok and j["member_limit"]["hard"] == 200 and j["member_limit"]["period"] == "day"
      and {m["id"]: m["reached"] for m in j["members"]} == {uid["bob"]: True, uid["carl"]: True}, f"bob sets 200 tokens a day per member {r.text[:300]}")
check(Bo.put(B + f"/api/agents/{TK}/server/team", json={"member_limit": {"period": "day", "hard": 400}}).ok, "and raises it to 400 (bob, carl: 250)")
n_msgs = len(plog())
n_runs = len(runs())
T3 = Bo.post(B + "/api/tasks", json={"title": "Team stork task", "list_id": P}).json()["id"]
check(Ca.post(B + f"/api/tasks/{T1}/comments", json={"body": f"<@{TK}> CARL-ONE FAKE_COMMENT {T1}"}).ok, "carl asks again (250 -> 500)")
check(until(lambda: len(agent_comments(T1)) >= 2, 40), "carl's second order still ran (under the limit before it)")
settled(n_runs + 1)
check(Ca.post(B + f"/api/tasks/{T1}/comments", json={"body": f"<@{TK}> CARL-OVER FAKE_COMMENT {T1}"}).ok, "carl over his limit asks")
check(Do.post(B + f"/api/tasks/{T3}/comments", json={"body": f"<@{TK}> FAKE_COMMENT {T3}"}).ok, "dora asks right after him")
check(until(lambda: agent_comments(T3), 40), "dora's order runs although carl is over his limit")
rr = settled(n_runs + 3)
mine = [x for x in (rr or [])[n_runs:]]
check(len(mine) == 3 and mine[1][1] == "failed" and mine[1][3] == uid["carl"] and mine[1][5] == 0 and "usage limit" in mine[1][4]
      and mine[2][1] == "done" and mine[2][3] == uid["dora"], f"carl's run refused without a model call, dora's done {mine}")
check(len(agent_comments(T1)) == 2, "no comment for carl's request over the limit")
check(not any("CARL-OVER" in (x.get("first") or "") for x in plog()[n_msgs:]), "carl's request over the limit never reached the model")
ms = Ca.get(B + f"/api/agents/{TK}/chat").json().get("messages") or []
check(any(m["from"] == "agent" and "usage limit for this agent is reached" in (m["body"] or "") for m in ms),
      f"carl reads why in his chat {[m.get('body') for m in ms][-3:]}")
check(dbx("SELECT status FROM agents WHERE user_id=?", (TK,)) == [("idle",)], "the agent itself does not pause")
check(Bo.put(B + f"/api/agents/{TK}/server/team", json={"member_limit": None}).json()["member_limit"] is None, "bob lifts the limit")

# ---------------------------------------------------------------- the circle limit (agents/safety.py) holds unchanged
P2 = Bo.post(B + "/api/lists", json={"name": "Bob and Eve", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{P2}/members", json={"user_id": uid["eve"], "role": "edit"}).ok, "setup: a project of bob and eve")
r = Bo.put(B + f"/api/lists/{P2}/members", json={"user_id": TK, "role": "edit"})
check(r.status_code == 409 and r.json().get("code") == "agent_bridge", f"the team agent bridges no circles (409 agent_bridge) {r.status_code}")
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (P2, TK)), "it did not join")

# ---------------------------------------------------------------- a proposal in the team project
n_runs = len(runs())
r = Ca.post(B + "/api/proposals", json={"agent_id": TK, "kind": "subtasks", "task_id": T2})
check(r.status_code in (200, 201), f"carl asks the agent for subtasks {r.status_code} {r.text[:200]}")
JID = r.json().get("job", r.json()).get("id")
settled(n_runs + 1)  # the job_request run of the server agent
r = A.post(B + f"/api/admin/agents/{TK}/token", json={})
check(r.ok, f"a token of the agent for the stand-in proposal {r.status_code}")
TOK = {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"}
import requests  # noqa: E402
r = requests.post(B + f"/api/v1/agent/jobs/{JID}/proposal", headers=TOK, json={"kind": "subtasks", "items": [{"title": "Sharpen the pencils"}]}, timeout=30)
check(r.ok, f"the agent's proposal {r.status_code} {r.text[:200]}")
for s, who in ((Do, "dora (write rights)"), (Ca, "carl (who asked)")):
    r = s.get(B + f"/api/proposals/{JID}")
    check(r.ok and r.json()["proposal"]["items"][0]["title"] == "Sharpen the pencils", f"{who} sees it {r.status_code}")
check(any(p["id"] == JID for p in Do.get(B + f"/api/lists/{P}/agent-proposals").json().get("proposals", [])), "the project's list names it for dora")
check(any(x["kind"] == "job" and x["id"] == JID for x in Do.get(B + "/api/inbox").json().get("items", [])), "Waiting for me lists it for dora")
for s, who in ((Ri, "rita (read only)"), (Ol, "another organisation"), (Fr, "a person without an organisation"), (Ev, "eve (not in the project)")):
    check(s.get(B + f"/api/proposals/{JID}").status_code == 404, f"{who}: the proposal 404")
    check(s.get(B + f"/api/lists/{P}/agent-proposals").status_code == 404, f"{who}: the project's proposals 404")
    check(not any(x["kind"] == "job" and x["id"] == JID for x in s.get(B + "/api/inbox").json().get("items", [])), f"{who}: not waiting")
    check(s.post(B + f"/api/proposals/{JID}/discard", json={}).status_code == 404, f"{who}: no discard")
# 2.569.0 (#4675 review): only the one who asked discards another's proposal - dora sees and applies, never throws it away
check(Do.post(B + f"/api/proposals/{JID}/discard", json={}).status_code == 404, "dora (write rights, not who asked): no discard")
r = Do.post(B + f"/api/proposals/{JID}/apply", json={"select": ["0"]})
check(r.ok and r.json().get("created") == 1, f"dora applies it {r.status_code} {r.text[:200]}")
check(dbx("SELECT COUNT(*) FROM tasks WHERE parent_id=? AND title='Sharpen the pencils' AND deleted_at IS NULL", (T2,)) == [(1,)], "the subtask is there")
check(Ri.post(B + f"/api/proposals/{JID}/undo", json={}).status_code == 404, "rita cannot undo it")
check(Do.post(B + f"/api/proposals/{JID}/undo", json={}).ok, "dora (who applied it) undoes it")

# ---------------------------------------------------------------- a personal server agent in a shared project (freelancer)
FAG = Fr.post(B + "/api/my/agents", json={"username": "frida-ki", "display_name": "Frida KI"}).json()["id"]
check(Fr.put(B + f"/api/agents/{FAG}/server", json={"api_key": KEY_FR}).ok, "frida sets up her personal server agent")
check(Fr.get(B + f"/api/agents/{FAG}/server/team").status_code == 400, "a personal agent has no limits per member")
check(Fr.put(B + f"/api/agents/{FAG}/server/team", json={"member_limit": {"period": "day", "hard": 10}}).status_code == 400, "... none to set")
FL = Fr.post(B + "/api/lists", json={"name": "Frida and Gina"}).json()["id"]
dbx("UPDATE users SET email_proved=lower(COALESCE(email, '')) WHERE email_proved=''")  # 2.1001.0 (#5669): a list / folder shared by address binds only a proved address (a mailed link / OIDC); the accounts here proved theirs
check(Fr.put(B + f"/api/lists/{FL}/members", json={"email": "gina@example.com", "role": "edit"}).ok, "setup: frida shares a project with gina (by e-mail: not connected yet)")
check(until(lambda: dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (FL, GID)), 10), "gina is in the project")
check(Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FAG, "role": "edit"}).ok, "and with her agent")
check(Fr.patch(B + f"/api/lists/{FL}", json={"listen_agent_ids": [FAG]}).ok, "her agent listens in")
bg = lambda: dbx("SELECT COUNT(*) FROM bg_jobs WHERE kind='srvagent:run' AND user_id=?", (FAG,))[0][0]  # noqa: E731
check(Gi.post(B + "/api/tasks", json={"title": "GINA-ORDER do this", "list_id": FL}).ok, "gina adds a task")
check(dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=? AND event='task_added' AND payload LIKE '%GINA-ORDER%'", (FAG,))[0][0] == 1,
      "the agent hears of gina's task (data)")
check(bg() == 0 and not runs(FAG), "but gina's task starts no run (no queue row)")
check(Gi.post(B + f"/api/agents/{FAG}/chat", json={"body": "GINA-CHAT"}).status_code in (403, 404), "gina cannot chat with frida's agent")
TF = Gi.post(B + "/api/tasks", json={"title": "Gina's task", "list_id": FL}).json()["id"]
check(Gi.post(B + f"/api/tasks/{TF}/comments", json={"body": f"<@{FAG}> GINA-MENTION"}).ok and bg() == 0, "gina's mention starts nothing either")
check(Fr.post(B + "/api/tasks", json={"title": "Frida asks FAKE_COMMENT " + str(TF), "list_id": FL}).ok, "frida adds a task")
check(until(lambda: agent_comments(TF, FAG), 40), "frida's task starts the run (the agent commented)")
fr = until(lambda: [x for x in runs(FAG) if x[1] != "run"] or None, 20)
check(fr and len(fr) == 1 and fr[0][1] == "done" and fr[0][2] == "task_added" and fr[0][3] == FID, f"one run, for frida {fr}")
check(not any("GINA-CHAT" in json.dumps(x) or "GINA-MENTION" in json.dumps(x) for x in plog()), "gina's chat and mention never reached the model")
# 2.569.0 (#4675 review): a proposal of frida's PERSONAL server agent in the shared project stays frida's - gina (edit) never sees it
r = Fr.post(B + "/api/proposals", json={"agent_id": FAG, "kind": "subtasks", "task_id": TF})
check(r.status_code in (200, 201), f"frida asks her agent for subtasks {r.status_code} {r.text[:200]}")
FJ = r.json().get("job", r.json()).get("id")
r = Fr.post(B + f"/api/my/agents/{FAG}/token", json={})
check(r.ok, f"a token of frida's agent {r.status_code}")
FT = {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"}
r = requests.post(B + f"/api/v1/agent/jobs/{FJ}/proposal", headers=FT, json={"kind": "subtasks", "items": [{"title": "Frida's step"}]}, timeout=30)
check(r.ok, f"her agent's proposal {r.status_code} {r.text[:200]}")
check(Fr.get(B + f"/api/proposals/{FJ}").ok, "frida sees her agent's proposal")
check(Gi.get(B + f"/api/proposals/{FJ}").status_code == 404, "gina (write rights) does not see the personal agent's proposal")
check(Gi.post(B + f"/api/proposals/{FJ}/apply", json={"select": ["0"]}).status_code == 404, "... nor applies it")
check(not any(p["id"] == FJ for p in Gi.get(B + f"/api/lists/{FL}/agent-proposals").json().get("proposals", [])), "... nor finds it in the project")
check(not any(x["kind"] == "job" and x["id"] == FJ for x in Gi.get(B + "/api/inbox").json().get("items", [])), "... nor waiting for her")

logs = subprocess.run(["docker", "logs", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
check(not any(k in logs for k in (KEY_ORG, KEY_FR)), "no key in the server log")
raise SystemExit(done("p2569_b_srvteam"))
