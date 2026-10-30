#!/usr/bin/env python3
# kalmido-suite:
"""2.421.0 A (#2936) API tests: the second freelancer, on a server as a hosted one starts (KALMIDO_HOSTED=1, organisations
of other customers on it). The admin only creates the account -- no collaboration / time switch in the setup, no agent
policy (p287b_a_freelancer_api_test.py runs with them on). The person turns the own modules on and does the core ways that
must work without any admin switch (freelancer parity): a private list with a task and a subtask, done; a time entry and
the timer; the personal office (company fields, a client, a quotation, its invoice, finalised, the PDF); an own agent with
its token that reads the private list it was given. Invented names only.
freelancer-matrix: tasks, time, office, agents
usage: p2421_a_api_test.py <datadir>      (a fresh container; KMT_NOSTART=1 = the server already runs)"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, done, fresh, H, PASSWORD, sess  # noqa: E402,F401

fresh({"KALMIDO_HOSTED": "1", "KALMIDO_INSTANCE_MODE": "workspaces"})
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "otto", "display_name": "Otto Operator", "password": PASSWORD}).ok
A = sess("otto")
# the first-run step with nothing switched on (no collab_all / time_all / modules), the language only
assert A.post(B + "/api/admin/setup", json={"lang": "en", "modules": []}).ok
OTTO = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Other customer", "admin_id": OTTO})  # another customer on the server
check(r.status_code in (200, 201), f"setup: an organisation of another customer {r.status_code} {r.text[:160]}")
check(A.get(B + "/api/about").json().get("hosted") is True or bool(os.environ.get("KMT_NOSTART")), "setup: a hosted server")
pol = A.get(B + "/api/admin/agent-policy").json()
check(pol.get("user_agents") is False, f"setup: the server's agent switch is off (nobody turned it on) {pol}")


def ok(r, what, codes=(200, 201, 204)):
    check(r.status_code in codes, f"{what}: {r.status_code} {r.text[:200]}")
    try:
        return r.json() if r.content else {}
    except ValueError:
        return {}


# the admin creates the account (no organisation); the person turns the modules on herself (freelancer_fixture)
FID, F = freelancer(B, A, "hanna")
st = F.get(B + "/api/state").json()
check(st["me"].get("workspaces") == [], "hosted: the person is in no organisation")

# ---- tasks: a private list, a task, a subtask, done (collaboration is not needed in the own private space)
L = ok(F.post(B + "/api/lists", json={"name": "Clients", "kind": "project", "time_tracking": True}), "tasks: a private list", (200, 201))
check(L.get("org_id") in (None, 0), f"tasks: the list is private {L.get('org_id')}")
T = ok(F.post(B + "/api/tasks", json={"list_id": L.get("id"), "title": "Edit the reel"}), "tasks: a task", (200, 201))
S = ok(F.post(B + "/api/tasks", json={"list_id": L.get("id"), "title": "Sound", "parent_id": T.get("id")}), "tasks: a subtask", (200, 201))
ok(F.post(B + f"/api/tasks/{S.get('id')}/complete"), "tasks: the subtask done")
ok(F.post(B + f"/api/tasks/{T.get('id')}/comments", json={"body": "note to self"}), "tasks: a comment", (200, 201))

# ---- time: an entry and the timer (the server's time switch was never touched: its default is on)
ok(F.post(B + "/api/time/entries", json={"list_id": L.get("id"), "start": "2026-09-01T09:00", "minutes": 45}), "time: an entry", (200, 201))
ok(F.post(B + "/api/time/start", json={"task_id": T.get("id")}), "time: the timer starts", (200, 201))
ok(F.post(B + "/api/time/stop", json={}), "time: the timer stops", (200, 201))
check(any(x.get("seconds") == 2700 for x in ok(F.get(B + "/api/time/entries"), "time: the entries").get("entries", [])),
      "time: the own entry is listed")

# ---- office: the personal office, its own admin
o = ok(F.get(B + "/api/office/settings"), "office: opens without an organisation")
check(o.get("personal") == 1 and o.get("role") == "admin", f"office: the personal office, its own admin {o.get('personal')} {o.get('role')}")
ok(F.put(B + "/api/office/settings", json={"company_fields": {"name": "Hanna Schnitt", "street": "Kaiweg 2", "zip": "20457",
                                                                "city": "Hamburg", "country": "DE", "tax_number": "12/345/67890",
                                                                "iban": "DE02120300000000202051", "bic": "BYLADEM1001"}}),
   "office: company fields")
cl = ok(F.post(B + "/api/clients", json={"name": "Beispiel GmbH", "street": "Markt 1", "zip": "50667", "city": "Köln", "country": "DE"}),
        "office: a private client", (200, 201))
q = ok(F.post(B + "/api/office/docs", json={"project_title": "Reel", "client_id": cl.get("id"), "service_from": "2026-09-01",
                                            "service_to": "2026-09-30"}), "office: a quotation", (200, 201))
ok(F.put(B + f"/api/office/docs/{q.get('id')}/items", json={"items": [{"title": "Edit", "qty": 2, "rate": 500}]}), "office: positions")
inv = ok(F.post(B + f"/api/office/docs/{q.get('id')}/invoice"), "office: the invoice from the quotation", (200, 201))
ok(F.post(B + f"/api/office/docs/{inv.get('id')}/finalize"), "office: the invoice finalised")
r = F.get(B + f"/api/office/docs/{inv.get('id')}/pdf")
check(r.status_code == 200 and r.content[:4] == b"%PDF", f"office: the PDF {r.status_code}")

# ---- agents: an own agent without the server's switch. On a server with organisations the private area is the
# person's own (agent_ws_allowed, #2928); a server WITHOUT organisations is one team, there the admin's switch decides
# (intended, not checked here)
ag = ok(F.post(B + "/api/my/agents", json={"username": "hannabot", "display_name": "Hanna's bot", "scopes": ["read", "tasks:write"]}),
        "agents: an own agent without the server's switch", (200, 201))
ok(F.put(B + f"/api/lists/{L.get('id')}/members", json={"user_id": ag.get("id"), "role": "edit"}), "agents: the agent in the private list")
tok = ok(F.post(B + f"/api/my/agents/{ag.get('id')}/token"), "agents: its token").get("token", "")
r = requests.get(B + "/api/v1/lists", headers={"Authorization": "Bearer " + tok})
check(r.ok and str(L.get("id")) in r.text, f"agents: the agent reads the private list it was given {r.status_code} {r.text[:160]}")

# nothing of the other customer
check(not any(x.get("org_id") for x in F.get(B + "/api/state").json().get("lists", [])), "hosted: no list of an organisation")

sys.exit(done("p2421_a_api"))
