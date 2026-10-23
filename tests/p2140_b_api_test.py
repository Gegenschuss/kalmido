#!/usr/bin/env python3
"""2.140.0 API tests, part B, own container (start.sh). Invented data only (addresses @example.com).
 - #2134 the shared statement reader (core/csvimport.py): a known bank layout is recognised in the budget AND in the office's
   bank import with the same guess; a CAMT.053 file reads in the budget like in the office (rows at once, another currency
   refused, DOCTYPE refused, duplicates found again); the plain guess of a file without a known layout is unchanged
 - #2134 the budget's month comparison: per category actual / plan of every month, the difference to the month before and
   to the average of the earlier months; 3 / 6 / 12 months, other values 400; a stranger 404
 - #2136 a private device <-> office equipment: taken over both ways with the fields, a link on both sides, "update from
   there", remove; equipment deleted = state gone; left the organisation = state noaccess without any name; into an
   organisation only as its admin (403 for a member); another person's device / link / equipment 404, a link never shows
   to another person on the equipment
 - freelancer-matrix: personal, office (a person without an organisation: budget comparison, device <-> the own office)
 - tenant-matrix: devlink (another person's device, link or equipment of another office area 404; an organisation only as admin)
usage: p2140_b_api_test.py <datadir>      (P2140B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,home,budget,contracts"


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


if not os.environ.get("P2140B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Leaving")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ids = {u: i for u, i in dbx("SELECT username, id FROM users")}
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["alice"]}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "dave@example.com", "role": "admin"}).ok
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2), (Da, ORG)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FR_ID, Fr = freelancer(B, A, features=FEAT)
for s in (A, Fr):
    s.put(B + "/api/office/settings", json={"company_fields": {"name": "Beispiel GmbH", "street": "Weg 1", "zip": "12345", "city": "Musterstadt",
                                                               "country": "DE"}})

# ================================================================ #2134 the shared reader: a known layout, CAMT
L = A.post(B + "/api/budget/lists", json={}).json()["list_id"]
SPK = ('"Auftragskonto";"Buchungstag";"Valutadatum";"Buchungstext";"Verwendungszweck";"Glaeubiger ID";"Mandatsreferenz";'
       '"Beguenstigter/Zahlungspflichtiger";"Kontonummer/IBAN";"BIC (SWIFT-Code)";"Betrag";"Waehrung";"Info"\n'
       '"DE00123";"01.09.26";"01.09.26";"LASTSCHRIFT";"Strom September";"";"";"Stadtwerke Beispiel";"DE89370400440532013000";"X";"-45,00";"EUR";"Umsatz gebucht"\n'
       '"DE00123";"02.09.26";"02.09.26";"GUTSCHRIFT";"Gehalt";"";"";"Firma Beispiel";"DE89370400440532013000";"X";"2.100,00";"EUR";"Umsatz gebucht"\n')
r = A.post(B + f"/api/budget/{L}/import/parse", json={"text": SPK})
g = r.json().get("guess") or {}
check(r.ok and g.get("preset") == "sparkasse" and g.get("preset_name") and (g["date"], g["amount"], g["title"], g["counterpart"]) == (1, 10, 4, 7)
      and g["date_format"] == "DD.MM.YY" and g["decimal"] == ",", f"budget: the Sparkasse layout is recognised {g}")
r = A.post(B + "/api/office/bank/import/preview", json={"text": SPK, "filename": "konto.csv"})
g2 = r.json().get("guess") or {}
check(r.ok and all(g2.get(k) == g.get(k) for k in ("preset", "date", "amount", "title", "counterpart", "date_format", "decimal")),
      f"office bank: the same file, the same guess (one reader) {g2}")
MAP = {k: g[k] for k in ("date", "amount", "amount_in", "amount_out", "title", "counterpart", "decimal", "date_format")}
rows = A.post(B + f"/api/budget/{L}/import/parse", json={"text": SPK, "mapping": MAP}).json()["rows"]
check([(x["day"], x["amount"], x["kind"], x["title"]) for x in rows] == [("2026-09-01", 45.0, "out", "Strom September"), ("2026-09-02", 2100.0, "in", "Gehalt")],
      f"budget: the rows of the recognised layout {rows}")
PLAIN = "Datum;Text;Betrag\n01.09.2026;Kaffee;-2,00\n"
g3 = A.post(B + f"/api/budget/{L}/import/parse", json={"text": PLAIN}).json()["guess"]
check(g3.get("preset") is None and (g3["date"], g3["title"], g3["amount"]) == (0, 1, 2), f"a file without a known layout: the plain guess {g3}")

CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>S-1</Id>
<Ntry><Amt Ccy="EUR">1000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-09-05</Dt></BookgDt><NtryDtls><TxDtls><RltdPties><Dbtr><Pty><Nm>Firma Beispiel</Nm></Pty></Dbtr></RltdPties>
<RmtInf><Ustrd>Bonus</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="EUR">59.50</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-09-06</Dt></BookgDt><NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>Markt Beispiel</Nm></Pty></Cdtr></RltdPties>
<RmtInf><Ustrd>Einkauf</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="USD">10.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-09-06</Dt></BookgDt><AddtlNtryInf>Fremd</AddtlNtryInf></Ntry>
</Stmt></BkToCstmrStmt></Document>"""
r = A.post(B + f"/api/budget/{L}/import/parse", json={"text": CAMT})
j = r.json()
rows = j.get("rows") or []
check(r.ok and j.get("fmt") == "camt" and len(rows) == 3 and (rows[0]["amount"], rows[0]["kind"], rows[0]["title"], rows[0]["counterpart"]) == (1000.0, "in", "Bonus", "Firma Beispiel")
      and (rows[1]["amount"], rows[1]["kind"], rows[1]["title"]) == (59.5, "out", "Einkauf") and rows[2]["error"] and j["skipped"] == 1,
      "budget: a CAMT statement reads at once, another currency refused " + r.text[:300])
r = A.post(B + f"/api/budget/{L}/import/commit", json={"rows": [{k: x[k] for k in ("day", "amount", "kind", "title", "counterpart")} for x in rows[:2]]})
check(r.status_code == 201 and r.json()["created"] == 2, "budget: the CAMT rows taken over " + r.text[:200])
rows = A.post(B + f"/api/budget/{L}/import/parse", json={"text": CAMT}).json()["rows"]
check(rows[0]["dup"] and rows[1]["dup"], "budget: the same CAMT file again = duplicates")
BAD = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "boom">]><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><Ntry>&e;</Ntry></Document>'
check(A.post(B + f"/api/budget/{L}/import/parse", json={"text": BAD}).status_code == 400, "budget: CAMT with DOCTYPE / ENTITY refused")
check(A.post(B + f"/api/budget/{L}/import/parse", json={"text": "a;b\n" + "x;y\n" * 700000}).status_code in (400, 413), "budget: a file over 2 MB refused")
r = A.post(B + "/api/office/bank/import/preview", json={"text": CAMT, "filename": "a.xml"})
check(r.ok and r.json()["fmt"] == "camt" and r.json()["count"] == 2, "office bank: CAMT reads as before " + r.text[:200])

# ================================================================ #2134 the month comparison
j = A.get(B + f"/api/budget/{L}", params={"month": "2026-09"}).json()
CATS = {x["name"]: x["id"] for x in j["cats"]}
assert A.patch(B + f"/api/budget/cats/{CATS['Groceries']}", json={"limit": "200"}).ok
for day, amt in (("2026-07-03", "100"), ("2026-08-03", "150"), ("2026-09-03", "120")):
    assert A.post(B + f"/api/budget/{L}/entries", json={"day": day, "amount": amt, "kind": "out", "title": "Market", "cat_id": CATS["Groceries"]}).status_code == 201
r = A.get(B + f"/api/budget/{L}/compare", params={"month": "2026-09", "months": 3})
j = r.json()
gro = next((x for x in j.get("cats") or [] if x["key"] == CATS["Groceries"]), {})
check(r.ok and j["months"] == ["2026-07", "2026-08", "2026-09"] and [m["ist"] for m in gro.get("months", [])] == [100.0, 150.0, 120.0]
      and gro.get("soll") == 200.0 and gro.get("prev") == 150.0 and gro.get("diff_prev") == -30.0 and gro.get("pct_prev") == -20.0
      and gro.get("avg") == 125.0 and gro.get("diff_avg") == -5.0 and gro.get("pct_avg") == -4.0, f"compare: Groceries over 3 months {gro}")
nocat = next((x for x in j["cats"] if x["key"] == "none-out"), {})
check(nocat.get("ist") == 59.5 and nocat.get("name") is None, f"compare: entries without a category {nocat}")
check(j["totals"]["out"]["ist"] == 179.5 and j["totals"]["in"]["ist"] == 1000.0 and j["totals"]["out"]["months"][0]["ist"] == 100.0,
      f"compare: the totals {j['totals']['out']['ist']} {j['totals']['in']['ist']}")
check(not any(x["key"] == CATS["Housing"] for x in j["cats"]), "compare: a category without anything in the period is left out")
j6 = A.get(B + f"/api/budget/{L}/compare", params={"month": "2026-09", "months": 6}).json()
g6 = next((x for x in j6["cats"] if x["key"] == CATS["Groceries"]), {})
check(g6.get("avg") == 125.0 and len(g6.get("months", [])) == 6, f"compare: months before the budget was used do not count for the average {g6.get('avg')}")
check(len(A.get(B + f"/api/budget/{L}/compare", params={"month": "2026-09", "months": 12}).json()["months"]) == 12, "compare: 12 months")
check(A.get(B + f"/api/budget/{L}/compare", params={"months": 6}).json()["n"] == 6, "compare: default month = this month")
check(A.get(B + f"/api/budget/{L}/compare", params={"month": "2026-09", "months": 5}).status_code == 400, "compare: 5 months = 400")
check(A.get(B + f"/api/budget/{L}/compare", params={"month": "2026-13"}).status_code == 400, "compare: a wrong month = 400")
check(Ca.get(B + f"/api/budget/{L}/compare").status_code == 404, "compare: another person's budget = 404")
# freelancer-matrix: personal -- the own budget without an organisation
FL = Fr.post(B + "/api/budget/lists", json={}).json()["list_id"]
check(Fr.get(B + f"/api/budget/{FL}/compare", params={"months": 3}).ok, "freelancer: the own budget comparison")
check(Fr.get(B + f"/api/budget/{L}/compare").status_code == 404, "freelancer: another person's budget = 404")

# ================================================================ #2136 device <-> equipment as a person without an organisation
# freelancer-matrix: personal, office
r = Fr.post(B + "/api/life/devices", json={"name": "Kamera", "model": "X100", "bought": "2026-01-10", "warranty": "2028-01-10",
                                           "serial": "SN-1", "price": "1190"})
check(r.status_code == 201 and r.json()["fam"].get("serial") == "SN-1" and r.json()["fam"].get("price") == 1190.0, "a device with serial and price " + r.text[:200])
FT = r.json()["id"]
j = Fr.get(B + f"/api/life/devices/{FT}/link").json()
offs = j.get("offices") or []
check(j["link"] is None and len(offs) == 1 and offs[0]["personal"] and offs[0]["ws"] == "private", f"freelancer: only the own office is offered {offs}")
r = Fr.post(B + f"/api/life/devices/{FT}/to-office", json={"office_id": offs[0]["id"], "name": "Kamera X100", "purchase_net": "1000"})
check(r.status_code == 201 and r.json()["link"]["other"]["state"] == "ok", "freelancer: into the own office " + r.text[:300])
EQ = r.json()["equipment_id"]
LNK = r.json()["link"]["id"]
e = Fr.get(B + f"/api/office/equipment/{EQ}").json()
check(e["name"] == "Kamera X100" and e["serial_no"] == "SN-1" and e["purchase_date"] == "2026-01-10" and float(e["purchase_net"]) == 1000,
      f"the equipment carries the device's fields {e.get('name')} {e.get('serial_no')} {e.get('purchase_date')} {e.get('purchase_net')}")
o = Fr.get(B + f"/api/life/devices/{FT}/link").json()["link"]["other"]
check(o["state"] == "ok" and o["equipment_id"] == EQ and o["name"] == "Kamera X100" and o["ws"] == "private" and o["can_write"], f"device side: linked {o}")
j = Fr.get(B + f"/api/office/equipment/{EQ}/link").json()
check(j["link"]["other"] == {"state": "ok", "task_id": FT, "list_id": j["link"]["other"].get("list_id"), "name": "Kamera"} and j["can_take"] is True,
      f"equipment side: linked with the device {j}")
check(Fr.post(B + f"/api/life/devices/{FT}/to-office", json={"office_id": offs[0]["id"]}).status_code == 400, "a linked device is not taken over twice")
assert Fr.patch(B + f"/api/office/equipment/{EQ}", json={"name": "Kamera neu", "serial_no": "SN-2", "purchase_net": "900"}).ok
r = Fr.post(B + f"/api/life/device-links/{LNK}/pull", json={"into": "device"})
f = dbx("SELECT fam FROM tasks WHERE id=?", (FT,))[0][0]
check(r.ok and '"name":"Kamera neu"' in f and '"serial":"SN-2"' in f and '"price":900.0' in f and '"warranty":"2028-01-10"' in f,
      f"update from there: the device takes name, serial, price; the warranty stays {f}")
assert Fr.patch(B + f"/api/office/equipment/{EQ}", json={"name": "Anders"}).ok
r = Fr.post(B + f"/api/life/device-links/{LNK}/pull", json={"into": "equipment"})
check(r.ok and Fr.get(B + f"/api/office/equipment/{EQ}").json()["name"] == "Kamera neu X100", "update from there: the equipment takes the device's name + model")
check(Fr.post(B + f"/api/life/device-links/{LNK}/pull", json={"into": "x"}).status_code == 400, "pull: into must be device or equipment")
assert Fr.delete(B + f"/api/office/equipment/{EQ}").ok
check(Fr.get(B + f"/api/life/devices/{FT}/link").json()["link"]["other"] == {"state": "gone"}, "the equipment deleted: state gone, no error")
check(Fr.post(B + f"/api/life/device-links/{LNK}/pull", json={"into": "device"}).status_code == 409, "pull of a broken link = 409")
check(Fr.delete(B + f"/api/life/device-links/{LNK}").ok and Fr.get(B + f"/api/life/devices/{FT}/link").json()["link"] is None, "remove the link")
# the other way: equipment -> a private device
r = Fr.post(B + "/api/office/equipment", json={"name": "Licht", "serial_no": "L-1", "purchase_date": "2026-02-01", "purchase_net": "300",
                                               "vendor": "Haendler Beispiel"})
assert r.status_code == 201, r.text
EQ2 = r.json()["id"]
check(Fr.get(B + f"/api/office/equipment/{EQ2}/link").json() == {"link": None, "can_take": True}, "equipment without a link: can be taken over")
r = Fr.post(B + f"/api/office/equipment/{EQ2}/to-device", json={})
t = r.json().get("task") or {}
check(r.status_code == 201 and t.get("fam", {}).get("kind") == "device" and t["fam"].get("serial") == "L-1" and t["fam"].get("bought") == "2026-02-01"
      and t["fam"].get("price") == 300.0 and "Haendler Beispiel" in (t.get("content") or "") and r.json()["link"]["other"]["state"] == "ok",
      "freelancer: equipment -> a private device with its fields " + r.text[:300])
check(Fr.post(B + f"/api/office/equipment/{EQ2}/to-device", json={}).status_code == 400, "a linked piece of equipment is not taken over twice")

# ================================================================ #2136 organisations: admin only, no foreign links, leaving
# tenant-matrix: devlink
AT = A.post(B + "/api/life/devices", json={"name": "Laptop", "serial": "LP-9"}).json()["id"]
offs = A.get(B + f"/api/life/devices/{AT}/link").json()["offices"]
check(sorted(o["ws"] for o in offs) == sorted(["private", f"org:{ORG}"]), f"an organisation admin: the own office and Alpha {offs}")
r = A.post(B + f"/api/life/devices/{AT}/to-office", json={"office_id": ORG})
check(r.status_code == 201, "into the organisation as its admin " + r.text[:200])
AEQ, ALNK = r.json()["equipment_id"], r.json()["link"]["id"]
check(dbx("SELECT org_id FROM office_equipment WHERE id=?", (AEQ,))[0][0] == ORG, "the equipment lies in the organisation")
BT = Bo.post(B + "/api/life/devices", json={"name": "Handy"}).json()["id"]
check([o["ws"] for o in Bo.get(B + f"/api/life/devices/{BT}/link").json()["offices"]] == ["private"], "a member: only the own office is offered")
check(Bo.post(B + f"/api/life/devices/{BT}/to-office", json={"office_id": ORG}).status_code == 403, "a member cannot add equipment to the organisation")
check(Bo.get(B + f"/api/office/equipment/{AEQ}/link").json()["link"] is None, "another person's link never shows on the equipment")
check(Bo.post(B + f"/api/office/equipment/{AEQ}/to-device", json={}).status_code == 403, "a member cannot take equipment over (no purchase fields)")
for meth, path, body in (("get", f"/api/life/devices/{AT}/link", None), ("post", f"/api/life/devices/{AT}/to-office", {"office_id": ORG2}),
                         ("post", f"/api/life/device-links/{ALNK}/pull", {"into": "device"}), ("delete", f"/api/life/device-links/{ALNK}", None),
                         ("get", f"/api/office/equipment/{AEQ}/link", None), ("post", f"/api/office/equipment/{AEQ}/to-device", {})):
    r = getattr(Ca, meth)(B + path, **({"json": body} if body is not None else {}))
    check(r.status_code == 404, f"another organisation's person: {meth} {path} -> 404 ({r.status_code})")
check(Fr.get(B + f"/api/life/devices/{AT}/link").status_code == 404, "a freelancer: another person's device 404")
check(A.post(B + f"/api/life/devices/{BT}/to-office", json={"office_id": ORG}).status_code == 404, "an admin: another person's device 404")
# leaving the organisation: the link stays as a hint without any name
DT = Da.post(B + "/api/life/devices", json={"name": "Mikrofon"}).json()["id"]
r = Da.post(B + f"/api/life/devices/{DT}/to-office", json={"office_id": ORG})
assert r.status_code == 201, r.text
DLNK = r.json()["link"]["id"]
assert A.delete(B + f"/api/orgs/{ORG}/members/{ids['dave']}").ok
Da.patch(B + "/api/settings", json={"workspace": "private"})
o = Da.get(B + f"/api/life/devices/{DT}/link").json()["link"]["other"]
check(o == {"state": "noaccess"}, f"left the organisation: state noaccess, nothing of the equipment shown {o}")
check(Da.post(B + f"/api/life/device-links/{DLNK}/pull", json={"into": "device"}).status_code == 409, "left: pull = 409")
check(Da.delete(B + f"/api/life/device-links/{DLNK}").ok, "left: the link can be removed")
check(A.get(B + f"/api/office/equipment").ok and dbx("SELECT count(*) FROM office_equipment WHERE org_id=? AND name='Mikrofon'", (ORG,))[0][0] == 1,
      "the organisation keeps its equipment")
# the module "home" off: no device routes
Bo.patch(B + "/api/settings", json={"features": "cal,comments,collab,office,clients"})
check(Bo.get(B + f"/api/life/devices/{BT}/link").status_code == 409, "the module home off: 409")

print(f"p2140_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
