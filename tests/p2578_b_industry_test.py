#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.578.0 B (#4573): the industry is one switch for the whole app (decided 04.11.2026, default: none).
 - one read point (accounts/onboarding.py app_industry): GET /api/industry and /api/state industry {code, can_set, choices,
   updated_at}; the truth is the office setting industry_packs of the person's area (the pack cards of the office switch the
   same list), so nothing is migrated: an area with the film pack on has the industry Film & Video
 - a new account starts without: the neutral sample "Website relaunch" (sections, dependencies, subtasks, budget, time,
   repetition, launch checklist), no shoot calculation in the office (GET /api/office/settings industry empty)
 - Film & Video: the image film sample with its packing list and the shoot calculation
 - PUT /api/industry: an unknown code 400, a stale expect_updated_at 409, the setup's industry
 - a person without organisation chooses for her own area (her personal office, made on the first choice)
 - in an organisation only its admins choose; a member reads it (403 on PUT), gets the organisation's sample; another
   organisation stays without
freelancer-matrix: industry (frida has no organisation: GET / PUT /api/industry for her own area, the sample follows it)
tenant-matrix: industry (Acme's admin chooses, Acme's member 403, Beta stays without)
usage: p2578_b_industry_test.py <datadir>"""
import sys

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer, org_join

A = kt.setup()
FEATS = "cal,timeline,matrix,collab,time,progress,deps,fields,office,clients"
A.patch(B + "/api/settings", json={"features": FEATS})
NEUTRAL, NCHECK = "Example: Website relaunch for client Muster", "Example: Launch checklist"
FILM, FCHECK = "Example: Image film for client Muster", "Example: Shoot day packing list"


def ind(s):
    return s.get(B + "/api/state").json().get("industry") or {}


def sample_names(s):
    sm = s.get(B + "/api/state").json().get("sample") or {}
    return sorted(l["name"] for l in sm.get("lists", []))


def shoot_packs(s):
    """The shoot calculation packs the office offers (GET /api/office/settings industry): empty = no shoot calculation."""
    r = s.get(B + "/api/office/settings")
    return [p["code"] for p in (r.json().get("industry") or [])] if r.ok else None


# ================================================================== a new account: no industry, the neutral sample
i0 = ind(A)
check(i0.get("code") == "" and i0.get("can_set") is True, "new account: no industry, may choose " + str(i0))
check([c["code"] for c in i0.get("choices", [])] == ["film"] and i0["choices"][0]["name"] == "Film & Video", "choices: Film & Video " + str(i0.get("choices")))
check(A.get(B + "/api/industry").json().get("industry", {}).get("code") == "", "GET /api/industry: the same")
r = A.post(B + "/api/sample", json={})
check(r.ok and r.json().get("created"), "sample created " + r.text[:120])
S = A.get(B + "/api/state").json()
check(sample_names(A) == sorted([NEUTRAL, NCHECK]), "no industry: the website relaunch + its checklist " + str(sample_names(A)))
L = next(l for l in S["lists"] if l["name"] == NEUTRAL)
secs = [s["name"] for s in S["sections"] if s["list_id"] == L["id"]]
check(secs == ["Concept", "Design", "Build", "Test", "Approval"], "neutral sections " + str(secs))
TT = [t for t in S["tasks"] if t["list_id"] == L["id"]]
by = {t["title"]: t for t in TT}
check(S["sample"]["tasks"] == 26 and len(TT) == 18, f"26 sample tasks (15 + 3 subtasks + 8 checklist items): {S['sample']['tasks']} / {len(TT)}")
check(by["Weekly status call with the client"]["repeat"].startswith("FREQ=WEEKLY"), "the repeating task")
check(by["Content workshop with the client"]["duration"] == 180, "a timed appointment with a duration")
check(any(t.get("parent_id") == by["Write the concept and sitemap"]["id"] for t in TT), "subtasks below the concept")
check(not any(x in t["title"] for t in S["tasks"] for x in ("Shoot", "treatment", "Rough cut")), "nothing of the film sample")
deps = kt.dbx("SELECT COUNT(*) FROM task_deps WHERE task_id IN (SELECT item_id FROM sample_items WHERE kind='task')")[0][0]
check(deps == 4, f"4 dependencies ({deps})")
te = A.get(B + "/api/time/entries?scope=mine").json()
check(any(e.get("note") == "First draft of the sitemap" for e in te.get("entries", [])), "the time entry of the neutral sample")
check(shoot_packs(A) == [], "no industry: no shoot calculation in the office " + str(shoot_packs(A)))
check(A.delete(B + "/api/sample").ok, "neutral sample removed")

# ================================================================== PUT /api/industry: checks, Film & Video
check(A.put(B + "/api/industry", json={"industry": "bakery"}).status_code == 400, "unknown industry: 400")
check(A.put(B + "/api/industry", json={}).status_code == 400, "no industry in the body: 400")
r = A.put(B + "/api/industry", json={"industry": "film"})
check(r.ok and r.json()["changed"] is True and r.json()["industry"]["code"] == "film", "Film & Video chosen " + r.text[:160])
at = r.json()["industry"]["updated_at"]
check(ind(A).get("code") == "film" and at, "state: film, with the version")
check(A.put(B + "/api/industry", json={"industry": "film"}).json().get("changed") is False, "the same again: nothing changes")
st_off = A.get(B + "/api/office/settings").json()["settings"]
check(st_off["industry_packs"] == ["film"], "one truth: the office setting industry_packs " + str(st_off["industry_packs"]))
check(shoot_packs(A) == ["film"], "Film & Video: the shoot calculation is offered")
r = A.post(B + "/api/sample", json={})
check(r.ok and sample_names(A) == sorted([FILM, FCHECK]), "Film & Video: the image film + packing list " + str(sample_names(A)))
check(A.get(B + "/api/state").json()["sample"]["tasks"] == 27, "the film sample as before (27 tasks)")
A.delete(B + "/api/sample")
# the office's pack card switches the same list: off there = no industry (the old way keeps working)
r = A.put(B + "/api/office/settings", json={"industry_packs": []})
check(r.ok and ind(A).get("code") == "", "pack card off: the industry is none " + str(ind(A)))
r = A.put(B + "/api/industry", json={"industry": "film", "expect_updated_at": at})
check(r.status_code == 409 and r.json().get("industry", {}).get("code") == "", "a stale version: 409 with the current " + r.text[:160])
# an area that had the film pack on before this version (switched on by the pack card) keeps its industry: no migration needed
check(A.put(B + "/api/office/settings", json={"industry_packs": ["film"]}).ok and ind(A).get("code") == "film", "the film pack on = Film & Video (existing accounts keep it)")
# the first-run setup takes the industry too (here: back to none with "", then film)
r = A.put(B + "/api/industry", json={"industry": ""})
check(r.ok and r.json()["industry"]["code"] == "" and A.get(B + "/api/office/settings").json()["settings"]["industry_packs"] == [], "back to none")
r = A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": FEATS.split(","), "industry": "film"})
check(r.ok and ind(A).get("code") == "film", "setup {industry: film} " + r.text[:120])
check(A.post(B + "/api/admin/setup", json={"lang": "en", "modules": FEATS.split(","), "industry": "x"}).status_code == 400, "setup: unknown industry 400")

# ================================================================== a person without organisation (freelancer-matrix: industry)
FID, Fr = freelancer(B, A)
fi = Fr.get(B + "/api/industry").json()["industry"]
check(fi["code"] == "" and fi["can_set"] is True, "frida: new, no industry, chooses for herself " + str(fi))
r = Fr.post(B + "/api/sample", json={})
check(r.ok and sample_names(Fr) == sorted([NEUTRAL, NCHECK]), "frida: the neutral sample " + str(sample_names(Fr)))
Fr.delete(B + "/api/sample")
r = Fr.put(B + "/api/industry", json={"industry": "film"})
check(r.ok and r.json()["industry"]["code"] == "film", "frida: Film & Video for her own area " + r.text[:160])
check(kt.dbx("SELECT COUNT(*) FROM orgs WHERE personal_of=?", (FID,))[0][0] == 1, "frida: her personal office (made on the first choice, if not yet there)")
check(Fr.get(B + "/api/office/settings").json()["settings"]["industry_packs"] == ["film"], "frida: her office has the film pack")
r = Fr.post(B + "/api/sample", json={})
check(r.ok and sample_names(Fr) == sorted([FILM, FCHECK]), "frida: the image film " + str(sample_names(Fr)))
check(ind(A).get("code") == "film" and Fr.put(B + "/api/industry", json={"industry": ""}).ok and ind(A).get("code") == "film", "frida's choice is hers only")

# ================================================================== organisations (tenant-matrix: industry)
mk = lambda name, **kw: A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": kt.PASSWORD, "email": f"{name}@example.com", **kw}).json()["id"]  # noqa: E731
OL = mk("olive", orgs=[])
OID = A.post(B + "/api/admin/orgs", json={"name": "Acme", "admin_id": OL}).json()["id"]
BE = mk("bea", orgs=[])
BID = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": BE}).json()["id"]
mk("tom", orgs=[OID])
Ol, Tm, Be = sess("olive"), sess("tom"), sess("bea")
for s in (Ol, Tm, Be):
    s.patch(B + "/api/settings", json={"features": FEATS, "tour": "done"})
check(ind(Ol).get("code") == "" and ind(Ol).get("can_set") is True, "Acme's admin: no industry yet, may choose " + str(ind(Ol)))
check(ind(Tm).get("code") == "" and ind(Tm).get("can_set") is False, "Acme's member: reads, may not choose " + str(ind(Tm)))
r = Tm.put(B + "/api/industry", json={"industry": "film"})
check(r.status_code == 403, f"member: PUT 403 ({r.status_code})")
r = Tm.post(B + "/api/sample", json={})
check(r.ok and sample_names(Tm) == sorted([NEUTRAL, NCHECK]), "member, organisation without an industry: the neutral sample " + str(sample_names(Tm)))
Tm.delete(B + "/api/sample")
r = Ol.put(B + "/api/industry", json={"industry": "film"})
check(r.ok and r.json()["industry"]["code"] == "film", "Acme's admin chooses Film & Video " + r.text[:160])
check(ind(Tm).get("code") == "film", "the member sees the organisation's industry")
r = Tm.post(B + "/api/sample", json={})
check(r.ok and sample_names(Tm) == sorted([FILM, FCHECK]), "member of a film organisation: the image film " + str(sample_names(Tm)))
check(shoot_packs(Tm) == ["film"], "member: the shoot calculation of the organisation " + str(shoot_packs(Tm)))
check(ind(Be).get("code") == "" and shoot_packs(Be) == [], "Beta stays without an industry")
check(Be.put(B + "/api/industry", json={"industry": "film"}).ok and ind(Ol).get("code") == "film" and Be.put(B + "/api/industry", json={"industry": ""}).ok
      and ind(Ol).get("code") == "film", "Beta's choice leaves Acme as it is")
# a member who is in two organisations with the workspace "all": no area, no choice (as the office)
check(Be.put(B + f"/api/orgs/{BID}/members", json={"email": "tom@example.com"}).ok and org_join(B, "tom", BID), "setup: tom joins Beta too")
r = Tm.put(B + "/api/industry", json={"industry": ""})
check(r.status_code == 403 and ind(Tm).get("can_set") is False, f"two organisations, no workspace: no choice ({r.status_code})")

sys.exit(kt.done("p2578_b_industry"))
