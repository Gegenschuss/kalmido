#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.826.0 B (#5510): the plans of an agent - pause / resume all of MY plans in one step, the starter pack's plan ids.
 - GET /api/agents/<id>/server/starter names the plan id of each starter routine with a plan (ids); a routine without a plan
   (meetings = a rule) has none
 - PATCH /api/agent-schedules/<that id> {enabled: false}: the routine is "paused", the plan stays (not deleted); on again: "active"
 - PATCH /api/agents/<id>/schedules {enabled: false}: every plan of the person with this agent is paused at once (changed = their
   ids, next_at gone); another person's plan with the same agent stays on
 - the undo step {enabled: true, ids}: only those plans are on again, the next run is in the future (missed runs are not made up)
 - ids of another person's plan change nothing; a bad body 400; a person who does not reach the agent 404; an agent token 404
freelancer-matrix: agents (frida has no organisation: her personal server agent and her plans)
tenant-matrix: agent (alice, the instance admin, does not reach frida's personal agent: 404)
usage: p2826_b_api_test.py <datadir>      (KMT_NOSTART=1 / P2826B_NOSTART=1: a running server)"""
import sys

import dbx
from freelancer_fixture import freelancer
from kt import B, DATA, check, dbx as q, done, fresh, sess

fresh(prefix="P2826B")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "comments,collab,agents"})
AID = A.get(B + "/api/state").json()["me"]["id"]
check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 10}).ok, "personal agents allowed")
FID, Fr = freelancer(B, A)

r = Fr.post(B + "/api/my/agents", json={"username": "frida-ki", "display_name": "Frida KI", "provider": "kalmido-server", "org_id": None})
check(r.status_code in (200, 201), f"frida: her personal server agent {r.status_code} {r.text[:200]}")
FA = r.json().get("id")
FL = Fr.post(B + "/api/lists", json={"name": "Garden plans"}).json()["id"]
check(Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "frida shares her own project with it")
r = Fr.post(B + f"/api/agents/{FA}/server/starter", json={"items": ["briefing", "followup", "meetings"]})
check(r.ok, f"the starter pack {r.text[:300]}")

# ---------------------------------------------------------------- the plan ids of the starter routines
j = Fr.get(B + f"/api/agents/{FA}/server/starter").json()
ids = j.get("ids") or {}
db_ids = {r[0]: r[1] for r in q("SELECT srv_flow, id FROM agent_schedules WHERE agent_id=? AND user_id=?", (FA, FID))}
check(set(ids) == {"briefing", "followup"} and ids.get("briefing") == db_ids.get("briefing") and ids.get("followup") == db_ids.get("followup"),
      f"#5510: the plan id per routine with a plan (meetings is a rule: none) {ids} {db_ids}")
check(j["items"].get("briefing") == "active", f"the briefing is on {j['items']}")
check(j.get("shared") is True and j.get("own") is True and j.get("projects") == 1, f"the state route keeps shared / own / projects next to ids {j}")
BR = ids.get("briefing")
r = Fr.patch(B + f"/api/agent-schedules/{BR}", json={"enabled": False})
j = Fr.get(B + f"/api/agents/{FA}/server/starter").json()
check(r.ok and j["items"]["briefing"] == "paused" and j["ids"].get("briefing") == BR, f"switched off: paused, the plan stays {j}")
r = Fr.patch(B + f"/api/agent-schedules/{BR}", json={"enabled": True})
check(r.ok and Fr.get(B + f"/api/agents/{FA}/server/starter").json()["items"]["briefing"] == "active", "switched on again: active")

# ---------------------------------------------------------------- pause all / resume all
r = Fr.post(B + f"/api/agents/{FA}/schedules", json={"title": "Water the plants", "prompt": "Remind me to water the plants.",
                                                      "freq": "daily", "time": "18:00"})
check(r.status_code == 201, f"an own plan of frida {r.status_code} {r.text[:200]}")
OWN = r.json().get("id")
c = dbx.connect(DATA)  # another person's plan with the same agent (a team agent could have one; here written directly)
c.execute("""INSERT INTO agent_schedules(agent_id,user_id,title,prompt,freq,days,at_time,tz,enabled,created_at,updated_at,action)
             SELECT agent_id, ?, 'Alice plan', prompt, freq, days, at_time, tz, true, created_at, updated_at, action FROM agent_schedules WHERE id=?""",
          (AID, OWN))
c.commit()
OTHER = q("SELECT id FROM agent_schedules WHERE agent_id=? AND user_id=?", (FA, AID))[0][0]
mine = sorted([BR, ids["followup"], OWN])

r = Fr.patch(B + f"/api/agents/{FA}/schedules", json={"enabled": False})
check(r.ok and sorted(r.json().get("changed") or []) == mine, f"#5510: pause all: her three plans changed {r.status_code} {r.text[:300]}")
rows = {r[0]: (r[1], r[2]) for r in q("SELECT id, enabled, next_at FROM agent_schedules WHERE agent_id=?", (FA,))}
check(all(rows[i][0] == 0 and rows[i][1] is None for i in mine), f"all of hers paused, no next run {rows}")
check(rows[OTHER][0] == 1, f"another person's plan stays on {rows[OTHER]}")
check(len(r.json().get("data") or []) == 3 and all(not s["enabled"] for s in r.json()["data"]), "the answer lists her plans, all paused")
r = Fr.patch(B + f"/api/agents/{FA}/schedules", json={"enabled": False})
check(r.ok and r.json().get("changed") == [], "pause all again: nothing to change")

r = Fr.patch(B + f"/api/agents/{FA}/schedules", json={"enabled": True, "ids": mine[:2] + [OTHER]})
check(r.ok and sorted(r.json().get("changed") or []) == mine[:2], f"the undo step with ids: only those of hers, never another person's {r.text[:300]}")
r = Fr.patch(B + f"/api/agents/{FA}/schedules", json={"enabled": True})
check(r.ok and r.json().get("changed") == [mine[2]], f"resume all: the rest {r.text[:200]}")
nows = q("SELECT COUNT(*) FROM agent_schedules WHERE agent_id=? AND user_id=? AND enabled AND next_at IS NOT NULL AND next_at > ?",
         (FA, FID, "2000-01-01"))[0][0]
fut = q("SELECT COUNT(*) FROM agent_schedules WHERE agent_id=? AND user_id=? AND enabled AND CAST(next_at AS timestamptz) > now()", (FA, FID))[0][0]
check(nows == 3 and fut == 3, f"resumed: each plan has its next run in the future (no missed runs made up) {nows} {fut}")

# a starter plan that waits for a project of her own (share_wait, #5378 review F2) keeps waiting: Resume all never starts it
FU = ids["followup"]
# CI red of 2.883.0: the watchdog (every TASKS_WATCHDOG_INTERVAL s, sched_wait_wake) wakes this plan by itself - frida owns her
# personal agent, so for the watchdog she has shared it - and left (1, 0) behind although Resume all had left the plan out
# (changed [1, 3]). The endpoint's property is "FU in no changed list"; (1, 0) with FU in no changed list can only be the watchdog,
# then the round is set up again (right after a watchdog round, so the next one is ~30 s away).
for _round in range(3):
    c.execute("UPDATE agent_schedules SET enabled=false, share_wait=1, next_at=NULL WHERE id=?", (FU,))
    c.commit()
    r0 = Fr.patch(B + f"/api/agents/{FA}/schedules", json={"enabled": False})
    r = Fr.patch(B + f"/api/agents/{FA}/schedules", json={"enabled": True})
    touched = FU in (r0.json().get("changed") or []) + (r.json().get("changed") or [])
    st = tuple(q("SELECT enabled, share_wait FROM agent_schedules WHERE id=?", (FU,))[0])
    if touched or st != (1, 0):
        break
    print(f"  (the watchdog woke the waiting plan during round {_round + 1}, again)")
check(r0.ok, "pause all")
check(r.ok and not touched and st == (0, 1),
      f"#5510: Resume all leaves a waiting starter plan waiting {r.text[:200]} {st}")
c.execute("UPDATE agent_schedules SET enabled=false, share_wait=1, next_at=NULL WHERE id=?", (FU,))
c.commit()
r = Fr.patch(B + f"/api/agents/{FA}/schedules", json={"enabled": True, "ids": [FU]})
check(r.ok and r.json().get("changed") == [], "... also when named in ids")

# ---------------------------------------------------------------- refused
check(Fr.patch(B + f"/api/agents/{FA}/schedules", json={"enabled": "no"}).status_code == 400, "enabled must be true / false")
check(Fr.patch(B + f"/api/agents/{FA}/schedules", json={"enabled": True, "ids": "1"}).status_code == 400, "ids must be a list")
check(A.patch(B + f"/api/agents/{FA}/schedules", json={"enabled": False}).status_code == 404, "alice does not reach frida's agent: 404")
check(q("SELECT enabled FROM agent_schedules WHERE id=?", (OTHER,))[0][0] == 1, "... and nothing changed")

sys.exit(done("p2826_b_api"))
