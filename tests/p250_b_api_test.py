#!/usr/bin/env python3
"""2.50.0 API tests, part B (office: sales pipeline + business figures), own container (start.sh, org encryption on).
Invented companies, people and figures only.
 - #1196: deals with stage presets of the probability (20 / 50 / 100 / 0, a value set by hand stays), sums (open,
   weighted, forecast per month, without a date apart); a quotation made from a deal (client taken over, stage -> quotation
   sent), the quotation accepted -> the deal is won, declined -> the deal stays; a project from a won deal (list of the
   client in the organisation); edit answers "before" (undo), delete + restore; value / contact / note encrypted at rest;
   foreign clients / lists / quotations refused
 - #1197: revenue received (net share of a payment) this month and this year, open invoices, budget and margin per client
   (invoiced net minus purchases), the pipeline's weighted value, three months of the cash flow
 - rights: a member gets 403, another organisation sees nothing and reaches nothing (404); a person without organisation
   has an own pipeline that nobody else sees
usage: p250_b_api_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time
from decimal import Decimal

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def ym_add(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
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
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo, Ca, Do, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
O = "/api/office"
D = O + "/docs"
P = O + "/deals"
TODAY = testclock.today().isoformat()
M0 = TODAY[:7]
M1, M2 = ym_add(M0, 1), ym_add(M0, 2)
A.put(B + O + "/settings", json={"company_fields": {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
                                                     "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "budget_h": 40}).json()["id"]
CL2 = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG"}).json()["id"]

# ---------------------------------------------------------------- #1196 deals
j = A.get(B + P).json()
# 2.94.0 (#1930): the stage lead (10 %) before inquiry
check(j["items"] == [] and j["stages"] == ["lead", "inquiry", "offer", "won", "lost"] and j["probabilities"] == {"lead": 10, "inquiry": 20, "offer": 50, "won": 100, "lost": 0}
      and j["summary"]["open"] == "0.00", f"#1196: the empty pipeline with its stages {j}")
r = A.post(B + P, json={"title": "Imagefilm Frühjahr", "client_id": CL, "value": "10000", "expected_date": M1 + "-10", "note": "Erstes Gespräch"})
check(r.status_code == 201 and r.json()["stage"] == "inquiry" and r.json()["probability"] == 20 and r.json()["client_name"] == "Kunde Eins GmbH" and r.json()["weighted"] == "2000.00",
      "#1196: a new inquiry gets 20 % " + r.text[:200])
D1 = r.json()["id"]
r = A.post(B + P, json={"title": "Werbespot", "contact": "Frau Beispiel", "value": 5000, "stage": "offer"})
check(r.status_code == 201 and r.json()["probability"] == 50 and r.json()["contact"] == "Frau Beispiel", "#1196: a deal in the stage quotation sent gets 50 %")
D2 = r.json()["id"]
r = A.post(B + P, json={"title": "Messefilm", "value": 2000, "probability": 70})
D3 = r.json()["id"]
check(r.json()["probability"] == 70, "#1196: a probability given by hand")
check(A.post(B + P, json={"title": ""}).status_code == 400, "#1196: a name is required")
check(A.post(B + P, json={"title": "x", "value": -1}).status_code == 400 and A.post(B + P, json={"title": "x", "stage": "maybe"}).status_code == 400
      and A.post(B + P, json={"title": "x", "probability": 150}).status_code == 400 and A.post(B + P, json={"title": "x", "expected_date": "2026-13-01"}).status_code == 400,
      "#1196: a negative value, unknown stage, probability over 100, a wrong date are refused")
check(A.post(B + P, json={"title": "x", "client_id": CL2}).status_code == 400, "#1196: a client of another organisation is refused")
s = A.get(B + P).json()["summary"]
fc = {f["month"]: f["weighted"] for f in s["forecast"]}
check(s["open"] == "17000.00" and s["weighted"] == "5900.00" and s["count_open"] == 3 and s["undated"] == "3900.00" and fc.get(M1) == "2000.00"
      and [f["month"] for f in s["forecast"]][:2] == [M0, M1] and [f for f in s["forecast"] if f["next"]][0]["month"] == M1,
      f"#1196: open, weighted, forecast per month (next month marked), without a date apart {s}")
# stage changes: preset follows unless changed by hand; before for the undo
r = A.patch(B + f"{P}/{D3}", json={"stage": "offer"})
check(r.ok and r.json()["probability"] == 70 and r.json()["before"] == {"stage": "inquiry"}, "#1196: a probability set by hand stays on a stage change " + r.text[:160])
r = A.patch(B + f"{P}/{D3}", json={"stage": "lost", "lost_reason": "Budget gestrichen"})
check(r.ok and r.json()["probability"] == 0 and r.json()["lost_reason"] == "Budget gestrichen" and r.json()["before"]["probability"] == 70, "#1196: lost = 0 % with its reason")
r = A.patch(B + f"{P}/{D3}", json=r.json()["before"])
check(r.ok and r.json()["stage"] == "offer" and r.json()["probability"] == 70 and r.json()["lost_reason"] == "", "#1196: the undo patches the old values back")
row = sql("SELECT value, contact, note FROM office_deals WHERE id=?", (D2,))[0]
check(all(str(x).startswith("kenc1:") for x in row[:2]) and str(sql("SELECT note FROM office_deals WHERE id=?", (D1,))[0][0]).startswith("kenc1:"),
      f"#1196: value, contact, note encrypted at rest {row}")
# quotation from the deal
r = A.post(B + f"{P}/{D1}/offer")
check(r.status_code == 201 and r.json()["deal"]["stage"] == "offer" and r.json()["deal"]["probability"] == 50 and r.json()["deal"]["offer_id"] == r.json()["doc_id"],
      "#1196: a quotation from the inquiry moves it to quotation sent " + r.text[:200])
Q = r.json()["doc_id"]
q = A.get(B + f"{D}/{Q}").json()
check(q["kind"] == "offer" and q["client_id"] == CL and q["project_title"] == "Imagefilm Frühjahr" and q["status"] == "draft", "#1196: the quotation takes over client and title")
check(A.post(B + f"{P}/{D1}/offer").status_code == 409, "#1196: a second quotation for the same deal is refused")
A.patch(B + f"{D}/{Q}", json={"service_from": TODAY, "service_to": TODAY})
A.put(B + f"{D}/{Q}/items", json={"items": [{"kind": "service", "title": "Dreh", "qty": 2, "unit": "day", "rate": 1000, "cost": 300, "intext": "extern"}]})
A.post(B + f"{D}/{Q}/status", json={"status": "sent"})
check(A.get(B + P).json()["items"][0]["offer_status"] in ("sent", ""), "#1196: the card knows the quotation's status")
r = A.post(B + f"{D}/{Q}/status", json={"status": "accepted"})
check(r.ok, "the quotation accepted " + r.text[:120])
d1 = [x for x in A.get(B + P).json()["items"] if x["id"] == D1][0]
check(d1["stage"] == "won" and d1["probability"] == 100 and d1["offer_status"] == "accepted", f"#1196: an accepted quotation wins its deal {d1}")
# declined quotation: the deal stays
r = A.post(B + f"{P}/{D2}/offer")
Q2 = r.json()["doc_id"]
for st in ("sent", "declined"):
    A.post(B + f"{D}/{Q2}/status", json={"status": st})
d2 = [x for x in A.get(B + P).json()["items"] if x["id"] == D2][0]
check(d2["stage"] == "offer" and d2["offer_status"] == "declined", f"#1196: a declined quotation leaves the deal where it is {d2}")
# project from the won deal
r = A.post(B + f"{P}/{D1}/project")
check(r.status_code == 201 and r.json()["deal"]["list_id"] == r.json()["list_id"], "#1196: a project from the won deal " + r.text[:200])
LID = r.json()["list_id"]
lr = sql("SELECT org_id, client_id, name FROM lists WHERE id=?", (LID,))[0]
check(lr[0] == ORG and lr[1] == CL and lr[2] == "Imagefilm Frühjahr", f"#1196: the project is in the organisation with the client {lr}")
check(A.post(B + f"{P}/{D1}/project").status_code == 409, "#1196: a second project is refused")
# foreign references
QF = Ca.post(B + D, json={"project_title": "Fremd"}).json()["id"]
check(A.patch(B + f"{P}/{D2}", json={"offer_id": QF}).status_code == 400, "#1196: a quotation of another organisation cannot be bound")
LF = Ca.post(B + "/api/lists", json={"name": "Fremdprojekt", "org_id": ORG2}).json().get("id")
check(LF is None or A.patch(B + f"{P}/{D2}", json={"list_id": LF}).status_code == 400, "#1196: a list of another organisation cannot be bound")
# delete + restore
check(A.delete(B + f"{P}/{D3}").ok and not any(x["id"] == D3 for x in A.get(B + P).json()["items"]), "#1196: deleted = gone from the pipeline")
check(A.post(B + f"{P}/{D3}/restore").ok and any(x["id"] == D3 for x in A.get(B + P).json()["items"]), "#1196: restore brings it back (undo)")
check(A.post(B + f"{P}/{D3}/restore").status_code == 404, "#1196: restoring a live deal is 404")
# rights
check(Bo.get(B + P).status_code == 403 and Bo.post(B + P, json={"title": "x"}).status_code == 403 and Bo.patch(B + f"{P}/{D1}", json={"title": "x"}).status_code == 403,
      "#1196: a member gets 403")
check(Ca.get(B + P).json()["items"] == [], "#1196: another organisation sees no deals")
check(Ca.patch(B + f"{P}/{D1}", json={"title": "x"}).status_code == 404 and Ca.delete(B + f"{P}/{D1}").status_code == 404
      and Ca.post(B + f"{P}/{D1}/offer").status_code == 404 and Ca.post(B + f"{P}/{D1}/project").status_code == 404, "#1196: another organisation reaches nothing (404)")

# ---------------------------------------------------------------- #1197 figures
INV = A.post(B + f"{D}/{Q}/invoice").json()
A.put(B + f"{D}/{INV['id']}/items", json={"items": [{"kind": "service", "title": "Dreh Teil 1", "qty": 1, "unit": "day", "rate": 1000}]})
A.patch(B + f"/api/clients/{CL}", json={"street": "Weg 2", "zip": "10115", "city": "Berlin"})  # 2.97.0 B (#1951): a draft's recipient comes from its client (a given one is ignored)
A.patch(B + f"{D}/{INV['id']}", json={"recipient": {"name": "Kunde Eins GmbH", "lines": ["Weg 2", "10115 Berlin"]}, "service_from": TODAY, "service_to": TODAY})
r = A.post(B + f"{D}/{INV['id']}/finalize")
check(r.ok, "the invoice is finalised " + r.text[:200])
T = r.json()["totals"]
check(A.post(B + f"{D}/{INV['id']}/payments", json={"date": TODAY, "amount": 500}).status_code == 201, "a part payment")
k = A.get(B + O + "/kpi")
check(k.ok, "#1197: the figures " + k.text[:200])
k = k.json()
net500 = (Decimal(500) * Decimal(str(T["net"])) / Decimal(str(T["gross"]))).quantize(Decimal("0.01"))
check(k["revenue"]["month"] == str(net500) and k["revenue"]["year"] == str(net500) and k["revenue"]["year_prev"] == "0.00" and k["revenue"]["to_date"]
      and [m for m in k["revenue"]["months"] if m["month"] == M0][0]["amount"] == str(net500) and len(k["revenue"]["months"]) == 12,
      f"#1197: revenue = net share of the payment, this month and this year {k['revenue']['month']} {net500}")
openg = (Decimal(str(T["gross"])) - 500).quantize(Decimal("0.01"))
check(k["invoices"]["open"] == {"count": 1, "amount": str(openg)} and k["invoices"]["overdue"]["count"] in (0, 1), f"#1197: open invoices {k['invoices']}")
c1 = [c for c in k["clients"] if c["id"] == CL]
check(c1 and c1[0]["invoiced"] == "%.2f" % float(T["net"]) and c1[0]["budget_h"] == 40 and c1[0]["level"] in ("ok", "none")
      and Decimal(c1[0]["margin"]) == Decimal(c1[0]["invoiced"]) - Decimal(c1[0]["costs"]) and Decimal(c1[0]["costs"]) == Decimal("600.00"),
      f"#1197: per client invoiced, costs (purchase of the accepted quotation), margin, budget {c1}")
check(not any(c["id"] == CL2 for c in k["clients"]), "#1197: no client of another organisation")
check(k["pipeline"]["weighted"] == A.get(B + P).json()["summary"]["weighted"] and len(k["cashflow"]) == 3 and k["cashflow"][0]["month"] == M0, "#1197: pipeline and cash flow")
cf = A.get(B + O + f"/cashflow?from={M0}&months=3").json()
check([x["balance"] for x in k["cashflow"]] == [x["balance"] for x in cf["rows"]], "#1197: the cash flow figures are those of the cash flow tab")
check(A.get(B + O + "/kpi?year=1999").status_code == 400 and A.get(B + O + f"/kpi?year={int(TODAY[:4]) - 1}").json()["revenue"]["to_date"] is False, "#1197: the year parameter")
check(Bo.get(B + O + "/kpi").status_code == 403, "#1197: a member gets 403")
kc = Ca.get(B + O + "/kpi").json()
check(kc["revenue"]["year"] == "0.00" and kc["invoices"]["open"]["count"] == 0 and kc["pipeline"]["count_open"] == 0, "#1197: another organisation sees its own (empty) figures")

# ---------------------------------------------------------------- personal office (a person without organisation)
CLP = Do.post(B + "/api/clients", json={"name": "Privatkunde Eins"}).json()["id"]
r = Do.post(B + P, json={"title": "Hochzeitsfilm", "client_id": CLP, "value": 1500})
check(r.status_code == 201, "#1196: a deal in the personal office " + r.text[:160])
DP = r.json()["id"]
check(Do.post(B + P, json={"title": "x", "client_id": CL}).status_code == 400, "#1196: a client of an organisation is refused in the personal office")
r = Do.patch(B + f"{P}/{DP}", json={"stage": "won"})
r = Do.post(B + f"{P}/{DP}/project")
check(r.status_code == 201 and tuple(sql("SELECT org_id, client_id FROM lists WHERE id=?", (r.json()["list_id"],))[0]) == (None, CLP), "#1196: its project is private with the client")
check(Er.get(B + P).json()["items"] == [] and Er.patch(B + f"{P}/{DP}", json={"title": "x"}).status_code == 404, "#1196: another person sees and reaches none of it")
check(not any(x["id"] == DP for x in A.get(B + P).json()["items"]), "#1196: nor does an organisation")
kd = Do.get(B + O + "/kpi").json()
check(kd["pipeline"]["won"] == "1500.00" and kd["pipeline"]["count_open"] == 0, "#1197: figures of the personal office " + str(kd["pipeline"]))

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
