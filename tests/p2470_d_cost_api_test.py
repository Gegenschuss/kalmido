#!/usr/bin/env python3
"""2.47.0 API tests, part D (quotations: purchase and producing), own container (start.sh, mode workspaces, org
encryption on). Invented companies and figures only.
 - #1645: producing / raw data switched per quotation: a new quotation takes both from the office default, the switches
   of the quotation decide (default off + quotation on and the other way round), the flags of a service are always taken
   over, a framework contract always presets raw data, the invoice from a quotation follows its switch; the start
   migration fills producing_on of older documents (flagged position = 1, else the office default) and their sums stay
 - #1649: a new position of a service takes the purchase of the service's freelancer role (also when a member adds it),
   a changed role price only reaches new positions; the surplus per position and its sum only for admins (members get
   neither the purchase nor the surplus); nothing of it in the print model; a percent position (artists' social
   insurance) = rate % of the positions marked extern, an invoice from the quotation makes it a plain amount; the purchase
   of an accepted quotation is written to office_purchases (date = start of the period of service, accepted_at = today,
   encrypted), written anew when the accepted quotation changes, removed when it leaves "accepted"
usage: p2470_d_cost_api_test.py <datadir>"""
import base64
import datetime
import json
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def restart():
    subprocess.run(["docker", "restart", CT], capture_output=True)
    for _ in range(80):
        try:
            if requests.get(B + "/api/health", timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo = sess("bob")
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
O = "/api/office"
D = O + "/docs"
TODAY = testclock.today().isoformat()
Y = testclock.today().year

# ---------------------------------------------------------------- #1645 producing / raw data per quotation
st = A.get(B + O + "/settings").json()["settings"]
check(st.get("producing_on") == 0 and st.get("raw_on") == 0, f"a new organisation starts with both defaults off {st.get('producing_on')} {st.get('raw_on')}")
SV = A.post(B + O + "/services", json={"name_de": "Dreh", "daily_rate": 1000, "producing": 1, "raw_fee": 1}).json()["id"]
CTR = A.post(B + O + "/contracts", json={"name": "Rahmenvertrag", "raw_included": 1}).json()["id"]
Q1 = A.post(B + D, json={"project_title": "Film eins"}).json()
check(Q1.get("producing_on") == 0 and Q1.get("raw_mode") == "none", f"#1645 default off: the quotation starts off {Q1.get('producing_on')} {Q1.get('raw_mode')}")
j = A.put(B + f"{D}/{Q1['id']}/items", json={"items": [{"kind": "service", "service_id": SV, "qty": 6}]}).json()
check([x["kind"] for x in j["totals"]["lines"]] == ["item"] and j["totals"]["net"] == 6000 and j["items"][0]["producing"] == 1 and j["items"][0]["raw_fee"] == 1,
      f"#1645 off: no automatic line, the flags of the service are kept {[x['kind'] for x in j['totals']['lines']]} {j['items'][0].get('producing')}")
j = A.patch(B + f"{D}/{Q1['id']}", json={"producing_on": 1}).json()
check(j["producing_on"] == 1 and [x["kind"] for x in j["totals"]["lines"]] == ["item", "producing"] and j["totals"]["net"] == 7200,
      f"#1645 default off, quotation on: producing 2 days x 600 {j['totals']['net']}")
j = A.patch(B + f"{D}/{Q1['id']}", json={"raw_mode": "optional"}).json()
check([x["kind"] for x in j["totals"]["lines"]] == ["item", "producing", "raw"] and j["totals"]["net_incl_raw"] == 8700, "#1645: raw data switched on in the quotation " + str(j["totals"].get("net_incl_raw")))
j = A.patch(B + f"{D}/{Q1['id']}", json={"contract_id": CTR}).json()
check(j["raw_mode"] == "included", "#1645: the framework contract presets raw data although the default is off " + j["raw_mode"])
r = A.post(B + f"{D}/{Q1['id']}/invoice")
check(r.status_code == 201 and [x["title"] for x in r.json()["items"]][:2] == ["Dreh", "Producing"], "#1645: the invoice from the quotation has its producing line " + r.text[:160])
A.put(B + O + "/settings", json={"producing_on": 1, "raw_on": 1})
Q2 = A.post(B + D, json={"project_title": "Film zwei"}).json()
# 2.113.1 (#2251): without an industry pack offering "share by amount" a new quotation starts without producing
check(Q2.get("producing_on") == 0 and Q2.get("raw_mode") == "optional", "#2251: without a pack option the quotation starts without producing")
A.put(B + f"{D}/{Q2['id']}/items", json={"items": [{"kind": "service", "service_id": SV, "qty": 6}]})
j = A.patch(B + f"{D}/{Q2['id']}", json={"producing_on": 0, "raw_mode": "none"}).json()
check([x["kind"] for x in j["totals"]["lines"]] == ["item"] and j["totals"]["net"] == 6000 and j["items"][0]["producing"] == 1,
      f"#1645 default on, quotation off: no producing / raw data, flags kept {[x['kind'] for x in j['totals']['lines']]}")
r = A.post(B + f"{D}/{Q2['id']}/invoice")
check(r.status_code == 201 and [x["title"] for x in r.json()["items"]] == ["Dreh"], "#1645: the invoice from a quotation switched off has no producing line " + r.text[:160])
# the start migration: documents of 2.46 (producing_on NULL) keep how they compute
A.put(B + O + "/settings", json={"producing_on": 0})
Q3 = A.post(B + D, json={"project_title": "Ohne Producing"}).json()
A.put(B + f"{D}/{Q3['id']}/items", json={"items": [{"kind": "service", "title": "Schnitt", "qty": 2, "rate": 500}]})
Q4 = A.post(B + D, json={"project_title": "Alt mit Producing", "producing_on": 1}).json()
A.put(B + f"{D}/{Q4['id']}/items", json={"items": [{"kind": "service", "service_id": SV, "qty": 6}]})
net4 = A.get(B + f"{D}/{Q4['id']}").json()["totals"]["net"]
sql("UPDATE office_docs SET producing_on=NULL WHERE id IN (?, ?)", (Q3["id"], Q4["id"]))
j = A.get(B + f"{D}/{Q4['id']}").json()
check(j.get("producing_on") is None and j["totals"]["net"] == net4 == 7200, f"#1645: a row of 2.46 (NULL) computes as before {j.get('producing_on')} {j['totals']['net']}")
restart()
A, Bo = sess("alice"), sess("bob")
got = dict(sql("SELECT id, producing_on FROM office_docs WHERE id IN (?, ?)", (Q3["id"], Q4["id"])))
check(got.get(Q4["id"]) == 1 and got.get(Q3["id"]) == 0, f"#1645 migration: flagged position = 1, else the office default (off) {got}")
j = A.put(B + f"{D}/{Q4['id']}/items", json={"items": [{"id": i["id"], **{k: i[k] for k in ("kind", "service_id", "title", "qty", "unit", "rate", "producing", "raw_fee")}} for i in A.get(B + f"{D}/{Q4['id']}").json()["items"]]}).json()
check(j["totals"]["net"] == 7200, "#1645 migration: the sum of the older document stays " + str(j["totals"]["net"]))
sql("UPDATE office_docs SET producing_on=NULL WHERE id=?", (Q3["id"],))
A.put(B + O + "/settings", json={"producing_on": 1})
restart()
A, Bo = sess("alice"), sess("bob")
check(sql("SELECT producing_on FROM office_docs WHERE id=?", (Q3["id"],))[0][0] == 1, "#1645 migration: without flags the office default (on)")
A.put(B + O + "/settings", json={"producing_on": 0, "raw_on": 0})

# ---------------------------------------------------------------- #1649 purchase from the role, surplus per position
ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
sql("INSERT INTO office_roles(org_id, kind, name_de, name_en, costs, intext, created_at, updated_at) VALUES(?, 'freelancer', 'Cutter', 'Editor', ?, 'extern', ?, ?)",
    (ORG, json.dumps({"day": 400, "hour": 55}), ts, ts))
ROLE = sql("SELECT id FROM office_roles WHERE org_id=? AND name_de='Cutter'", (ORG,))[0][0]
SVC = A.post(B + O + "/services", json={"name_de": "Schnitt", "daily_rate": 600, "hourly_rate": 80, "intext": "extern"}).json()["id"]
sql("UPDATE office_services SET role_id=? WHERE id=?", (ROLE, SVC))
SVI = A.post(B + O + "/services", json={"name_de": "Regie", "daily_rate": 900, "intext": "intern"}).json()["id"]
r = A.post(B + O + "/services", json={"name_de": "Künstlersozialkasse", "unit": "percent", "daily_rate": 5})
check(r.ok, "#1649: a service of unit percent " + r.text[:160])
SVK = r.json()["id"]
Q = A.post(B + D, json={"project_title": "Imagefilm"}).json()
j = A.put(B + f"{D}/{Q['id']}/items", json={"items": [{"kind": "service", "service_id": SVC, "qty": 3}, {"kind": "service", "service_id": SVC, "qty": 4, "unit": "hour"},
                                                       {"kind": "service", "service_id": SVI, "qty": 2}]}).json()
its = j["items"]
check([i["cost"] for i in its] == [400, 55, 0], f"#1649: a new position takes the purchase of the role per unit {[i.get('cost') for i in its]}")
check(its[0]["margin"] == 1800 - 1200 and its[1]["margin"] == 320 - 220 and its[2]["margin"] == 1800 and j["items_margin"] == 600 + 100 + 1800,
      f"#1649: surplus per position and sum for the admin {[i.get('margin') for i in its]} {j.get('items_margin')}")
# a member adds a position: the server sets the purchase, the member does not see it
bj = Bo.get(B + f"{D}/{Q['id']}").json()
body = [{k: v for k, v in i.items() if k in ("id", "kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "raw_fee", "producing", "intext", "discountable")} for i in bj["items"]]
r = Bo.put(B + f"{D}/{Q['id']}/items", json={"items": body + [{"kind": "service", "service_id": SVC, "qty": 1}]})
check(r.ok, "#1649: a member adds a position " + r.text[:160])
bj = r.json()
check(all("cost" not in i and "margin" not in i for i in bj["items"]) and "items_margin" not in bj and "costs" not in bj["totals"] and "margin" not in bj["totals"],
      "#1649: a member gets no purchase, no surplus (fields absent)")
aj = A.get(B + f"{D}/{Q['id']}").json()
check([i["cost"] for i in aj["items"]] == [400, 55, 0, 400], f"#1649: the member's position has the role's purchase, the others kept theirs {[i.get('cost') for i in aj['items']]}")
# the role price changes: only new positions
sql("UPDATE office_roles SET costs=? WHERE id=?", (json.dumps({"day": 450, "hour": 60}), ROLE))
body = [{k: v for k, v in i.items() if k in ("id", "kind", "service_id", "title", "qty", "unit", "rate", "tax", "intext", "cost")} for i in aj["items"]]
j = A.put(B + f"{D}/{Q['id']}/items", json={"items": body + [{"kind": "service", "service_id": SVC, "qty": 1}]}).json()
check([i["cost"] for i in j["items"]] == [400, 55, 0, 400, 450], f"#1649: a changed role price reaches only new positions {[i.get('cost') for i in j['items']]}")
body = [{k: v for k, v in i.items() if k in ("id", "kind", "service_id", "title", "qty", "unit", "rate", "tax", "intext", "cost")} for i in j["items"]]
body[0]["cost"] = 380
j = A.put(B + f"{D}/{Q['id']}/items", json={"items": body}).json()
check(j["items"][0]["cost"] == 380 and j["items"][0]["margin"] == 1800 - 1140, "#1649: the admin changes the purchase of one position")
# the print model carries no purchase / surplus per line; a member gets no internal figures at all
rd = A.get(B + f"{D}/{Q['id']}/render").json()
check(all("cost" not in ln and "margin" not in ln for ln in rd["lines"]), "#1649: no purchase / surplus in the lines of the print model")
rb = Bo.get(B + f"{D}/{Q['id']}/render").json()
check(rb.get("internal") is None and "380" not in json.dumps(rb["lines"]), "#1649: the member's print model has no internal figures")

# ---------------------------------------------------------------- #1649 percent position (artists' social insurance)
QK = A.post(B + D, json={"project_title": "KSK"}).json()
j = A.put(B + f"{D}/{QK['id']}/items", json={"items": [{"kind": "service", "service_id": SVC, "qty": 2, "rate": 500}, {"kind": "service", "service_id": SVI, "qty": 3, "rate": 100},
                                                        {"kind": "service", "service_id": SVK, "qty": 7}]}).json()
ln = [x for x in j["totals"]["lines"] if x["kind"] == "item"][2]
check(j["items"][2]["unit"] == "percent" and j["items"][2]["rate"] == 5 and ln["total"] == 50 and ln["qty_text"] == "5 %" and ln["unit_text"] == "",
      f"#1649: percent position = 5 % of the extern positions (1000), the quantity does not count {ln}")
check(j["totals"]["net"] == 1350, "#1649: the percent position counts in the net " + str(j["totals"]["net"]))
r = A.post(B + f"{D}/{QK['id']}/invoice")
check(r.status_code == 201 and r.json()["items"][2]["unit"] == "flat" and r.json()["items"][2]["rate"] == 50 and r.json()["totals"]["net"] == "1350.00",
      "#1649: the invoice from the quotation makes it a plain amount " + r.text[:200])

# ---------------------------------------------------------------- #1649 the purchase of an accepted quotation
A.patch(B + f"{D}/{Q['id']}", json={"service_from": f"{Y + 1}-03-02", "service_to": f"{Y + 1}-03-06"})
A.post(B + f"{D}/{Q['id']}/status", json={"status": "sent"})
check(not sql("SELECT 1 FROM office_purchases WHERE doc_id=?", (Q["id"],)), "#1649: a sent quotation has no purchase rows")
r = A.post(B + f"{D}/{Q['id']}/status", json={"status": "accepted"})
check(r.ok, "accepted " + r.text[:120])
rows = sql("SELECT date, accepted_at, amount, source, ref, label FROM office_purchases WHERE doc_id=? ORDER BY id", (Q["id"],))
its = A.get(B + f"{D}/{Q['id']}").json()["items"]
check(len(rows) == 4 and all(x[0] == f"{Y + 1}-03-02" and x[1] == TODAY and x[3] == "item" for x in rows) and [x[4] for x in rows] == [its[i]["id"] for i in (0, 1, 3, 4)],
      f"#1649: accepted = one row per position with a purchase, dated at the start of the period of service {[(x[0], x[1], x[3]) for x in rows]}")
check(all(str(x[2]).startswith("kenc1:") for x in rows) and rows[0][5] == "Schnitt", "#1649: the amount is encrypted at rest")
# the amounts (written once in plain text with encryption switched off for the instance)
sql("INSERT INTO settings(key, value) VALUES('org_encrypt', '0') ON CONFLICT(key) DO UPDATE SET value='0'")
body = [{k: v for k, v in i.items() if k in ("id", "kind", "service_id", "title", "qty", "unit", "rate", "tax", "intext", "cost")} for i in its]
body[0]["qty"] = 5
r = A.put(B + f"{D}/{Q['id']}/items", json={"items": body})
check(r.ok, "an accepted quotation can still be changed " + r.text[:120])
rows = sql("SELECT amount, accepted_at FROM office_purchases WHERE doc_id=? ORDER BY id", (Q["id"],))
check([float(x[0]) for x in rows] == [1900.0, 220.0, 400.0, 450.0] and rows[0][1] == TODAY, f"#1649: changed while accepted = written anew (380 x 5, 55 x 4, ...) {rows}")
sql("UPDATE settings SET value='1' WHERE key='org_encrypt'")
r = A.post(B + f"{D}/{Q['id']}/status", json={"status": "declined"})
check(r.ok and not sql("SELECT 1 FROM office_purchases WHERE doc_id=?", (Q["id"],)), "#1649: leaving accepted removes the purchase rows")
QD = A.post(B + D, json={"project_title": "Ohne Zeitraum"}).json()
A.put(B + f"{D}/{QD['id']}/items", json={"items": [{"kind": "service", "service_id": SVC, "qty": 1}]})
A.post(B + f"{D}/{QD['id']}/status", json={"status": "accepted"})
rows = sql("SELECT date, accepted_at FROM office_purchases WHERE doc_id=?", (QD["id"],))
check(rows and rows[0][0] == TODAY == rows[0][1], f"#1649: without a period of service the day of acceptance {rows}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
