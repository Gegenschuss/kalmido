#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.828.0 A (#5511): several industries at once (decided 10.11.2026: one box per industry, as Office > Packs).
 - PUT /api/industry {industries: [...]}: the set chosen; only the change reaches industry_packs (a pack switched on under
   Office > Packs stays, own packs stay); the old form {industry: "x"} = exactly that one (as before); [] = none
 - GET /api/industry and /api/state industry {codes: every industry on, code: the first (old clients)}
 - Film & Video counts as soon as it is among them (was: only as the first built-in pack): a shoot project
   (lists/templates.py PTYPE_INDUSTRY) and the image film sample (onboarding.py SAMPLE_VARIANTS, Film before the others)
 - the first-run setup takes industries too
 - Rueckfall (#5511): Film & Video on, Agency & services added -> both stay on (before: Film fell away)
freelancer-matrix: industry (frida has no organisation: several industries for her own area, her shoot, her sample)
usage: p2828_a_industry_test.py <datadir>"""
import sys

import kt
from kt import B, check
from freelancer_fixture import freelancer

A = kt.setup()
FEATS = "cal,timeline,matrix,collab,time,progress,deps,fields,office,clients"
A.patch(B + "/api/settings", json={"features": FEATS})
FILM = "Example: Promo film for Example Ltd"


def ind(s):
    return s.get(B + "/api/state").json().get("industry") or {}


def packs(s):
    return s.get(B + "/api/office/settings").json()["settings"].get("industry_packs")


# ================================================================== the regression: Film on, Agency added -> both on
r = A.put(B + "/api/industry", json={"industries": ["film"]})
check(r.ok and r.json()["industry"]["codes"] == ["film"] and r.json()["industry"]["code"] == "film", "Film & Video on " + r.text[:160])
r = A.put(B + "/api/industry", json={"industries": ["film", "agency"], "expect_updated_at": r.json()["industry"]["updated_at"]})
check(r.ok and r.json()["changed"] is True and sorted(r.json()["industry"]["codes"]) == ["agency", "film"],
      "Agency & services added: Film & Video stays on " + r.text[:200])
check(sorted(packs(A)) == ["agency", "film"], "one truth: both packs on in Office > Packs " + str(packs(A)))
check(sorted(A.get(B + "/api/industry").json()["industry"]["codes"]) == ["agency", "film"], "GET /api/industry: both")
check(A.put(B + "/api/industry", json={"industries": ["agency", "film"]}).json().get("changed") is False, "the same set again: nothing changes")

# a pack switched on under Office > Packs stays when the field changes another one (own packs: the same rule, not built in)
check(A.put(B + "/api/office/settings", json={"industry_packs": ["film"]}).ok and packs(A) == ["film"], "Office > Packs: film only")
r = A.put(B + "/api/industry", json={"industries": ["film", "agency"]})
check(r.ok and packs(A) == ["film", "agency"], "only the change applied: agency added at the end, film stays " + str(packs(A)))
r = A.put(B + "/api/industry", json={"industries": ["agency"]})
check(r.ok and packs(A) == ["agency"] and r.json()["industry"]["codes"] == ["agency"], "film unticked: only film goes " + str(packs(A)))

# the old form: exactly that one (as before 2.828), "" / [] = none; checks
r = A.put(B + "/api/industry", json={"industry": "film"})
check(r.ok and packs(A) == ["film"] and r.json()["industry"]["codes"] == ["film"], "old form industry: film = exactly film " + str(packs(A)))
check(A.put(B + "/api/industry", json={"industries": ["film", "bakery"]}).status_code == 400, "an unknown code in industries: 400")
check(A.put(B + "/api/industry", json={"industries": [3]}).status_code == 400, "a number in industries: 400")
check(A.put(B + "/api/industry", json={"industries": "film"}).status_code == 400, "industries not a list (no industry either): 400")
check(packs(A) == ["film"], "nothing changed by the refused ones")
r = A.put(B + "/api/industry", json={"industries": []})
check(r.ok and packs(A) == [] and r.json()["industry"]["codes"] == [] and r.json()["industry"]["code"] == "", "none ticked: no industry")
at = ind(A)["updated_at"]
A.put(B + "/api/office/settings", json={"industry_packs": ["agency"]})
r = A.put(B + "/api/industry", json={"industries": ["film"], "expect_updated_at": at})
check(r.status_code == 409 and r.json().get("industry", {}).get("codes") == ["agency"], "a stale version: 409 with the current " + r.text[:160])

# ================================================================== Film & Video among several, not the first: its functions hold
check(A.put(B + "/api/office/settings", json={"industry_packs": ["agency", "film"]}).ok, "agency first, film second")
check(ind(A).get("code") == "agency" and ind(A).get("codes") == ["agency", "film"], "state: code = the first, codes = both " + str(ind(A)))
r = A.post(B + "/api/lists", json={"name": "Shoot with two industries", "ptype": "shoot", "sections": True})
check(r.ok, f"a shoot with Film & Video as the second industry (before: 400) {r.status_code} {r.text[:120]}")
A.delete(B + "/api/sample")
r = A.post(B + "/api/sample", json={})
names = [x["name"] for x in (A.get(B + "/api/state").json().get("sample") or {}).get("lists", [])]
check(r.ok and FILM in names, "the image film sample with Film & Video second " + str(names))
A.delete(B + "/api/sample")

# ================================================================== the first-run setup takes several
r = A.post(B + "/api/admin/setup", json={"lang": "en", "modules": FEATS.split(","), "industries": ["film", "agency"]})
check(r.ok and sorted(ind(A).get("codes") or []) == ["agency", "film"], "setup {industries: [film, agency]} " + r.text[:120])
check(A.post(B + "/api/admin/setup", json={"lang": "en", "modules": FEATS.split(","), "industries": ["x"]}).status_code == 400, "setup: unknown industry 400")

# ================================================================== a person without organisation (freelancer-matrix: industry)
FID, Fr = freelancer(B, A)
check(ind(Fr).get("codes") == [] and ind(Fr).get("can_set") is True, "frida: no industry, chooses for herself " + str(ind(Fr)))
r = Fr.put(B + "/api/industry", json={"industries": ["film"]})
r = Fr.put(B + "/api/industry", json={"industries": ["film", "agency"]})
check(r.ok and sorted(r.json()["industry"]["codes"]) == ["agency", "film"], "frida: Film & Video + Agency & services " + r.text[:160])
check(sorted(Fr.get(B + "/api/office/settings").json()["settings"]["industry_packs"]) == ["agency", "film"], "frida: both packs in her office")
r = Fr.post(B + "/api/lists", json={"name": "Frida's shoot", "ptype": "shoot", "sections": True})
check(r.ok, f"frida: her shoot with both industries {r.status_code}")
check(sorted(ind(A).get("codes") or []) == ["agency", "film"] and Fr.put(B + "/api/industry", json={"industries": []}).ok
      and sorted(ind(A).get("codes") or []) == ["agency", "film"], "frida's choice is hers only")

sys.exit(kt.done("p2828_a_industry"))
