#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.568.0 B (#4673): the Kalmido AI prepares quotations and invoices in the office -- drafts only. Invented companies and figures.
freelancer-matrix: office (a person without an organisation: her personal office and her own server agent)
tenant-matrix: office (the organisation's admin: the organisation's office; another person's agent finds nothing)
 - POST /api/v1/office/invoices (MCP create_invoice_draft, office/agentinvoice.py) with the token of a server agent (provider
   kalmido-server; no model is called here): from_time = the billable, open time of one project (task_id: one task only) ->
   one position per project with the hours and the client's hourly rate, computed by Kalmido (inv_from_time, the person's
   function), the entries bound to the draft (never twice: then 409 no_time); free positions (catalogue / free, marked);
   no number, status draft, missing = what finalising still needs (the person's check inv_missing); client_ref = once
 - an agent never finalises, numbers, sends or cancels: the person's routes take no token (401/403), the agent routes refuse
   status / number fields, the generic object route finds no office document; the draft stays as it was
 - the person finalises afterwards: the number comes only now
 - without the scope office / without the agent's office switch / the area's privacy switch: 403; a project the agent does
   not see: 404
 - the starter item office (agents/srvstarter.py): skipped with the reason while a right is missing (scope, switch, privacy),
   then a weekly plan on Mondays 08:00 + the standing rule "only as drafts"; the same again = exists
usage: p2568_b_ai_office_test.py <datadir>      (KMT_NOSTART=1 / P2568B_NOSTART=1: a running server)"""
import base64
import os
import sys
from datetime import date, timedelta

import requests

from freelancer_fixture import freelancer
from kt import B, H, check, dbx, done, fresh, setup

KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"
D = O + "/docs"
INV = B + "/api/v1/office/invoices"  # tests/tenant_coverage_test.py finds the route by its literal path
SP = "kalmido-server"
TEST_IBAN = "DE02120300000000202051"
T0 = date.today()
D1, D2, D9 = (T0 - timedelta(days=3)).isoformat(), (T0 - timedelta(days=2)).isoformat(), (T0 - timedelta(days=9)).isoformat()
TODAY = T0.isoformat()

fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SECRET_KEY": KEY, "KALMIDO_ORGCRYPT_DELAY": "0"}, prefix="P2568B")
A = setup()
FEAT = "cal,comments,collab,office,clients,docs,time"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 10})
FID, F = freelancer(B, A, features=FEAT)


def agent(S, name, scopes):
    r = S.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "provider": SP, "scopes": scopes})
    check(r.status_code == 201 and r.json().get("provider") == SP, f"{name}: a server agent {r.status_code} {r.text[:160]}")
    j = r.json()
    return j["id"], {"Authorization": "Bearer " + j["token"], **H}


def starter(S, aid):
    r = S.post(B + f"/api/agents/{aid}/server/starter", json={"items": ["office"]})
    check(r.ok, f"starter office {r.status_code} {r.text[:200]}")
    return (r.json().get("items") or [{}])[0] if r.ok else {}


def entry(uid, lid, tid, day, secs):
    dbx("INSERT INTO time_entries(user_id, list_id, task_id, task_title, start, \"end\", seconds, note, source, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (uid, lid, tid, "Edit", day + "T08:00:00Z", day + "T09:00:00Z", secs, "", "manual", day + "T09:00:00Z", day + "T09:00:00Z"))


def head(did):
    r = dbx("SELECT number, status, locked_at, totals FROM office_docs WHERE id=?", (did,))
    return dict(r[0]) if r else None


for who, S, uid in (("org admin", A, ALICE), ("freelancer", F, FID)):
    # freelancer-matrix: office
    r = S.put(B + O + "/settings", json={"lang": "en", "currency": "EUR",
                                         "company_fields": {"name": "Example Studio GmbH", "street": "Sample Road 1", "zip": "12345", "city": "Sampletown",
                                                            "country": "DE", "email": "hello@example.com", "tax_number": "12/345/67890",
                                                            "vat_id": "DE999999999", "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Example Bank"}})
    check(r.ok, f"{who}: office settings " + r.text[:160])
    r = S.post(B + "/api/clients", json={"name": "Example Client AG", "street": "Market 2", "zip": "54321", "city": "Example City", "country": "DE",
                                         "vat_id": "DE987654321", "email_invoice": "billing@example.com", "rate": 80})
    check(r.status_code == 201, f"{who}: a client " + r.text[:160])
    CL = r.json().get("id")
    r = S.post(B + "/api/clients", json={"name": "Bare Client"})
    CL2 = r.json().get("id")
    r = S.post(B + "/api/lists", json={"name": "Film project", "org_id": ORG if S is A else None})
    check(r.status_code in (200, 201), f"{who}: a project " + r.text[:160])
    LP = r.json()["id"]
    check(S.patch(B + f"/api/lists/{LP}", json={"client_id": CL}).ok, f"{who}: the project has the client")
    r = S.post(B + "/api/lists", json={"name": "Hidden project", "org_id": ORG if S is A else None})
    LH = r.json()["id"]
    S.patch(B + f"/api/lists/{LH}", json={"client_id": CL})
    T1 = S.post(B + "/api/tasks", json={"list_id": LP, "title": "Edit the film"}).json()["id"]
    entry(uid, LP, T1, D1, 7200)   # 2 h on the task
    entry(uid, LP, None, D2, 3600)  # 1 h on the project
    entry(uid, LH, None, D2, 3600)  # 1 h in a project the agent does not see

    # ---- the starter item office: skipped with its reason until every right is there
    G0, H0 = agent(S, f"ki0{len(who)}", ["read"])
    x = starter(S, G0)
    check(x.get("state") == "skipped" and "Office drafts" in (x.get("reason") or ""), f"{who}: no scope office -> skipped, names the permission {x}")
    r = requests.post(INV, headers=H0, json={"client_id": CL, "from_time": True, "list_id": LP, "from": D9, "to": TODAY})
    check(r.status_code == 403, f"{who}: an agent without the scope office: 403 ({r.status_code} {r.text[:160]})")
    G, AH = agent(S, f"ki1{len(who)}", ["read", "office"])
    x = starter(S, G)
    check(x.get("state") == "skipped" and "May draft office documents" in (x.get("reason") or ""), f"{who}: office switch off -> skipped {x}")
    r = requests.post(INV, headers=AH, json={"client_id": CL, "items": [{"text": "Cut", "qty": 1, "price": 100}]})
    check(r.status_code == 403, f"{who}: the agent's office switch off: 403 ({r.status_code})")
    check(S.patch(B + f"{O}/agents/{G}", json={"office_drafts": True}).ok, f"{who}: the agent's office switch on")
    S.put(B + O + "/settings", json={"agents_read": 0})
    x = starter(S, G)
    check(x.get("state") == "skipped" and "Agents may read office data" in (x.get("reason") or ""), f"{who}: privacy switch off -> skipped {x}")
    r = requests.post(INV, headers=AH, json={"client_id": CL, "items": [{"text": "Cut", "qty": 1, "price": 100}]})
    check(r.status_code == 403, f"{who}: the area's privacy switch off: 403 ({r.status_code})")
    check(S.put(B + O + "/settings", json={"agents_read": 1}).ok, f"{who}: agents may read office data")
    n_plans, n_rules = len(S.get(B + f"/api/agents/{G}/schedules").json()["data"]), len(S.get(B + f"/api/agents/{G}/rules").json()["rules"])
    check(n_plans == 0 and n_rules == 0, f"{who}: the skipped item made nothing ({n_plans}, {n_rules})")
    x = starter(S, G)
    check(x.get("state") == "created", f"{who}: every right there -> created {x}")
    ps = S.get(B + f"/api/agents/{G}/schedules").json()["data"]
    rs = [r_["text"] for r_ in S.get(B + f"/api/agents/{G}/rules").json()["rules"]]
    check(len(ps) == 1 and ps[0]["freq"] == "weekly" and ps[0]["days"] == [1] and ps[0]["time"] == "08:00" and ps[0]["title"] == "Due billing"
          and "approval card" in ps[0]["prompt"] and "never finalise" in ps[0]["prompt"], f"{who}: a weekly plan Mondays 08:00, only after approval {ps}")
    check(len(rs) == 1 and "only as drafts" in rs[0] and "never finalise, number, send or cancel" in rs[0], f"{who}: the standing rule {rs}")
    check(starter(S, G).get("state") == "exists", f"{who}: the same again: exists")
    check(len(S.get(B + f"/api/agents/{G}/schedules").json()["data"]) == 1 and len(S.get(B + f"/api/agents/{G}/rules").json()["rules"]) == 1,
          f"{who}: the same again: nothing twice")

    # ---- the agent must see the project
    check(S.put(B + f"/api/lists/{LP}/members", json={"user_id": G, "role": "edit"}).ok, f"{who}: the project shared with the agent")
    r = requests.post(INV, headers=AH, json={"client_id": CL, "from_time": True, "list_id": LH, "from": D9, "to": TODAY})
    check(r.status_code == 404, f"{who}: a project the agent does not see: 404 ({r.status_code} {r.text[:160]})")
    for bad in ({"client_id": CL, "from_time": True, "from": D9, "to": TODAY},  # no project
                {"client_id": CL, "from_time": True, "list_id": LP},  # no period
                {"client_id": CL, "from_time": True, "list_id": LP, "from": TODAY, "to": D9},  # period backwards
                {"client_id": CL, "from_time": "yes", "list_id": LP, "from": D9, "to": TODAY},
                {"client_id": CL, "from_time": True, "list_id": LP, "from": D9, "to": TODAY, "items": [{"text": "x", "qty": 1, "price": 1}]},
                {"from_time": True, "list_id": LP, "from": D9, "to": TODAY},  # no client
                {"client_id": CL, "items": [], "status": "final"}, {"client_id": CL, "items": [], "number": "RE-1"}):
        r = requests.post(INV, headers=AH, json=bad)
        check(r.status_code == 400, f"{who}: wrong input {bad}: 400 ({r.status_code} {r.text[:120]})")

    # ---- from the time of one task, then the rest of the project (never twice)
    r = requests.post(INV, headers=AH, json={"client_id": CL, "from_time": True, "list_id": LP, "task_id": T1, "from": D9, "to": TODAY,
                                                         "title": "Film edit", "client_ref": f"ref-{who}"})
    check(r.status_code == 201, f"{who}: an invoice draft from the task's time {r.status_code} {r.text[:300]}")
    j = r.json() if r.status_code == 201 else {}
    d = j.get("doc") or {}
    I1 = d.get("id")
    its = [i for i in d.get("items") or [] if i.get("kind") == "service"]
    check(d.get("kind") == "invoice" and d.get("status") == "draft" and not d.get("number") and d.get("project_title") == "Film edit"
          and d.get("list_id") == LP and d.get("service_from") == D9 and d.get("service_to") == TODAY,
          f"{who}: a draft, no number, title, project, service period {({k: d.get(k) for k in ('kind', 'status', 'number', 'list_id', 'service_from', 'service_to')})}")
    check(len(its) == 1 and float(its[0]["qty"]) == 2.0 and float(its[0]["rate"]) == 80.0, f"{who}: one position, 2 h of the task at the client's rate {its}")
    tot = d.get("totals") or {}
    check(float(tot.get("net") or 0) == 160.0 and float(tot.get("gross") or 0) == 190.4, f"{who}: net and gross computed by Kalmido (19 % VAT) {tot.get('net')} {tot.get('gross')}")
    check(j.get("missing") == [], f"{who}: nothing missing before finalising {j.get('missing')}")
    check(head(I1)["number"] == "", f"{who}: no number in the database")
    r = requests.post(INV, headers=AH, json={"client_id": CL, "from_time": True, "list_id": LP, "task_id": T1, "from": D9, "to": TODAY,
                                                         "client_ref": f"ref-{who}"})
    check(r.status_code == 200 and (r.json().get("doc") or {}).get("id") == I1, f"{who}: the same client_ref again: the same draft ({r.status_code})")
    r = requests.post(INV, headers=AH, json={"client_id": CL, "from_time": True, "list_id": LP, "from": D9, "to": TODAY})
    check(r.status_code == 201, f"{who}: the rest of the project's time {r.status_code} {r.text[:200]}")
    I2 = (r.json().get("doc") or {}).get("id") if r.status_code == 201 else None
    its = [i for i in ((r.json().get("doc") or {}).get("items") or []) if i.get("kind") == "service"] if I2 else []
    check(len(its) == 1 and float(its[0]["qty"]) == 1.0, f"{who}: only the 1 h left, the task's 2 h are on the first draft {its}")
    r = requests.post(INV, headers=AH, json={"client_id": CL, "from_time": True, "list_id": LP, "from": D9, "to": TODAY})
    check(r.status_code == 409 and r.json()["error"]["code"] == "no_time", f"{who}: nothing open any more: 409 no_time ({r.status_code} {r.text[:160]})")

    # ---- free positions
    r = requests.post(INV, headers=AH, json={"client_id": CL2, "title": "Workshop", "from": D9, "to": TODAY, "notify": True,
                                                         "items": [{"text": "Workshop day", "qty": 2, "unit": "day", "price": 500}]})
    check(r.status_code == 201, f"{who}: a free invoice draft {r.status_code} {r.text[:300]}")
    j = r.json() if r.status_code == 201 else {}
    d = j.get("doc") or {}
    I3 = d.get("id")
    its = [i for i in d.get("items") or [] if i.get("kind") == "service"]
    check(d.get("kind") == "invoice" and d.get("status") == "draft" and not d.get("number") and len(its) == 1 and float(its[0]["rate"]) == 500.0
          and "free" in (its[0].get("agent_flag") or ""), f"{who}: free position, marked for the person {its}")
    check(float((d.get("totals") or {}).get("net") or 0) == 1000.0 and float((d.get("totals") or {}).get("gross") or 0) == 1190.0,
          f"{who}: Kalmido's totals {d.get('totals', {}).get('net')} {d.get('totals', {}).get('gross')}")
    check(j.get("missing") and isinstance(j["missing"], list), f"{who}: a client without an address: missing names it {j.get('missing')}")
    check(j.get("chat_message_id"), f"{who}: notify: a card in the person's chat")

    # ---- an agent never finalises, numbers, sends or cancels
    before = head(I1)
    for m, path, body in (("POST", f"{D}/{I1}/finalize", {}), ("POST", f"{D}/{I1}/number", {}), ("POST", f"{D}/{I1}/send", {"to": "billing@example.com"}),
                          ("POST", f"{D}/{I1}/status", {"status": "sent"}), ("POST", f"{D}/{I1}/credit", {}), ("PATCH", f"{D}/{I1}", {"number": "RE-1"}),
                          ("PATCH", f"/api/v1/office/offers/{I1}", {"title": "x"}), ("PATCH", f"/api/v1/office/offers/{I1}", {"status": "final"}),
                          ("POST", f"/api/v1/office/invoices/{I1}/finalize", {}), ("PATCH", f"/api/v1/office/invoices/{I1}", {"status": "final"}),
                          ("PATCH", f"/api/v1/agent/objects/office_doc/{I1}", {"status": "final", "expect_updated_at": "x"}),
                          ("PATCH", f"/api/v1/agent/objects/invoice/{I1}", {"status": "final", "expect_updated_at": "x"})):
        r = requests.request(m, B + path, headers=AH, json=body)
        check(400 <= r.status_code < 500, f"{who}: agent {m} {path}: refused ({r.status_code} {r.text[:120]})")
    check(head(I1) == before, f"{who}: the draft is unchanged {head(I1)}")

    # ---- the person finalises: only now the number
    r = S.post(B + f"{D}/{I1}/finalize")
    check(r.ok, f"{who}: the person finalises the agent's draft {r.status_code} {r.text[:300]}")
    h1 = head(I1)
    check(h1["number"] and h1["locked_at"], f"{who}: the number comes only when the person finalises {h1['number']}")

    # ---- another person's agent finds nothing of it (tenant-matrix: office)
    if S is F:
        r = requests.post(INV, headers=AH0_ORG, json={"client_id": CL, "items": [{"text": "x", "qty": 1, "price": 1}]})
        check(r.status_code in (400, 403, 404), f"the organisation's agent with the freelancer's client: refused ({r.status_code})")
        check(not dbx("SELECT 1 FROM office_docs WHERE client_id=? AND agent_id=?", (CL, AG_ORG)), "nothing made with another office's client")
    else:
        AG_ORG, AH0_ORG = G, AH

sys.exit(done("p2568_b_ai_office"))
