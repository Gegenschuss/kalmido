#!/usr/bin/env python3
"""2.144.6 API tests, part B (#2400: office fixes from the review of 2.138), own container (start.sh). Invented data only.
tenant-matrix: office
freelancer-matrix: office
 - F2: raising the invoice counter of the legacy import needs a reason like the number ranges (GoBD): none / too short
   = 400, with a reason it is set and the reason is in the office log; the quotation counter needs none; never lowered
 - F1: undoing a data import puts back the order of the services the import renumbered (only where nobody reordered
   since); the area undo "services" does it, a second undo (409) does not touch it again
 - F3: a list rule "assigned -> assign to X" does not run when someone asks for an approval (the approver keeps the
   task) nor when the approver asks for changes (back to the asker); a normal assignment still runs it
 - F4: "Archive leftover entries" leaves a service / device alone that was restored by hand (PATCH archived 0)
 - a person without an organisation: the same in the personal office and a private list
usage: p21446_b_api_test.py <datadir>      (P21446B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import json
import os
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients"
O, L = "/api/office", "/api/office/legacy"


def by_name(s, kind="services"):
    return {(x.get("name_de") or x.get("name")): x for x in s.get(B + O + f"/{kind}?archived=1").json()["items"]}


def imp(s, svc=(), eq=()):
    """An import of invented rows (action new, the file's order = sort) -> run id."""
    rows = [{"row": i + 2, "name_de": n, "sort": i + 1, "daily_rate": 100 + i, "action": "new"} for i, n in enumerate(svc)]
    eqs = [{"row": i + 2, "name": n, "daily_rate": 20 + i, "action": "new"} for i, n in enumerate(eq)]
    r = s.post(B + L + "/import", json={"services": rows, "equipment": eqs})
    assert r.status_code == 201, r.text
    return r.json()["run_id"]


def offer(s, title, sids):
    r = s.post(B + O + "/docs", json={"kind": "offer", "project_title": title})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.put(B + O + f"/docs/{did}/items", json={"items": [{"kind": "service", "service_id": sid, "qty": 1} for sid in sids]})
    assert r.ok, r.text
    return did


def run_of(s, rid):
    return next((x for x in s.get(B + L + "/runs").json()["runs"] if x["id"] == rid), {})


# ---------------------------------------------------------------- setup: two organisations, an admin, a member
if os.environ.get("P21446B_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
for e in ("bob@example.com", "carol@example.com"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": e, "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})


# ================================================================ F2: the legacy counter needs a reason
def part_counter(S, who):
    cur = S.get(B + L + "/counter").json()
    last = cur["invoice"]["last"]
    r = S.post(B + L + "/counter", json={"kind": "invoice", "last": last + 40})
    check(r.status_code == 400 and "reason" in r.text, f"{who} F2: raising the invoice counter without a reason = 400 {r.status_code} {r.text[:200]}")
    r = S.post(B + L + "/counter", json={"kind": "invoice", "last": last + 40, "reason": "abc"})
    check(r.status_code == 400, f"{who} F2: a reason too short = 400 {r.status_code}")
    check(S.get(B + L + "/counter").json()["invoice"]["last"] == last, f"{who} F2: nothing changed")
    why = f"Old invoices up to {last + 40} ({who})"
    r = S.post(B + L + "/counter", json={"kind": "invoice", "last": last + 40, "reason": why})
    check(r.ok and r.json()["last"] == last + 40, f"{who} F2: with a reason it is set {r.status_code} {r.text[:200]}")
    log = S.get(B + O + "/log?limit=50").json().get("log", [])
    check(any(x.get("action") == "number" and x.get("target") == "legacy" and why in json.dumps(x, ensure_ascii=False) for x in log),
          f"{who} F2: the reason is in the office log")
    r = S.post(B + L + "/counter", json={"kind": "invoice", "last": last + 10, "reason": why})
    check(r.status_code == 400, f"{who} F2: never lowered (400)")
    r = S.post(B + L + "/counter", json={"kind": "offer", "last": S.get(B + L + "/counter").json()["offer"]["last"] + 5})
    check(r.ok, f"{who} F2: the quotation counter needs no reason {r.status_code} {r.text[:200]}")


part_counter(A, "org")
check(Bo.post(B + L + "/counter", json={"kind": "invoice", "last": 999, "reason": "A member tries"}).status_code == 403, "rights: a member cannot set the counter (403)")
check(Ca.get(B + L + "/counter").json()["invoice"]["last"] == 0, "tenant-matrix: office -- the other organisation's counter is untouched")


# ================================================================ F1: undo puts the services' old order back
def part_order(S, who):
    made = {}
    for n, srt in (("Zeta Dreh", 30), ("Alpha Schnitt", 10), ("Mitte Ton", 20)):
        r = S.post(B + O + "/services", json={"name_de": n, "sort": srt})
        check(r.status_code == 201, f"{who} setup: service " + r.text[:200])
        made[n] = r.json()["id"]
    before = {n: x["sort"] for n, x in by_name(S).items() if n in made}
    # the file names an existing service first: the import renumbers everything 1..n
    rows = [{"row": 2, "name_de": "Zeta Dreh", "sort": 1, "action": "skip"}, {"row": 3, "name_de": f"Neu {who}", "sort": 2, "daily_rate": 50, "action": "new"}]
    r = S.post(B + L + "/import", json={"services": rows})
    check(r.status_code == 201, f"{who} F1: import " + r.text[:200])
    rid = r.json().get("run_id")
    mid = {n: x["sort"] for n, x in by_name(S).items() if n in made}
    check(mid != before and mid["Zeta Dreh"] < mid["Alpha Schnitt"], f"{who} F1: the import renumbered the existing services {mid}")
    S.patch(B + O + f"/services/{made['Mitte Ton']}", json={"sort": 99})  # reordered by hand after the import: stays
    r = S.post(B + L + f"/runs/{rid}/undo", json={"kinds": ["services"]})
    check(r.ok, f"{who} F1: undo services " + r.text[:200])
    after = {n: x["sort"] for n, x in by_name(S).items() if n in made}
    check(after["Zeta Dreh"] == before["Zeta Dreh"] and after["Alpha Schnitt"] == before["Alpha Schnitt"] and after["Mitte Ton"] == 99,
          f"{who} F1: the old order is back, a later change by hand stays {before} -> {after}")
    check(f"Neu {who}" not in by_name(S), f"{who} F1: the new service is gone")
    S.patch(B + O + f"/services/{made['Zeta Dreh']}", json={"sort": 5})
    r = S.post(B + L + f"/runs/{rid}/undo", json={"kinds": ["services"]})
    check(r.status_code == 409 and by_name(S)["Zeta Dreh"]["sort"] == 5, f"{who} F1: a second undo does not touch the order again {r.status_code}")
    for i in made.values():
        S.delete(B + O + f"/services/{i}")


part_order(A, "org")


# ================================================================ F4: a restored entry is no leftover
def part_tidy(S, who):
    rid = imp(S, [f"Rest {who} A", f"Rest {who} B"], [f"Gerät {who}"])
    sv, eq = by_name(S), by_name(S, "equipment")
    offer(S, f"Probe {who}", [sv[f"Rest {who} A"]["id"], sv[f"Rest {who} B"]["id"]])
    S.post(B + O + "/sets", json={"name": f"Set {who}", "items": [{"equipment_id": eq[f"Gerät {who}"]["id"], "qty": 1}]})
    r = S.post(B + L + f"/runs/{rid}/undo")
    check(r.ok and len(r.json().get("archived", [])) == 3, f"{who} F4 setup: undo archives the three used entries " + r.text[:300])
    r = S.patch(B + O + f"/services/{sv[f'Rest {who} A']['id']}", json={"archived": 0})
    check(r.ok and r.json()["archived"] == 0, f"{who} F4: restore = archived 0")
    S.patch(B + O + f"/equipment/{eq[f'Gerät {who}']['id']}", json={"archived": 0})
    check(run_of(S, rid).get("leftover") == 0, f"{who} F4: restored by hand = no leftover {run_of(S, rid)}")
    r = S.post(B + L + f"/runs/{rid}/tidy")
    check(r.ok and r.json().get("archived") == [], f"{who} F4: tidy archives nothing " + r.text[:300])
    sv, eq = by_name(S), by_name(S, "equipment")
    check(sv[f"Rest {who} A"]["archived"] == 0 and eq[f"Gerät {who}"]["archived"] == 0 and sv[f"Rest {who} B"]["archived"] == 1,
          f"{who} F4: the restored entries stay active, the other stays archived")
    return rid


RUN_T = part_tidy(A, "org")
check(Ca.post(B + L + f"/runs/{RUN_T}/tidy").status_code == 404, "tenant-matrix: office -- another organisation's run = 404")


# ================================================================ F3: an approval is no "assigned" for the list rules
def part_rules(S, who, org, other, other_s):
    r = S.post(B + "/api/lists", json={"name": f"Team {who}", "org_id": org})
    assert r.ok, r.text
    lid = r.json()["id"]
    for e in ("bob@example.com", "carol@example.com"):  # by address: a person without an organisation sees nobody's id
        S.put(B + f"/api/lists/{lid}/members", json={"email": e, "role": "edit"})
    r = S.post(B + f"/api/lists/{lid}/rules", json={"name": "To carol", "trigger": {"kind": "assigned"}, "action": {"kind": "assign", "user_id": CAROL}})
    check(r.status_code == 201, f"{who} F3: rule assigned -> carol {r.status_code} {r.text[:200]}")

    def task(title):
        r = S.post(B + "/api/tasks", json={"title": title, "list_id": lid})
        assert r.ok, r.text
        return r.json()["id"]

    def assignee(tid):
        return S.get(B + f"/api/tasks/{tid}").json().get("assignee_id")

    t1 = task("Needs a yes")
    r = S.post(B + f"/api/tasks/{t1}/approval", json={"action": "request", "approver_id": other})
    check(r.ok and assignee(t1) == other, f"{who} F3: asking for an approval keeps the approver as assignee ({r.status_code} {assignee(t1)})")
    r = other_s.post(B + f"/api/tasks/{t1}/approval", json={"action": "changes", "note": "Please add the date"})
    me = S.get(B + "/api/state").json()["me"]["id"]
    check(r.ok and assignee(t1) == me, f"{who} F3: changes go back to the asker, no rule runs ({r.status_code} {assignee(t1)})")
    t2 = task("Plain")
    S.patch(B + f"/api/tasks/{t2}", json={"assignee_id": other})
    check(assignee(t2) == CAROL, f"{who} F3: a normal assignment still runs the rule ({assignee(t2)})")


part_rules(A, "org", ORG, BOB, Bo)

# ================================================================ a person without an organisation (personal office, private list)
# freelancer-matrix: office
FID, Fr = freelancer(B, A)
part_counter(Fr, "freelancer")
part_order(Fr, "freelancer")
part_tidy(Fr, "freelancer")
check(Fr.post(B + L + f"/runs/{RUN_T}/tidy").status_code == 404, "freelancer: no way into the organisation's runs")
part_rules(Fr, "freelancer", None, BOB, Bo)

print(f"p21446_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
