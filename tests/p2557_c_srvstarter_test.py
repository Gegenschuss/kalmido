#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.557.0 C (#4670): the setup of a server agent ("Kalmido AI") -- defaults and the starter pack (kalmido/agents/srvstarter.py)
 - GET /api/agents/server/defaults: the instance switch, the suggested name / model / instructions (only for people)
 - POST /api/agents/<id>/server/starter: each of the five items alone on its own agent (briefing = plan daily 07:30,
   tidy = plan triage daily 07:00, docs = levels "agent" for sender / type / tags + a standing rule, meetings = a standing
   rule, followup = plan on weekdays 09:00 with the days in its order), then all at once; the same again = "exists", no
   duplicate; each setting is an ordinary one afterwards (the plan switched off and deleted on its own)
 - wrong input 400, another person / an agent token 404, a team agent without a shared project: plans "skipped"
 - the instance switch server_agents_off (PATCH /api/admin/settings, about): off -> defaults say so, starter 403
 - the same as a person without an organisation (freelancer-matrix: agents)
usage: p2557_c_srvstarter_test.py <datadir>      (KMT_NOSTART=1 / P2557C_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, H, check, done, fresh, sess

fresh(prefix="P2557C")
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Org", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 10})
FID, F = freelancer(B, A)
OID, O = freelancer(B, A, "otto")
SP = "kalmido-server"


def own_agent(s, name):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "provider": SP})
    check(r.status_code in (200, 201), f"{name}: a personal server agent {r.status_code} {r.text[:120]}")
    j = r.json()
    check(j.get("provider") == SP, f"{name}: provider kalmido-server kept")
    return j["id"], {"Authorization": "Bearer " + j["token"]}


def starter(s, aid, items, **kw):
    return s.post(B + f"/api/agents/{aid}/server/starter", json={"items": items, **kw})


def states(r):
    return {x["item"]: x["state"] for x in (r.json().get("items") or [])} if r.ok else {}


def plans(s, aid):
    return [p for p in s.get(B + f"/api/agents/{aid}/schedules").json()["data"]]


def rules(s, aid):
    return [r["text"] for r in s.get(B + f"/api/agents/{aid}/rules").json()["rules"]]


def levels(s):
    return s.get(B + "/api/docs/settings?ws=private").json()["levels"]


# ================================================================ the defaults
# freelancer-matrix: agents
d = F.get(B + "/api/agents/server/defaults")
check(d.ok, f"defaults for a person {d.status_code}")
d = d.json()
check(d["enabled_instance"] is True and d["provider"] == SP, f"defaults: allowed, provider {d}")
check(d["default_model"] == "claude-sonnet-5-5", f"defaults: the model of the decision of 05.11.2026 ({d['default_model']})")
check(d["default_name"] == "Kalmido AI" and "only" in d["default_instructions"] and "outside Kalmido" in d["default_instructions"],
      "defaults: the name and the instructions (Kalmido only)")
# 2.568.0 (#4673): + office (tests/p2568_b_ai_office_test.py)
check(d["starter"] == ["briefing", "tidy", "docs", "meetings", "followup", "office"] and d["followup_days"] == 5, f"defaults: the starter pack {d['starter']}")
# 2.621.0 (#4715): the workspace the item "documents" meets, per owner choice of the dialog: a person without an organisation
# only "me" = Private; an organisation admin also org:<id> with its name
check(d["docs_scopes"] == [{"key": "me", "name": "Private"}], f"defaults: a person without an organisation: Private only {d['docs_scopes']}")
da = A.get(B + "/api/agents/server/defaults").json()["docs_scopes"]
check(da[0] == {"key": "me", "name": "Private"} and any(x["key"] == f"org:{ORG}" and x["name"] for x in da), f"defaults: an admin also sees the organisation {da}")
F.patch(B + "/api/settings", json={"lang": "de"})
check(F.get(B + "/api/agents/server/defaults").json()["default_name"] == "Kalmido-KI", "defaults in German: Kalmido-KI")
F.patch(B + "/api/settings", json={"lang": "en"})

# ================================================================ each item alone (a person without an organisation)
before = levels(F)
check(before["sender"] != "agent", f"documents: not 'agent' before ({before})")
AG = {}
for k in ("briefing", "tidy", "docs", "meetings", "followup"):
    AG[k] = own_agent(F, f"ki{k}")[0]
    r = starter(F, AG[k], [k], **({"followup_days": 7} if k == "followup" else {}))
    check(r.ok and states(r) == {k: "created"}, f"{k} alone: created {r.status_code} {r.text[:200]}")
    ps, rs = plans(F, AG[k]), rules(F, AG[k])
    if k == "briefing":
        check(len(ps) == 1 and ps[0]["freq"] == "daily" and ps[0]["time"] == "07:30" and ps[0]["action"] == "chat"
              and ps[0]["enabled"] and ps[0]["title"] == "Morning briefing" and "read-only" in ps[0]["prompt"] and not rs,
              f"briefing: one plan daily 07:30 in the chat, read only {ps} {rs}")
    elif k == "tidy":
        check(len(ps) == 1 and ps[0]["action"] == "triage" and ps[0]["time"] == "07:00" and ps[0]["freq"] == "daily"
              and "proposal" in ps[0]["prompt"] and not rs, f"tidy: a plan 'Sort the basket' daily 07:00 {ps}")
    elif k == "docs":
        lv = levels(F)
        check(lv["sender"] == lv["type"] == lv["tags"] == "agent" and lv["folder"] == before["folder"] and not ps
              and len(rs) == 1 and "never set them yourself" in rs[0], f"docs: levels agent for sender/type/tags, folder unchanged, one rule {lv} {rs}")
    elif k == "meetings":
        check(not ps and len(rs) == 1 and "Tasks from notes" in rs[0], f"meetings: one standing rule {rs}")
    else:
        check(len(ps) == 1 and ps[0]["freq"] == "weekdays" and ps[0]["time"] == "09:00" and "7 days" in ps[0]["prompt"]
              and "approval" in ps[0]["prompt"] and not rs, f"followup: a plan on weekdays 09:00, 7 days, only after approval {ps}")

# all at once on one agent, then the same again: nothing twice
ALL = ["briefing", "tidy", "docs", "meetings", "followup"]
KI, KH = own_agent(F, "kalmido-ki")
r = starter(F, KI, ALL)
check(r.ok and set(states(r).values()) == {"created"} and len(states(r)) == 5, f"all five: created {r.text[:300]}")
check(set(states(r)) == set(ALL), "all five reported")
n_p, n_r = len(plans(F, KI)), len(rules(F, KI))
check(n_p == 3 and n_r == 2, f"all five: 3 plans + 2 standing rules ({n_p}, {n_r})")
check(any("5 days" in p["prompt"] for p in plans(F, KI)), "followup without days: the default 5")
r = starter(F, KI, ALL)
check(r.ok and set(states(r).values()) == {"exists"}, f"the same again: exists {r.text[:300]}")
check(len(plans(F, KI)) == n_p and len(rules(F, KI)) == n_r, "the same again: no duplicate")
# afterwards each one is an ordinary setting: the plan of the briefing switched off and deleted on its own
pb = next(p for p in plans(F, KI) if p["title"] == "Morning briefing")
check(F.patch(B + f"/api/agent-schedules/{pb['id']}", json={"enabled": False}).ok, "the briefing plan switched off on its own")
check(F.delete(B + f"/api/agent-schedules/{pb['id']}").ok, "the briefing plan deleted on its own")
check(len(plans(F, KI)) == n_p - 1, "the other plans stay")

# 2.621.0 (#4715): the plans are found by a fixed marker, not by the translated title: a second call in another language adds nothing
F.patch(B + "/api/settings", json={"lang": "de"})
r = starter(F, KI, [x for x in ALL if x != "briefing"])  # (the briefing plan of KI was deleted above)
check(r.ok and set(states(r).values()) == {"exists"}, f"other language: exists, no second plan {r.text[:300]}")
check(len(plans(F, KI)) == n_p - 1 and len(rules(F, KI)) == n_r - 0, "other language: nothing added")
r = starter(F, AG["briefing"], ["briefing"])
check(states(r) == {"briefing": "exists"} and len(plans(F, AG["briefing"])) == 1, f"other language: the briefing plan of another agent stays one {r.text[:200]}")
# a plan of an older pack (no marker) made by hand with the German title is still found
DE = "Tagesüberblick"
check(DE != "Morning briefing", "the German title differs")
OLD = own_agent(F, "kioldplan")[0]
r = F.post(B + f"/api/agents/{OLD}/schedules", json={"title": DE, "prompt": "x", "freq": "daily", "time": "07:30", "action": "chat", "enabled": True})
if r.ok:
    F.patch(B + "/api/settings", json={"lang": "en"})
    r = starter(F, OLD, ["briefing"])
    check(states(r) == {"briefing": "exists"} and len(plans(F, OLD)) == 1, f"an older plan by its German title is found {r.text[:200]}")
F.patch(B + "/api/settings", json={"lang": "en"})

# ================================================================ wrong input, rights
for bad in ({"items": []}, {"items": ["web"]}, {"items": "briefing"}, {"items": ["followup"], "followup_days": 0},
            {"items": ["followup"], "followup_days": 61}, {"items": ["followup"], "followup_days": True},
            {"items": ["briefing"], "extra": 1}):
    r = F.post(B + f"/api/agents/{KI}/server/starter", json=bad)
    check(r.status_code == 400, f"wrong input {bad}: 400 ({r.status_code})")
check(starter(O, KI, ["briefing"]).status_code == 404, "another person: 404")
check(requests.post(B + f"/api/agents/{KI}/server/starter", headers=KH, json={"items": ["briefing"]}).status_code in (401, 403, 404),
      "the agent's own token: refused")
check(requests.get(B + "/api/agents/server/defaults", headers=KH).status_code in (401, 403, 404), "defaults: not for an agent token")
check(starter(F, 999999, ["briefing"]).status_code == 404, "an unknown agent: 404")

# ================================================================ a team agent of the organisation (instance admin)
r = A.post(B + "/api/admin/agents", json={"username": "teamki", "display_name": "Team KI", "provider": SP, "org_id": ORG})
check(r.status_code in (200, 201), f"a team server agent {r.status_code} {r.text[:200]}")
TA = r.json()["id"]
r = starter(A, TA, ["briefing", "docs"])
st = states(r)
check(r.ok and st.get("briefing") == "skipped" and st.get("docs") == "created", f"team agent: plan skipped without a shared project, docs of the organisation created {r.text[:300]}")
check(next(x for x in r.json()["items"] if x["item"] == "briefing")["reason"], "skipped: with its reason")
check(A.get(B + f"/api/docs/settings?ws=org:{ORG}").json()["levels"]["type"] == "agent", "the organisation's documents: type = agent")
check(starter(F, TA, ["briefing"]).status_code == 404, "a team agent: not for a person without the admin role (404)")

# ================================================================ the instance switch
r = A.patch(B + "/api/admin/settings", json={"server_agents_off": True})
check(r.ok and r.json().get("server_agents_off") is True, f"the instance switch off {r.status_code}")
check(F.get(B + "/api/agents/server/defaults").json()["enabled_instance"] is False, "defaults: switched off")
r = starter(F, KI, ["meetings"])
check(r.status_code == 403 and r.json().get("error") == "server_agents_off", f"starter while off: 403 server_agents_off ({r.status_code} {r.text[:120]})")
check(F.get(B + "/api/about").json().get("server_agents_off") is None, "about: the switch only for admins")
r = F.put(B + f"/api/agents/{KI}/server", json={"model": "claude-haiku-5-5"})
check(r.status_code == 403 and r.json().get("error") == "server_agents_off", f"PUT …/server while off: 403 server_agents_off ({r.status_code})")
check(A.patch(B + "/api/admin/settings", json={"server_agents_off": True}).ok, "switching off again asks nothing")
check(A.patch(B + "/api/admin/settings", json={"server_agents_off": "yes"}).status_code == 400, "the switch: only true / false")
r = A.patch(B + "/api/admin/settings", json={"server_agents_off": False})
check(r.status_code == 403 and r.json().get("password_needed") is True, f"allowing them again asks for the password ({r.status_code})")
check(A.patch(B + "/api/admin/settings", json={"server_agents_off": False, "password": "wrong-pass"}).status_code in (400, 401, 403), "a wrong password: refused")
check(F.get(B + "/api/agents/server/defaults").json()["enabled_instance"] is False, "still off after the refusals")
r = A.patch(B + "/api/admin/settings", json={"server_agents_off": False, "password": "password123"})
check(r.ok and r.json().get("server_agents_off") is False, "the instance switch on again (with the password)")
check(F.put(B + f"/api/agents/{KI}/server", json={"model": "claude-haiku-5-5"}).ok, "PUT …/server works again")
check(F.get(B + "/api/agents/server/defaults").json()["enabled_instance"] is True, "defaults: allowed again")
sys.exit(done("p2557_c_srvstarter"))
