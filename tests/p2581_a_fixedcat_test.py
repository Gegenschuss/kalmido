#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.581.0 A (#4820): rename / merge a category of the fixed costs in one step (POST /api/office/fixed-costs/category-rename,
office/cashflow.py rk_fixed_cat_rename) and no colon at the end of a category (rk_cat_clean, the import's group row).
Own container (org encryption on). Invented names only.
freelancer-matrix: office
 - an organisation's office admin: three fixed costs "Digital Abos" are renamed to "Subscriptions" in one call (count 3,
   ids, old), stored renamed (the category is plain at rest, the amount stays sealed), every entry has a history entry naming "category"; renamed onto an
   existing name = merged (merged true, one group); the undo (from/to swapped, ids) moves back only the moved entries;
   an empty name = without a category; "without category" as a whole (from "" without ids) 400; an unknown category 404
 - another organisation's admin: 404 and nothing changes; a member without the office admin right 403
 - by hand: a category "Versicherungen :" is stored as "Versicherungen"
 - the import preview: a group row "Digital Abos:" and a category cell "Musik :" give the categories without the colon
 - the person without an organisation (tests/freelancer_fixture.py) in the personal office: rename and merge work the same
usage: p2581_a_fixedcat_test.py <datadir>"""
import base64
import os
import sys
from datetime import date

import kt
from kt import B, check
from freelancer_fixture import freelancer, login

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2581A")

FEAT = "cal,comments,collab,office,clients,docs"
A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": kt.PASSWORD, "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} {r.status_code} {r.text[:120]}")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok, "setup: bob in Alpha")
CARL = kt.dbx("SELECT id FROM users WHERE username='carl'")[0][0]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CARL}).json()["id"]
Bo, Ca = login(B, "bob"), login(B, "carl")
for s, ws in ((Bo, f"org:{ORG}"), (Ca, f"org:{BETA}")):
    check(s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": ws}).ok, f"setup: {ws}")
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
F = "/api/office/fixed-costs"
REN = "/api/office/fixed-costs/category-rename"  # the whole path (tests/tenant_coverage_test.py finds it)
D = date.today().replace(day=1).isoformat()


def add(s, label, cat, who):
    r = s.post(B + F, json={"label": label, "amount": "10", "start": D, "repeat": "monthly", "category": cat})
    check(r.status_code == 201, f"{who}: add {label} {r.status_code} {r.text[:200]}")
    return r.json().get("id", 0) if r.status_code == 201 else 0


def cats(s):
    return {f["id"]: f["category"] for f in (s.get(B + F).json().get("items") or [])}


def stored(fid):
    return kt.dbx("SELECT category FROM office_fixed_costs WHERE id=?", (fid,))[0][0]


def run(s, who, sealed):
    a1, a2, a3 = (add(s, n, "Digital Abos:", who) for n in ("Streaming", "Music", "Cloud"))
    check(cats(s)[a1] == "Digital Abos", f"{who}: a category by hand loses the colon at the end ({cats(s)[a1]!r})")
    ins = add(s, "Liability", "Insurances", who)
    other = add(s, "Bank", "Bank fees", who)
    # rename (the colon is gone already, so rename "Digital Abos" -> "Subscriptions")
    r = s.post(B + REN, json={"from": "Digital Abos", "to": "  Subscriptions : "})
    j = r.json() if r.ok else {}
    check(r.ok and j.get("count") == 3 and sorted(j.get("ids") or []) == sorted([a1, a2, a3]) and j.get("old") == "Digital Abos"
          and j.get("to") == "Subscriptions" and j.get("merged") is False, f"{who}: renamed three in one step {r.status_code} {r.text[:300]}")
    cs = cats(s)
    check(all(cs[x] == "Subscriptions" for x in (a1, a2, a3)) and cs[ins] == "Insurances" and cs[other] == "Bank fees",
          f"{who}: only the category's entries changed {cs}")
    if sealed:
        # 2.581.0 (#4820): the category is plain at rest (core/orgcrypt.py seals only the amount); the amount stays sealed
        check(stored(a1) == "Subscriptions" and str(kt.dbx("SELECT amount FROM office_fixed_costs WHERE id=?", (a1,))[0][0]).startswith("kenc1:"),
              f"{who}: stored category renamed, the amount still sealed")
    h = s.get(B + F + f"/{a2}/history").json().get("items") or []
    check(h and "category" in (h[0].get("fields") or []), f"{who}: the history of an entry names the category {h[:1]}")
    # merge onto "Insurances"
    r = s.post(B + REN, json={"from": "Subscriptions", "to": "Insurances"})
    j = r.json() if r.ok else {}
    check(r.ok and j.get("count") == 3 and j.get("merged") is True, f"{who}: merged {r.status_code} {r.text[:300]}")
    cs = cats(s)
    check(sum(1 for v in cs.values() if v == "Insurances") == 4, f"{who}: one group of four {cs}")
    # the toast's undo: back with ids, the entry that was in "Insurances" before stays
    r = s.post(B + REN, json={"from": j.get("to"), "to": j.get("old"), "ids": j.get("ids")})
    cs = cats(s)
    check(r.ok and r.json().get("count") == 3 and cs[ins] == "Insurances" and all(cs[x] == "Subscriptions" for x in (a1, a2, a3)),
          f"{who}: the undo moves back only the moved entries {r.status_code} {cs}")
    # empty = without a category, and back through ids (from "")
    r = s.post(B + REN, json={"from": "Bank fees", "to": " : "})
    j = r.json() if r.ok else {}
    check(r.ok and j.get("count") == 1 and j.get("to") == "" and cats(s)[other] == "", f"{who}: empty = without a category {r.text[:200]}")
    r = s.post(B + REN, json={"from": "", "to": "Bank fees", "ids": j.get("ids")})
    check(r.ok and cats(s)[other] == "Bank fees", f"{who}: undo from without a category through ids {r.status_code} {r.text[:200]}")
    r = s.post(B + REN, json={"from": "", "to": "Something"})
    check(r.status_code == 400, f"{who}: without category as a whole 400 ({r.status_code})")
    r = s.post(B + REN, json={"from": "Nothing here", "to": "X"})
    check(r.status_code == 404, f"{who}: an unknown category 404 ({r.status_code})")
    for bad in ({"from": 5, "to": "x"}, {"from": "Insurances", "to": ["x"]}, {"from": "Insurances", "to": "x", "ids": "1"},
                {"from": "Insurances", "to": "x", "ids": [True]}):
        check(s.post(B + REN, json=bad).status_code == 400, f"{who}: bad input 400 {bad}")
    return a1


# ---- an organisation's office admin
A1 = run(A, "the admin", True)

# ---- another organisation's admin / a member: refused, nothing changes
before = cats(A)
r = Ca.post(B + REN, json={"from": "Subscriptions", "to": "Stolen"})
check(r.status_code == 404, f"another organisation: 404 ({r.status_code} {r.text[:120]})")
r = Ca.post(B + REN, json={"from": "Subscriptions", "to": "Stolen", "ids": [A1]})
check(r.status_code == 404, f"another organisation with the ids: 404 ({r.status_code})")
r = Bo.post(B + REN, json={"from": "Subscriptions", "to": "Member"})
check(r.status_code == 403, f"a member without the office admin right: 403 ({r.status_code})")
check(cats(A) == before, "nothing changed by the refused calls")

# ---- the import preview: a group row with a colon, a category cell with " :"
CSV = "Name;Amount;Category\nDigital Abos:;;\nStreaming;12,99;\nMusic;9,99;Musik :\n"
r = A.post(B + F + "/import/preview", files={"file": ("fixed.csv", CSV.encode(), "text/csv")})
rows = {x.get("label"): x.get("category") for x in (r.json().get("rows") or [])} if r.ok else {}
check(rows.get("Streaming") == "Digital Abos" and rows.get("Music") == "Musik", f"import: no colon at the end {r.status_code} {rows} {r.text[:200]}")

# ---- the person without an organisation
run(Fr, "the freelancer", False)

sys.exit(kt.done("p2581_a_fixedcat"))
