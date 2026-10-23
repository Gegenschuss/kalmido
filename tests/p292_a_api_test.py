#!/usr/bin/env python3
"""2.92.0 API tests, part A (#1925): business contracts and insurances in the office, own container (start.sh, org
encryption on). Invented companies, people and figures only.
 - CRUD of a contract (office admin), strict fields, cost / number / note encrypted at rest, soft delete + restore
 - the last day to cancel (end of term minus notice; a passed one rolls on with the renewal, a contract without renewal is
   simply over), the deadline task (fam kind contract + office_agreement): created in the inbox or a chosen list, follows
   name / end / lead, switched off = ended, a deleted task comes back on the next save, archive / delete end it (never
   deleted), unarchive / restore bring a new one
 - the agent "contracts in view" hears of an office contract (event contract_notice) when the deadline task's list is
   shared with it, also without the module "At home > Contracts"; an agent without the list hears nothing
 - the cash flow: contributions with cashflow on as kind agreement, exactly once, net / gross by the VAT rate; read-only rows
   in the fixed costs (no copy in office_fixed_costs); off = not in the cash flow
 - the contract document: a document of the office's documents space; one of another organisation 404
 - rights (tenant-matrix: office): a member 403, another organisation 404 everywhere, an agent token 403; a person without
   organisation has their own (personal office) and a second person sees nothing of it
usage: p292_a_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
from kt import FAILS, OKS, check, sess, until, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
V = B + "/api/v1"
KEY = base64.b64encode(os.urandom(32)).decode()


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def ym_add(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def months_add(d, n):
    """date d plus n months (the day kept, the 31st becomes the month's last day)."""
    y, m = d.year, d.month - 1 + n
    y, m = y + m // 12, m % 12 + 1
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return date(y, m, min(d.day, (nxt - timedelta(days=1)).day))


def task(tid):
    r = sql("SELECT id, list_id, title, due, repeat, reminders, status, fam, deleted_at, content FROM tasks WHERE id=?", (tid,))
    if not r:
        return None
    t = dict(zip(("id", "list_id", "title", "due", "repeat", "reminders", "status", "fam", "deleted_at", "content"), r[0]))
    t["fam"] = json.loads(t["fam"] or "{}")
    return t


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
if not os.environ.get("P292A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Frei"), ("erik", "Erik Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do, Er = sess("bob"), sess("carol"), sess("dora"), sess("erik")
FEAT = "cal,comments,collab,office,clients,docs,agents"  # no "contracts" (At home): the office contracts do not need it
for s in (A, Bo, Ca, Do, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
O = "/api/office"
AG = O + "/agreements"
T0 = testclock.today()
TODAY = T0.isoformat()
D = lambda n: (T0 + timedelta(days=n)).isoformat()  # noqa: E731
M0 = TODAY[:7]
INBOX = [l["id"] for l in A.get(B + "/api/state").json()["lists"] if l.get("is_inbox")][0]

# ---------------------------------------------------------------- tenant-matrix: office -- CRUD + fields
j = A.get(B + AG).json()
check(j["items"] == [] and j["doc_ws"] == f"org:{ORG}" and any(l["id"] == INBOX and l["inbox"] for l in j["lists"]), f"#1925: the empty list, documents space, lists {j}")
ENDS = T0 + timedelta(days=60)
r = A.post(B + AG, json={"kind": "insurance", "name": "Betriebshaftpflicht", "provider": "Beispiel Versicherung AG", "number": "P-123-45", "cost": "240,00",
                         "per": "year", "ends": ENDS.isoformat(), "notice": 1, "notice_unit": "m", "renew_months": 12, "lead_days": 45, "note": "Deckung 3 Mio."})
check(r.status_code == 201, "#1925: a contract " + r.text[:300])
INS = r.json()
CB = months_add(ENDS, -1)
check(INS["cost"] == "240.00" and INS["monthly"] == "20.00" and INS["number"] == "P-123-45" and INS["note"] == "Deckung 3 Mio." and INS["cashflow"] == 1
      and INS["vat_pct"] is None and INS["archived"] == 0, f"#1925: the stored fields {INS}")
dl = INS["deadline"]
check(dl and dl["cancel_by"] == CB.isoformat() and dl["ends"] == ENDS.isoformat() and dl["days"] == (CB - T0).days and dl["warn"] and not dl["over"],
      f"#1925: last day to cancel = end minus one month, red from the lead time {dl}")
t = task(INS["task_id"])
check(t and t["list_id"] == INBOX and t["title"] == "Cancel or renew the contract: Betriebshaftpflicht" and t["due"] == CB.isoformat() and t["repeat"] == "FREQ=YEARLY"
      and t["reminders"] == "64800,0" and t["status"] == 0 and t["fam"].get("kind") == "contract" and t["fam"].get("office_agreement") == INS["id"]
      and t["fam"].get("cost") == 240.0 and t["fam"].get("per") == "year" and t["fam"].get("lead") == 45 and f"#office/agreements/{INS['id']}" in (t["content"] or ""),
      f"#1925: the deadline task in the inbox (fam like a family contract + office_agreement) {t}")
check(INS["task"] and INS["task"]["id"] == INS["task_id"] and not INS["task"]["done"], f"#1925: the task in the answer {INS.get('task')}")
row = sql("SELECT cost, number, note, name FROM office_agreements WHERE id=?", (INS["id"],))[0]
check(all(str(v).startswith("kenc1:") for v in row[:3]) and row[3] == "Betriebshaftpflicht", f"#1925: cost, number and note encrypted at rest {row}")
check("covered" in INS, "#1925: the field covered (part B, ast_covered) is there")
for bad, what in (({"kind": "spaceship", "name": "x"}, "kind"), ({"name": ""}, "name"), ({"name": "x", "per": "week"}, "per"), ({"name": "x", "cost": -1}, "cost"),
                  ({"name": "x", "cost": "abc"}, "cost text"), ({"name": "x", "notice_unit": "y"}, "notice_unit"), ({"name": "x", "ends": "2026-13-01"}, "date"),
                  ({"name": "x", "start": "2026-05-01", "ends": "2026-04-01"}, "end before start"), ({"name": "x", "vat_pct": "16"}, "vat"),
                  ({"name": "x", "renew_months": 500}, "renew"), ({"name": "x", "lead_days": -1}, "lead"), ({"name": "x", "cashflow": 5}, "cashflow")):
    check(A.post(B + AG, json=bad).status_code == 400, f"#1925: refused: {what}")
r = A.post(B + AG, json={"name": "  Lange  " + "x" * 400, "provider": "p" * 400})
check(r.status_code == 201 and len(r.json()["name"]) == 200 and len(r.json()["provider"]) == 200 and r.json()["task"] is None, "#1925: texts are cut; without an end no task " + r.text[:120])
check(A.delete(B + f"{AG}/{r.json()['id']}").ok, "#1925: delete the long one")

# rolling on: a passed last day to cancel moves to the next term; without renewal it is over
r = A.post(B + AG, json={"kind": "rent", "name": "Büromiete", "cost": 1200, "per": "month", "ends": D(-10), "notice": 0, "renew_months": 12, "lead_days": 30, "cashflow": 0})
RENT = r.json()
NEXT = months_add(T0 - timedelta(days=10), 12).isoformat()
check(r.status_code == 201 and RENT["ends"] == NEXT and RENT["deadline"]["cancel_by"] == NEXT and not RENT["deadline"]["over"], f"#1925: the term rolled on by 12 months {RENT.get('ends')} {RENT.get('deadline')}")
r = A.post(B + AG, json={"kind": "service", "name": "Alte Wartung", "ends": D(-5), "notice": 0, "renew_months": 0})
OLD = r.json()
check(r.status_code == 201 and OLD["deadline"]["over"] and OLD["task"] is None and OLD["ends"] == D(-5), f"#1925: without renewal a passed deadline stays over, no task {OLD.get('deadline')}")

# changes follow into the task
r = A.patch(B + f"{AG}/{INS['id']}", json={"name": "Betriebshaftpflicht neu", "lead_days": 10})
check(r.ok and r.json()["name"] == "Betriebshaftpflicht neu" and r.json()["provider"] == "Beispiel Versicherung AG", "#1925: patch keeps the other fields " + r.text[:160])
t = task(INS["task_id"])
check(t["id"] == INS["task_id"] and t["title"].endswith("Betriebshaftpflicht neu") and t["reminders"] == "14400,0" and t["fam"]["lead"] == 10 and t["fam"]["name"] == "Betriebshaftpflicht neu",
      f"#1925: the task follows name and lead {t}")
E2 = T0 + timedelta(days=100)
r = A.patch(B + f"{AG}/{INS['id']}", json={"ends": E2.isoformat(), "notice": 2, "notice_unit": "w"})
check(r.ok and task(INS["task_id"])["due"] == (E2 - timedelta(weeks=2)).isoformat() and r.json()["deadline"]["cancel_by"] == (E2 - timedelta(weeks=2)).isoformat(),
      "#1925: a new end + notice moves the task's due " + r.text[:200])
# switched off: the task ends; on again: a new one in a chosen list
LST = A.post(B + "/api/lists", json={"name": "Verträge Büro"}).json()["id"]
r = A.patch(B + f"{AG}/{INS['id']}", json={"task": 0})
t = task(INS["task_id"])
check(r.ok and r.json()["task_id"] is None and t["status"] == 2 and t["repeat"] == "" and t["deleted_at"] is None, f"#1925: off ends the task, never deletes {t}")
r = A.patch(B + f"{AG}/{INS['id']}", json={"task": 1, "list_id": LST})
T2 = r.json()["task_id"]
check(r.ok and T2 and T2 != INS["task_id"] and task(T2)["list_id"] == LST and task(T2)["status"] == 0, "#1925: on again = a new task in the chosen list " + r.text[:200])
# a deleted task comes back on the next save
sql("UPDATE tasks SET deleted_at=? WHERE id=?", ("2026-01-01T00:00:00Z", T2))
r = A.patch(B + f"{AG}/{INS['id']}", json={"provider": "Beispiel Versicherung SE"})
T3 = r.json()["task_id"]
check(r.ok and T3 and T3 != T2 and task(T3)["status"] == 0 and task(T3)["list_id"] == INBOX, f"#1925: a deleted task is made again (inbox) {T3}")
# a list the person may not write: refused; a stored task id never reaches another task
CL_LIST = Ca.post(B + "/api/lists", json={"name": "Carols Liste"}).json()["id"]
check(A.patch(B + f"{AG}/{INS['id']}", json={"task": 1, "list_id": CL_LIST}).status_code in (403, 404), "#1925: a list of another person is refused")
# 2.92.0 review: a list of another organisation (even one the admin may write) never takes the contract's deadline task
XL = A.post(B + "/api/lists", json={"name": "Fremde Org"}).json()["id"]
sql("UPDATE lists SET org_id=? WHERE id=?", (ORG2, XL))
r = A.patch(B + f"{AG}/{INS['id']}", json={"task": 1, "list_id": XL})
check(r.status_code in (400, 403, 404) and not sql("SELECT 1 FROM tasks WHERE list_id=?", (XL,)),
      f"#1925 review: a list of another organisation is refused {r.status_code} {r.text[:160]}")
check(all(x["id"] != XL for x in A.get(B + AG).json().get("lists", [])), "#1925 review: lists of another organisation are not offered")
PLAIN = A.post(B + "/api/tasks", json={"title": "Fremde Aufgabe", "list_id": INBOX, "due": D(3)}).json()["id"]
sql("UPDATE office_agreements SET task_id=? WHERE id=?", (PLAIN, RENT["id"]))
r = A.patch(B + f"{AG}/{RENT['id']}", json={"name": "Büromiete Hauptsitz"})
check(r.ok and task(PLAIN)["title"] == "Fremde Aufgabe" and task(PLAIN)["status"] == 0, "#1925: a task id of another task is never changed")
# archive / unarchive
r = A.patch(B + f"{AG}/{INS['id']}", json={"archived": 1})
check(r.ok and r.json()["archived"] == 1 and task(T3)["status"] == 2 and task(T3)["repeat"] == "", "#1925: archiving ends the task")
check(all(a["id"] != INS["id"] for a in A.get(B + AG).json()["items"]) and any(a["id"] == INS["id"] for a in A.get(B + AG + "?archived=1").json()["items"]), "#1925: archived only with ?archived=1")
r = A.patch(B + f"{AG}/{INS['id']}", json={"archived": 0})
T4 = r.json()["task_id"]
check(r.ok and T4 and T4 != T3 and task(T4)["status"] == 0, "#1925: unarchiving brings a new task " + r.text[:120])
# delete (soft) + restore
r = A.delete(B + f"{AG}/{INS['id']}")
check(r.ok and A.get(B + f"{AG}/{INS['id']}").status_code == 404 and task(T4)["status"] == 2 and task(T4)["deleted_at"] is None, "#1925: delete: gone, task ended not deleted")
r = A.post(B + f"{AG}/{INS['id']}/restore", json={})
check(r.ok and r.json()["archived"] == 0 and r.json()["task"] and r.json()["task_id"] != T4 and A.get(B + f"{AG}/{INS['id']}").ok, "#1925: restore brings it and a task back " + r.text[:160])
check(A.post(B + f"{AG}/{INS['id']}/restore", json={}).status_code == 409, "#1925: restoring a contract that is there: 409")

# ---------------------------------------------------------------- the cash flow
r = A.post(B + AG, json={"kind": "leasing", "name": "Kamera-Leasing", "cost": 100, "per": "month", "vat_pct": "19", "start": M0 + "-05", "ends": D(400),
                         "notice": 1, "notice_unit": "m", "renew_months": 0})
LEA = r.json()
check(r.status_code == 201 and LEA["gross"] == "119.00" and LEA["vat_pct"] == "19", "#1925: leasing with VAT " + r.text[:160])
cf = A.get(B + O + f"/cashflow?from={M0}&months=12").json()
ag = [e for e in cf["entries"] if e["kind"] == "agreement"]
lea = [e for e in ag if e["agreement_id"] == LEA["id"]]
ins = [e for e in ag if e["agreement_id"] == INS["id"]]
check(len(lea) == 12 and {e["amount"] for e in lea} == {"119.00"} and lea[0]["date"] == M0 + "-05" and lea[0]["state"] == ("actual" if M0 + "-05" <= TODAY else "plan"),
      f"#1925: monthly leasing gross, every month once {[(e['date'], e['amount']) for e in lea]}")
check(len(ins) == 1 and ins[0]["amount"] == "240.00" and ins[0]["dir"] == "out", f"#1925: the yearly insurance exactly once in 12 months {ins}")
check(not [e for e in ag if e["agreement_id"] in (RENT["id"], OLD["id"])], "#1925: cashflow off / without a cost: not in the cash flow")
cfn = A.get(B + O + f"/cashflow?from={M0}&months=3&basis=net").json()
check({e["amount"] for e in cfn["entries"] if e["kind"] == "agreement" and e["agreement_id"] == LEA["id"]} == {"100.00"}, "#1925: net basis = the contribution without VAT")
fx = A.get(B + O + "/fixed-costs").json()
check(fx["items"] == [] and {a["id"] for a in fx["agreements"]} == {INS["id"], LEA["id"]} and sql("SELECT COUNT(*) FROM office_fixed_costs")[0][0] == 0,
      f"#1925: read-only rows in the fixed costs, no copy {fx}")
A.patch(B + f"{AG}/{LEA['id']}", json={"cashflow": 0})
check(not [e for e in A.get(B + O + f"/cashflow?from={M0}&months=3").json()["entries"] if e.get("agreement_id") == LEA["id"]], "#1925: switched off: gone from the cash flow")

# ---------------------------------------------------------------- the document
r = A.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files=[("files", ("police.txt", b"Police P-123-45 Beispiel Versicherung", "text/plain"))])
check(r.status_code == 201 and r.json()["ids"], "setup: a document in Alpha " + r.text[:160])
DOC = r.json()["ids"][0] if r.ok and r.json().get("ids") else 0
r = A.patch(B + f"{AG}/{INS['id']}", json={"doc_node_id": DOC})
check(r.ok and r.json()["doc"] and r.json()["doc"]["id"] == DOC and r.json()["doc"]["name"] == "police.txt", "#1925: the contract document " + r.text[:200])
r = Ca.post(B + "/api/docs", data={"ws": f"org:{ORG2}"}, files=[("files", ("fremd.txt", b"Fremd", "text/plain"))])
DOC2 = r.json()["ids"][0] if r.ok and r.json().get("ids") else 0
check(A.patch(B + f"{AG}/{INS['id']}", json={"doc_node_id": DOC2}).status_code == 404, "#1925: a document of another organisation: 404")
r = A.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("privat.txt", b"Privat", "text/plain"))])
DOCP = r.json()["ids"][0] if r.ok and r.json().get("ids") else 0
check(A.patch(B + f"{AG}/{INS['id']}", json={"doc_node_id": DOCP}).status_code == 404, "#1925: a private document is not one of the office (organisation): 404")
check(A.patch(B + f"{AG}/{INS['id']}", json={"doc_node_id": None}).json()["doc"] is None, "#1925: the document removed")

# ---------------------------------------------------------------- rights
check(Bo.get(B + AG).status_code == 403 and Bo.post(B + AG, json={"name": "x"}).status_code == 403 and Bo.get(B + f"{AG}/{INS['id']}").status_code == 403,
      "#1925: a member: 403 (contributions are for admins)")
check(Bo.get(B + O + "/fixed-costs").status_code == 403, "#1925: a member does not see them in the fixed costs either")
check(all(a["id"] != INS["id"] for a in Ca.get(B + AG).json()["items"]), "#1925: another organisation sees none")
for m, u, kw in (("get", f"{AG}/{INS['id']}", {}), ("patch", f"{AG}/{INS['id']}", {"json": {"name": "x"}}), ("delete", f"{AG}/{INS['id']}", {}),
                 ("post", f"{AG}/{INS['id']}/restore", {"json": {}})):
    check(getattr(Ca, m)(B + u, **kw).status_code == 404, f"#1925: another organisation {m} {u}: 404")
check(not [e for e in Ca.get(B + O + f"/cashflow?from={M0}&months=12").json()["entries"] if e["kind"] == "agreement"], "#1925: nor in its cash flow")
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "watcher", "display_name": "Watcher"})
assert r.status_code == 201, r.text
WAT, WH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
check(requests.get(B + AG, headers=WH).status_code == 403 and requests.post(B + AG, headers=WH, json={"name": "x"}).status_code == 403, "#1925: an agent token: 403")

# ---------------------------------------------------------------- contracts in view (#1359): the event for an office contract
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "quiet", "display_name": "Quiet"})
QH = {"Authorization": "Bearer " + r.json()["token"]}
sql("UPDATE agents SET org_id=? WHERE user_id IN (?, ?)", (ORG, WAT, r.json()["id"]))  # agents of Alpha (the list belongs to Alpha)
VLIST = A.post(B + "/api/lists", json={"name": "Fristen"}).json()["id"]
r = A.put(B + f"/api/lists/{VLIST}/members", json={"user_id": WAT, "role": "edit"})
check(r.ok, "setup: the list shared with the agent " + r.text[:200])
r = A.post(B + AG, json={"kind": "service", "name": "Wartungsvertrag Server", "provider": "Beispiel IT", "cost": 50, "per": "month", "ends": D(20), "notice": 0,
                         "renew_months": 12, "lead_days": 30, "list_id": VLIST})
SRV = r.json()
check(r.status_code == 201 and task(SRV["task_id"])["list_id"] == VLIST, "#1925: a deadline task in the shared list " + r.text[:160])


def events(h):
    r = requests.get(V + "/agent/events?since=0&limit=500", headers=h)
    return [e for e in r.json().get("data", []) if e["event"] == "contract_notice"] if r.ok else []


ev = until(lambda: events(WH))
d = ev[0]["data"] if ev else {}
check(ev and d.get("task_id") == SRV["task_id"] and d.get("name") == "Wartungsvertrag Server" and d.get("due") == D(20) and d.get("cost") == 50.0,
      f"#1925/#1359: contract_notice for the office contract (no module At home) {d}")
check(not events(QH), "#1925/#1359: an agent without the list hears nothing")
check(len(events(WH)) == 1, "#1925/#1359: once")

# ---------------------------------------------------------------- a person without organisation (personal office)
check(Do.get(B + O + "/settings").json().get("role") == "admin", "#1925: a person without organisation is admin of their own office")
j = Do.get(B + AG).json()
check(j["items"] == [] and j["doc_ws"] == "private", f"#1925: personal office: empty, documents space private {j.get('doc_ws')}")
r = Do.post(B + AG, json={"kind": "insurance", "name": "Berufshaftpflicht", "cost": 30, "per": "month", "ends": D(120), "notice": 3, "notice_unit": "m", "lead_days": 14})
PD = r.json()
check(r.status_code == 201 and PD["task"] and PD["deadline"]["cancel_by"] == months_add(T0 + timedelta(days=120), -3).isoformat(), "#1925: personal office: a contract with a task " + r.text[:200])
r = Do.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("bhv.txt", b"Police Dora", "text/plain"))])
DD = r.json()["ids"][0] if r.ok and r.json().get("ids") else 0
check((Do.patch(B + f"{AG}/{PD['id']}", json={"doc_node_id": DD}).json().get("doc") or {}).get("id") == DD, "#1925: personal office: a private document is the office's")
check(Do.patch(B + f"{AG}/{PD['id']}", json={"doc_node_id": DOC}).status_code == 404, "#1925: personal office: a document of an organisation: 404")
pcf = Do.get(B + O + f"/cashflow?from={M0}&months=3").json()
check(len([e for e in pcf["entries"] if e["kind"] == "agreement"]) >= 2, "#1925: personal office: the contributions in the cash flow")
check(Er.get(B + AG).json()["items"] == [] and Er.get(B + f"{AG}/{PD['id']}").status_code == 404 and Er.patch(B + f"{AG}/{PD['id']}", json={"name": "x"}).status_code == 404,
      "#1925: personal office: another person sees and reaches nothing")
check(all(a["id"] != PD["id"] for a in A.get(B + AG).json()["items"]) and A.get(B + f"{AG}/{PD['id']}").status_code == 404, "#1925: nor does an organisation")
r = Do.delete(B + f"{AG}/{PD['id']}")
check(r.ok and Do.post(B + f"{AG}/{PD['id']}/restore", json={}).ok, "#1925: personal office: delete + restore")
check(Do.patch(B + f"{AG}/{PD['id']}", json={"archived": 1}).json()["archived"] == 1, "#1925: personal office: archive")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
