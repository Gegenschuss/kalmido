#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1041.0 (#5812): repricing a quotation draft (Nachkalkulieren), POST /api/office/docs/<id>/reprice
(kalmido/office/reprice.py). Invented companies and figures only.
 - preview (apply false) writes nothing: same prices, same version, no log entry
 - apply: every chosen unit price changes (no discount line), the totals follow, the office log says "reprice" with the
   percentage; ONE undo step (X-Kalmido-Undo, POST /api/office/undo/doc/<id> op undo) brings every price back
 - target net sum with the rest: the stored net is exactly the target; item_ids: only those positions change
 - a version that is not the stored one: 409 with the current document, nothing written; an unreachable target: 409
 - a part (part_id): its positions change, the title page's not; the target means the whole quotation
 - finalised quotation: 409 (preview too); an invoice: 409
 - surplus target: a member 403, the admin without external costs 400, with external costs 30 % reached
 - wrong input: 400 (mode, round, value)
tenant-matrix: office (another organisation: 404)
freelancer-matrix: office (a person without an organisation reprices in the personal office: preview, apply, undo, surplus)
usage: p21041_a_reprice_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, done, fresh, sess  # noqa: E402

fresh(prefix="P21041A")
D = B + "/api/office/docs"
TOKS = iter("%032x" % (0x5812a0 + i) for i in range(50))

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments", "office", "clients"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
UID = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    UID[u] = r.json().get("id")
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = UID["carol"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
r = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": CAROL}) if CAROL else None
check(r is not None and r.status_code == 201, f"setup: another organisation {getattr(r, 'status_code', None)}")
ORG2 = r.json()["id"] if r is not None and r.ok else None
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
if ORG2:
    Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
FID, Fr = freelancer(B, A)

ITEMS = [{"kind": "heading", "title": "Konzept"}, {"title": "Regie", "qty": 2, "rate": 1000, "unit": "day"},
         {"title": "Kamera", "qty": 3, "rate": 850, "unit": "day"}, {"title": "Lizenz", "qty": 1, "rate": 333.33, "unit": "flat"}]


def new_doc(s, title, items=ITEMS):
    r = s.post(D, json={"project_title": title})
    check(r.status_code == 201, f"setup: a quotation {r.status_code} {r.text[:200]}")
    did = r.json()["id"]
    r = s.put(D + f"/{did}/items", json={"items": items})
    check(r.ok, f"setup: its positions {r.status_code} {r.text[:200]}")
    return did


def doc(s, did):
    return s.get(D + f"/{did}").json()


def rates(d):
    return [float(x["rate"]) for x in d.get("items") or [] if x.get("kind") == "service"]


def rp(s, did, headers=None, **b):
    return s.post(D + f"/{did}/reprice", json=b, headers=headers or {})


def log_actions(s, did):
    """the document's office log (its admin reads it)"""
    r = s.get(D + f"/{did}/log")
    return (r.json() if r.ok else {}).get("log") or []


def suite(s, who, admin=True, adm=None):
    adm = adm or s
    did = new_doc(s, f"Frühjahr {who}")
    d0 = doc(s, did)
    r0 = rates(d0)
    # ---- preview
    r = rp(s, did, mode="pct", value=10, round="cent", apply=False)
    j = r.json() if r.ok else {}
    check(r.ok and j.get("reachable") and abs(j["after"]["net"] - round(d0["totals"]["net"] * 1.1, 2)) < 0.02,
          f"{who}: preview +10 % shows the new net {r.status_code} {r.text[:200]}")
    check(j.get("pct") == 10 and len(j.get("items") or []) == 3, f"{who}: preview names 10 % and the three priced positions {j.get('pct')} {len(j.get('items') or [])}")
    d1 = doc(s, did)
    check(rates(d1) == r0 and d1["updated_at"] == d0["updated_at"], f"{who}: preview wrote nothing {rates(d1)}")
    check(not any(x.get("action") == "reprice" for x in log_actions(adm, did)), f"{who}: preview: no log entry")
    # ---- apply + one undo step
    tok = next(TOKS)
    r = rp(s, did, headers={"X-Kalmido-Undo": tok}, mode="pct", value=10, round="cent", apply=True, expect_updated_at=d1["updated_at"])
    check(r.ok and r.json().get("changed") == 3, f"{who}: apply changes three prices {r.status_code} {r.text[:200]}")
    d2 = doc(s, did)
    check(rates(d2) == [1100, 935, 366.66], f"{who}: the unit prices themselves changed {rates(d2)}")
    check(not any(ln.get("kind") in ("discount", "surcharge") for ln in d2["totals"].get("lines") or []), f"{who}: no discount / markup line")
    acts = [x for x in log_actions(adm, did) if x.get("action") == "reprice"]
    check(len(acts) == 1 and (acts[0].get("detail") or {}).get("pct") == 10, f"{who}: office log 'reprice' with 10 % {acts[:1]}")
    r = s.post(B + f"/api/office/undo/doc/{did}", json={"sess": tok, "op": "undo"})
    d3 = doc(s, did)
    check(r.ok and rates(d3) == r0, f"{who}: one undo brings every price back {r.status_code} {rates(d3)}")
    # ---- target net with the rest; only some positions
    r = rp(s, did, mode="net", value=6000, round="five", rest=True, apply=True, expect_updated_at=d3["updated_at"])
    d4 = doc(s, did)
    check(r.ok and abs(float(d4["totals"]["net"]) - 6000) < 0.001, f"{who}: target net 6.000 met exactly {r.status_code} {d4['totals'].get('net')} {r.text[:160]}")
    ids = [x["id"] for x in d4["items"] if x.get("kind") == "service"]
    r = rp(s, did, mode="pct", value=-20, item_ids=[ids[0]], apply=True, expect_updated_at=d4["updated_at"])
    d5 = doc(s, did)
    check(r.ok and rates(d5)[1:] == rates(d4)[1:] and rates(d5)[0] == round(rates(d4)[0] * 0.8, 2), f"{who}: item_ids: only the chosen one {rates(d4)} -> {rates(d5)}")
    # ---- stale version, unreachable
    r = rp(s, did, mode="pct", value=5, apply=True, expect_updated_at="2001-01-01T00:00:00.000Z")
    check(r.status_code == 409 and (r.json().get("doc") or {}).get("id") == did and rates(doc(s, did)) == rates(d5), f"{who}: another version: 409 + the document, nothing written {r.status_code}")
    r = rp(s, did, mode="net", value=100, item_ids=[ids[0]], apply=False)
    check(r.ok and r.json().get("reachable") is False and r.json().get("reason"), f"{who}: unreachable target: preview says why {r.text[:160]}")
    r = rp(s, did, mode="net", value=100, item_ids=[ids[0]], apply=True, expect_updated_at=doc(s, did)["updated_at"])
    check(r.status_code == 409 and rates(doc(s, did)) == rates(d5), f"{who}: unreachable target: apply 409, nothing written {r.status_code}")
    # ---- wrong input
    for b in ({"mode": "x", "value": 1}, {"mode": "pct", "value": 1, "round": "ten"}, {"mode": "pct", "value": "abc"}, {"mode": "net", "value": -5}):
        check(rp(s, did, **b).status_code == 400, f"{who}: wrong input 400 {b}")
    # ---- surplus
    if not admin:
        check(rp(s, did, mode="margin", value=30).status_code == 403, f"{who}: a member may not aim at the surplus (403)")
    else:
        r = rp(s, did, mode="margin", value=30)
        check(r.status_code == 400 and "external costs" in r.text, f"{who}: surplus without external costs: 400 with the reason {r.status_code} {r.text[:160]}")
        dm = new_doc(s, f"Marge {who}", [{"title": "Regie", "qty": 3, "rate": 1100, "unit": "day"},
                                          {"title": "Kamera extern", "qty": 4, "rate": 950, "cost": 700, "intext": "extern", "unit": "day"}])
        r = rp(s, dm, mode="margin", value=30, rest=True, apply=True, expect_updated_at=doc(s, dm)["updated_at"])
        t = doc(s, dm)["totals"]
        mp = (float(t["net"]) - float(t["costs"])) / float(t["net"]) * 100 if r.ok else None
        check(r.ok and mp is not None and abs(mp - 30) < 0.005, f"{who}: surplus 30 % reached {mp} {r.text[:160]}")
    return did


# ---- the organisation: admin and member
DA = suite(A, "alice")
DB = suite(Bo, "bob", admin=False, adm=A)

# ---- a part: its positions change, the title page's not; the target means the whole quotation
r = A.post(D + f"/{DA}/parts", json={"kind": "items", "title": "Modul A"})
check(r.status_code in (200, 201), f"part: created {r.status_code} {r.text[:160]}")
PID = (r.json().get("part") or {}).get("id") if r.ok else None
r = A.put(D + f"/{DA}/parts/{PID}/items", json={"items": [{"title": "Animation", "qty": 2, "rate": 700, "unit": "day"}]})
check(r.ok, f"part: its positions {r.status_code} {r.text[:160]}")
dp = doc(A, DA)
title_rates = rates(dp)
net0 = float(dp["totals"]["net"])
r = rp(A, DA, mode="net", value=round(net0 + 280, 2), rest=True, part_id=PID, apply=True, expect_updated_at=dp["updated_at"])
dq = doc(A, DA)
part = next((p for p in dq.get("parts") or [] if p["id"] == PID), {})
check(r.ok and rates(dq) == title_rates, f"part: the title page's prices stay {r.status_code} {r.text[:160]}")
check([float(x["rate"]) for x in part.get("items") or []] == [840], f"part: its price 700 -> 840 {[x.get('rate') for x in part.get('items') or []]}")
check(abs(float(dq["totals"]["net"]) - (net0 + 280)) < 0.001, f"part: the whole quotation's net is the target {dq['totals']['net']} vs {net0 + 280}")

# ---- another organisation: 404
if ORG2:
    r = Ca.post(B + f"/api/office/docs/{DA}/reprice", json={"mode": "pct", "value": 10, "apply": True})
    check(r.status_code == 404 and rates(doc(A, DA)) == rates(dq), f"another organisation: 404, nothing changed {r.status_code}")

# ---- finalised / invoice: 409
r = A.post(D + f"/{DA}/finalize")
check(r.ok and r.json().get("locked"), f"setup: finalised {r.status_code} {r.text[:160]}")
r = rp(A, DA, mode="pct", value=10)
check(r.status_code == 409, f"finalised: 409 (preview too) {r.status_code}")
r = A.post(D, json={"kind": "invoice", "items": [{"title": "Schnitt", "qty": 1, "rate": 500}]})
check(r.status_code == 201, f"setup: an invoice draft {r.status_code}")
check(rp(A, r.json()["id"], mode="pct", value=10).status_code == 409, "an invoice: 409")

# ---- a person without an organisation
suite(Fr, "frida")

sys.exit(done("p21041_a_reprice"))
