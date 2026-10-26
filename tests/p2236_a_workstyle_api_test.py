#!/usr/bin/env python3
"""2.236.0 A (#2904-#2911): the work style of an agent over GET / PATCH /api/agents/<id>/work-style
 - the owner of a personal agent reads and changes it (one key per PATCH, the rest stays), the value is there after a reload
 - a new agent starts with push "limits" (a team agent too)
 - another person gets 404 (read and write), an invalid value 400, an unknown key 400
 - the same for a person without an organisation (freelancer-matrix: agents); an instance admin reaches a team agent
usage: p2236_a_workstyle_api_test.py <datadir>      (KMT_NOSTART=1 / P2236A_NOSTART=1: a running server)"""
import sys

from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup

fresh(prefix="P2236A")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
OID, O = freelancer(B, A, "otto")


def work(s, aid, method="get", **kw):
    return getattr(s, method)(B + f"/api/agents/{aid}/work-style", **kw)


def own_agent(s, name):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read"]})
    check(r.status_code in (200, 201), f"{name}: a personal agent {r.status_code} {r.text[:120]}")
    return r.json()["id"]


# ---------------------------------------------------------------- the owner (a person without an organisation)
aid = own_agent(F, "fridabot")
r = work(F, aid)
check(r.status_code == 200, f"the owner reads it {r.status_code}")
j = r.json()
check(j["work_style"]["push"] == "limits", f"a new agent starts with push limits: {j['work_style'].get('push')}")
check("defaults" in j and "state" in j, "defaults and state come along")

r = work(F, aid, "patch", json={"max_parallel": 3})
check(r.status_code == 200 and r.json()["work_style"]["max_parallel"] == 3, f"max_parallel saved {r.status_code} {r.text[:100]}")
r = work(F, aid, "patch", json={"priority_rule": "bugs first"})
ws = r.json()["work_style"]
check(r.status_code == 200 and ws["priority_rule"] == "bugs first" and ws["max_parallel"] == 3, "one key per PATCH: the other stays")
r = work(F, aid, "patch", json={"work_days": [1, 3], "budget_period": "week", "budget_limit": 5000, "report_lang": "de"})
check(r.status_code == 200, f"several keys at once {r.status_code}")
ws = work(F, aid).json()["work_style"]
check(ws["work_days"] == [1, 3] and ws["budget_period"] == "week" and ws["budget_limit"] == 5000 and ws["report_lang"] == "de"
      and ws["priority_rule"] == "bugs first" and ws["max_parallel"] == 3, f"the values are there after a reload: {ws}")
check(work(F, aid, "patch", json={"budget_limit": None}).json()["work_style"]["budget_limit"] is None, "an empty limit = no limit")

# ---------------------------------------------------------------- refused
for bad in ({"max_parallel": 21}, {"push": "always"}, {"work_from": "25:00"}, {"next_step": "yes"}, {"budget_limit": -1},
            {"priority_rule": "x" * 501}, {"work_days": []}):
    r = work(F, aid, "patch", json=bad)
    check(r.status_code == 400, f"invalid {bad} -> {r.status_code}")
r = work(F, aid, "patch", json={"no_such_key": 1})
check(r.status_code == 400, f"an unknown key -> {r.status_code}")
check(work(F, aid).json()["work_style"]["max_parallel"] == 3, "a refused PATCH changes nothing")

# ---------------------------------------------------------------- another person
check(work(O, aid).status_code == 404, "another person: GET 404")
check(work(O, aid, "patch", json={"max_parallel": 1}).status_code == 404, "another person: PATCH 404")
check(work(F, aid).json()["work_style"]["max_parallel"] == 3, "the other person changed nothing")
bid = own_agent(O, "ottobot")
check(work(F, bid).status_code == 404, "the freelancer cannot reach the other's agent")
check(work(A, bid).status_code == 404, "an instance admin does not reach a personal agent of someone else")

# ---------------------------------------------------------------- a team agent: the instance admin
r = A.post(B + "/api/admin/agents", json={"username": "teambot", "display_name": "Team", "scopes": ["read"]})
check(r.status_code in (200, 201), f"a team agent {r.status_code} {r.text[:100]}")
tid = r.json()["id"]
check(work(A, tid).json()["work_style"]["push"] == "limits", "a new team agent starts with push limits too")
check(work(A, tid, "patch", json={"push": "never"}).json()["work_style"]["push"] == "never", "the admin changes a team agent")
check(work(F, tid).status_code == 404, "a person without admin rights: 404 on a team agent")
sys.exit(done("p2236_a_workstyle_api"))
