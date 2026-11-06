#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.576.0 B API tests (#4764): the reads the edit dialogs' version watch uses (objsave.js dlgStale) -- one budget entry, one
budget template, one time entry (now with updated_at) -- for a person without an organisation; another person gets 404 (budget)
or 403 / 404 (time); an entry in the trash is gone (404). The 409 of each dialog's save names the current state under its key.
Own container (kt.fresh). Invented people and figures only.
freelancer-matrix: personal, time
tenant-matrix: budget, own
Regression: before 2.576 these GET routes did not exist (405) and a time entry had no updated_at.
usage: p2576_b_api_test.py <datadir>"""
import kt
from kt import B, check
from freelancer_fixture import freelancer

kt.fresh()
A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "time_all": True})
FID, Fr = freelancer(B, A)
SID, St = freelancer(B, A, "sven")  # the stranger (another person without an organisation)

# ================================================================== budget
L = Fr.post(B + "/api/budget/lists", json={"name": "Household"}).json()["list_id"]
M = Fr.get(B + "/api/budget").json()["month"]
E = Fr.post(B + f"/api/budget/{L}/entries", json={"day": f"{M}-03", "amount": 25, "kind": "out", "title": "Paint"}).json()
R = Fr.post(B + f"/api/budget/{L}/recurring", json={"title": "Rent", "amount": 900, "kind": "out", "per": "month", "start": M}).json()

r = Fr.get(B + f"/api/budget/entries/{E['id']}")
check(r.ok and r.json()["title"] == "Paint" and r.json()["updated_at"] == E["updated_at"], f"the entry reads with its version {r.status_code} {r.text[:200]}")
check(St.get(B + f"/api/budget/entries/{E['id']}").status_code == 404, "another person: 404 on the entry")
r = Fr.patch(B + f"/api/budget/entries/{E['id']}", json={"note": "Kitchen", "expect_updated_at": E["updated_at"]})
check(r.ok, f"changed with the version {r.text[:200]}")
r2 = Fr.get(B + f"/api/budget/entries/{E['id']}").json()
check(r2["note"] == "Kitchen" and r2["updated_at"] != E["updated_at"], "… the read shows the new version (the dialog's watch sees it)")
r = Fr.patch(B + f"/api/budget/entries/{E['id']}", json={"amount": 30, "expect_updated_at": E["updated_at"]})
check(r.status_code == 409 and r.json().get("entry", {}).get("note") == "Kitchen", f"an old version: 409 with the current entry {r.status_code} {r.text[:200]}")

r = Fr.get(B + f"/api/budget/recurring/{R['id']}")
check(r.ok and r.json()["title"] == "Rent" and r.json()["updated_at"] == R["updated_at"], f"the template reads with its version {r.status_code} {r.text[:200]}")
check(St.get(B + f"/api/budget/recurring/{R['id']}").status_code == 404, "another person: 404 on the template")
r = Fr.patch(B + f"/api/budget/recurring/{R['id']}", json={"title": "Rent flat", "expect_updated_at": "2000-01-01T00:00:00"})
check(r.status_code == 409 and r.json().get("item", {}).get("title") == "Rent", f"an old version: 409 with the current template {r.status_code}")

check(Fr.delete(B + f"/api/budget/entries/{E['id']}").ok, "the entry deleted (into the trash)")
check(Fr.get(B + f"/api/budget/entries/{E['id']}").status_code == 404, "… then the read answers 404")

# ================================================================== time
P = Fr.post(B + "/api/lists", json={"name": "Garden", "kind": "project", "time_tracking": 1}).json()["id"]
T = Fr.post(B + "/api/tasks", json={"title": "Cut the hedge", "list_id": P}).json()["id"]
TE = Fr.post(B + "/api/time/entries", json={"task_id": T, "start": f"{M}-02T09:00", "minutes": 30, "note": "Front"}).json()
check(TE.get("updated_at"), f"a time entry carries updated_at {TE}")
r = Fr.get(B + f"/api/time/entries/{TE['id']}")
check(r.ok and r.json()["note"] == "Front" and r.json()["updated_at"] == TE["updated_at"], f"the time entry reads {r.status_code} {r.text[:200]}")
check(St.get(B + f"/api/time/entries/{TE['id']}").status_code in (403, 404), "another person cannot read it")
r = Fr.patch(B + f"/api/time/entries/{TE['id']}", json={"note": "Front and back", "_prev": {"note": "Front"}})
check(r.ok and r.json()["updated_at"] != TE["updated_at"], f"a change moves the version {r.text[:200]}")
r = Fr.patch(B + f"/api/time/entries/{TE['id']}", json={"note": "Only front", "_prev": {"note": "Front"}})
check(r.status_code == 409 and r.json().get("entry", {}).get("note") == "Front and back", f"what the dialog showed is old: 409 with the entry {r.status_code}")

raise SystemExit(kt.done("p2576_b_api"))
