#!/usr/bin/env python3
"""2.47.0 API tests, part C (#1216): the shoot calculation sheet through the part routes of #1215 (part B), own container in
mode workspaces (start.sh). Invented crew and figures only (Camera 650 intern, Lighting 350 extern).
 - office setting industry_packs: admin switches the pack Film & Video on (unknown codes dropped), a member cannot;
   without the pack no part of kind 'shoot' can be added
 - a new shoot part starts with the pack's defaults; PATCH {sheet} computes on the server (staff with travel / preparation,
   producing, km, meals, hotel, set, additional costs, discount) and the quotation's totals follow
 - members: read and edit the sheet, but get no markup, purchase (costs / margin / cost per row) or intern / extern and
   cannot set them (the stored values stay); another organisation gets 404
usage: p2470_c_sheet_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,comments,office,clients"
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def part_of(j, kind="shoot"):
    """The part from an answer that is either the part or the whole quotation."""
    if isinstance(j, dict) and isinstance(j.get("parts"), list):
        ps = [p for p in j["parts"] if p.get("kind") == kind]
        return ps[-1] if ps else None
    if isinstance(j, dict) and isinstance(j.get("part"), dict):
        return j["part"]
    return j


def line(calc, block, label=None):
    return next((ln for ln in (calc or {}).get("lines") or [] if ln.get("block") == block and (label is None or ln.get("label") == label)), None)


# ---------------------------------------------------------------- setup: Alpha (alice admin, bob member), Beta (carol)
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
UID = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    UID[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
# 2.47.0: the id from the create answer (mode workspaces lists only the people an admin shares an organisation with)
CAROL = UID["carol"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})

# ---------------------------------------------------------------- the setting
st = A.get(B + "/api/office/settings").json()
check((st.get("settings") or st).get("industry_packs") == [], "industry_packs default [] " + str((st.get("settings") or st).get("industry_packs")))
DOC = A.post(B + "/api/office/docs", json={}).json()["id"]
r = A.post(B + f"/api/office/docs/{DOC}/parts", json={"kind": "shoot", "title": "Shooting"})
check(r.status_code in (400, 403, 409), f"no shoot part without the industry pack ({r.status_code})")
r = Bo.put(B + "/api/office/settings", json={"industry_packs": ["film"]})
check(r.status_code == 403, f"a member cannot switch the pack ({r.status_code})")
r = A.put(B + "/api/office/settings", json={"industry_packs": ["film", "nope"]})
check(r.ok, "admin switches the pack on " + r.text[:200])
st = A.get(B + "/api/office/settings").json()
check((st.get("settings") or st).get("industry_packs") == ["film"], "only known packs are kept")
check([x.get("code") for x in st.get("industry") or []] == ["film"] and st["industry"][0]["defaults"]["meal_large"] == 28,
      "the settings answer lists the pack with its defaults")

# ---------------------------------------------------------------- master data
cam = A.post(B + "/api/office/crew", json={"name_de": "Kamera", "name_en": "Camera", "rate_day": 650, "intext": "intern"}).json()
lig = A.post(B + "/api/office/crew", json={"name_de": "Beleuchter", "name_en": "Lighting", "rate_day": 350, "intext": "extern", "markup_pct": 10}).json()
check(cam.get("id") and lig.get("id"), "crew roles created")
e1 = A.post(B + "/api/office/equipment", json={"name": "Kamera-Set", "daily_rate": 400}).json()["id"]
e2 = A.post(B + "/api/office/equipment", json={"name": "Licht", "daily_rate": 100}).json()["id"]
SET = A.post(B + "/api/office/sets", json={"name": "Interview", "discount_pct": 20, "items": [{"equipment_id": e1, "qty": 1}, {"equipment_id": e2, "qty": 2}]}).json()["id"]

# ---------------------------------------------------------------- a shoot part
r = A.post(B + f"/api/office/docs/{DOC}/parts", json={"kind": "shoot", "title": "Shooting"})
check(r.status_code in (200, 201), "shoot part created " + r.text[:200])
P = part_of(r.json())
PID = P["id"]
check((P.get("sheet") or {}).get("head", {}).get("meal_large") == 28, "new sheet with the pack defaults")
U = B + f"/api/office/docs/{DOC}/parts/{PID}"
sheet = {"head": {"shoot_days": 1, "travel_days": 1, "travel_share": 1, "prep_days": 0.5, "prep_share": 1, "nights": 2, "night_rate": 100},
         "staff": [{"role_id": cam["id"], "qty": 1, "prep": 1}, {"role_id": lig["id"], "qty": 2, "prep": 0}],
         "producing": {"on": 1, "share": 0.2}, "km": {"km": 300, "rate": 0.35, "trips": 2}, "meals_on": 1, "set": {"set_id": SET},
         "extras": [{"name": "Studio", "qty": 1, "rate": 500}], "discount_pct": 5}
r = A.patch(U, json={"sheet": sheet})
check(r.ok, "admin saves the sheet " + r.text[:300])
j = r.json()
P = part_of(j)
c = P.get("calc") or {}
# camera 1625, lighting 2 x 350 x 2 days x 1.10 = 1540 (purchase 1400), producing 0.2 x 3165 = 633, km 210, meals 3 x 42 = 126,
# hotel 3 x 200 = 600, set 600 x 0.8 = 480, studio 500 -> sum 5714, discount 5 % = 285.70 -> 286, net 5428
check(c.get("sum") == "5714.00", "sum " + str(c.get("sum")))
check(c.get("discount") == "-286.00", "discount rounded to whole euros " + str(c.get("discount")))
check(c.get("net") == "5428.00", "net " + str(c.get("net")))
check(c.get("costs") == "2836.00", "admin: third-party costs 1400 + 210 + 126 + 600 + 500 " + str(c.get("costs")))
check((line(c, "staff", "Lighting") or line(c, "staff", "Beleuchter") or {}).get("cost") == "1400.00", "admin: purchase per row without markup")
check(any(r_.get("markup_pct") == 10 for r_ in P["sheet"]["staff"]), "admin: markup from the role")
check("doc_totals" in j or "totals" in j, "the quotation totals come back")

# ---------------------------------------------------------------- member
d = Bo.get(B + f"/api/office/docs/{DOC}").json()
bp = part_of(d)
check(bp and bp.get("id") == PID, "member reads the part")
txt = str(bp)
check("markup_pct" not in txt, "member: no markup in the sheet")
bc = bp.get("calc") or {}
check("costs" not in bc and "margin" not in bc, "member: no costs / margin")
check(all("cost" not in ln and "intext" not in ln for ln in bc.get("lines") or []), "member: no purchase / intern-extern per row")
ms = bp["sheet"]
for row in ms["staff"]:
    row["markup_pct"] = 0
    row["intext"] = "intern"
    row["rate"] = 1
ms["staff"][0]["qty"] = 2
r = Bo.patch(U, json={"sheet": ms})
check(r.ok, "member edits the sheet " + r.text[:200])
mp = part_of(r.json())
check("costs" not in (mp.get("calc") or {}) and "markup_pct" not in str(mp.get("sheet")), "member answer without purchase / markup")
ap = part_of(A.get(B + f"/api/office/docs/{DOC}").json())
lg = next(x for x in ap["sheet"]["staff"] if x.get("role_id") == lig["id"])
check(lg.get("markup_pct") == 10 and lg.get("intext") == "extern" and lg.get("rate") == 350, "member could not change markup / intext / rate " + str(lg))
check(next(x for x in ap["sheet"]["staff"] if x.get("role_id") == cam["id"])["qty"] == 2, "member changed the number of people")

# ---------------------------------------------------------------- another organisation
r = Ca.patch(U, json={"sheet": sheet})
check(r.status_code == 404, f"another organisation: 404 ({r.status_code})")

print(f"p2470_c_sheet_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
