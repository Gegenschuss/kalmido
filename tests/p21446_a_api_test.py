#!/usr/bin/env python3
"""2.144.6 API tests, part A (#2053): time entries to an invoice -- billable / billed, never twice. Own container
(start.sh), invented names only.
 - an entry is billable by default; billable false on create and by PATCH; GET /api/office/time-open: open / billed / not
   billable hours of the period
 - "invoice from time" takes only the open billable entries and binds them (billed: the draft); the answer's "time"
   counts taken / skipped; a second call takes nothing (skipped as billed)
 - a billed entry: duration / date / task / billable 409, delete 409, the note can change; an unchanged billable passes
 - deleting the draft frees the entries; two parallel calls never bill the same entry twice
 - a cancelled invoice: a member cannot release (403), the admin releases, the undo binds them again; a draft: 409
 - an entry bound to a document that no longer exists (an older version deleted it) is open again
 - somebody else cannot change the entry (403); another organisation: time-open / release 404 (tenant-matrix: office);
   an agent: 403
 - a person without an organisation (freelancer-matrix: office): the personal office bills the private lists the same way
 - API v1: billable / billed on the entries, billable settable, OpenAPI fields
usage: p21446_a_api_test.py <datadir>      (a fresh container; P21446A_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys
import threading

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "clients,office,time"
O = "/api/office"
D = O + "/docs"
T = "/api/time/entries"
P = {"from": "2026-05-01", "to": "2026-05-31"}


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


def dbx(sql, args=()):
    return dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10).execute(sql, args).fetchall()


def entry(s, eid):
    return next((e for e in s.get(B + T, params={"from": "2026-05-01", "to": "2026-05-31"}).json()["entries"] if e["id"] == eid), None)


def add(s, lid, start, minutes, **kw):
    r = s.post(B + T, json={"list_id": lid, "start": start, "minutes": minutes, **kw})
    assert r.ok, r.text
    return r.json()


def opened(s, cid):
    r = s.get(B + O + "/time-open", params={"client_id": cid, **P})
    assert r.ok, r.text
    return r.json()


if not os.environ.get("P21446A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u == "bob" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["carl"]})
assert r.status_code in (200, 201), r.text
Bo, Ca = sess("bob"), sess("carl")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write", "time"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}

r = A.post(B + "/api/clients", json={"name": "Nordwind GmbH", "org_id": ORG, "rate": 80})
assert r.status_code == 201, r.text
CL = r.json()["id"]
r = A.post(B + "/api/lists", json={"name": "Projekt Hafen", "org_id": ORG, "time_tracking": True})
assert r.ok, r.text
LID = r.json()["id"]
r = A.patch(B + f"/api/lists/{LID}", json={"client_id": CL})
check(r.ok, "setup: the list belongs to the client " + r.text[:120])
r = A.post(B + f"/api/lists/{LID}/members", json={"user_id": uid["bob"], "role": "editor"})

# ---------------------------------------------------------------- billable by default, switch, the open hours
E1 = add(A, LID, "2026-05-04T08:00:00Z", 120, note="Schnitt")
E2 = add(A, LID, "2026-05-05T08:00:00Z", 60, billable=False)
check(E1["billable"] is True and E1["billed"] is None, f"a new entry is billable, not billed: {E1.get('billable')} {E1.get('billed')}")
check(E2["billable"] is False, "billable false on create")
E3 = add(A, LID, "2026-05-06T08:00:00Z", 30)
r = A.patch(B + f"{T}/{E3['id']}", json={"billable": False})
check(r.ok and r.json()["billable"] is False, "PATCH billable false " + r.text[:120])
check(A.patch(B + f"{T}/{E3['id']}", json={"billable": "maybe"}).status_code == 400, "billable: invalid value 400")
r = A.patch(B + f"{T}/{E3['id']}", json={"billable": True})
check(r.ok and r.json()["billable"] is True, "PATCH billable back to true")
o = opened(A, CL)
check(o["open_seconds"] == 9000 and o["open_entries"] == 2 and o["unbillable_seconds"] == 3600 and o["billed_seconds"] == 0,
      f"time-open before the invoice: {o}")
check(Bo.patch(B + f"{T}/{E1['id']}", json={"billable": False}).status_code in (403, 404), "somebody else cannot switch the entry")

# ---------------------------------------------------------------- invoice from time: takes and binds
r = A.post(B + f"{D}/from-time", json={"client_id": CL, **P})
check(r.status_code == 201, "from-time 201 " + r.text[:160])
INV = r.json()
its = INV.get("items") or []
check(len(its) == 1 and float(its[0]["qty"]) == 2.5 and float(its[0]["rate"]) == 80, f"only the billable hours: {[(x['title'], x['qty']) for x in its]}")
t = INV.get("time") or {}
check(t.get("taken_entries") == 2 and t.get("taken_seconds") == 9000 and t.get("skipped_unbillable") == 1 and t.get("skipped_billed") == 0,
      f"the answer counts taken / skipped: {t}")
check(INV.get("time_billed") == {"entries": 2, "seconds": 9000}, f"the invoice knows its time: {INV.get('time_billed')}")
e = entry(A, E1["id"])
check(e and e["billed"] and e["billed"]["id"] == INV["id"], f"the entry is billed by the draft: {e and e.get('billed')}")
check(entry(A, E2["id"])["billed"] is None, "a not billable entry stays open")
o = opened(A, CL)
check(o["open_seconds"] == 0 and o["billed_seconds"] == 9000 and o["billed_entries"] == 2, f"time-open after the invoice: {o}")

# the lock
for what, body in (("minutes", {"minutes": 30}), ("start", {"start": "2026-05-04T09:00:00Z"}), ("billable", {"billable": False}),
                   ("list", {"list_id": LID + 100000})):
    r = A.patch(B + f"{T}/{E1['id']}", json=body)
    check(r.status_code == 409 and "invoice" in r.json().get("error", ""), f"billed entry: {what} = 409 {r.status_code} {r.text[:120]}")
check(A.delete(B + f"{T}/{E1['id']}").status_code == 409, "billed entry: delete 409")
r = A.patch(B + f"{T}/{E1['id']}", json={"note": "Schnitt, Farbe", "billable": True})
check(r.ok and r.json()["note"] == "Schnitt, Farbe", "billed entry: the note changes (an unchanged billable passes) " + r.text[:120])
check(Bo.patch(B + f"{T}/{E1['id']}", json={"note": "x"}).status_code in (403, 404), "somebody else cannot change the note")

# a second call takes nothing
r = A.post(B + f"{D}/from-time", json={"client_id": CL, **P})
check(r.status_code == 201 and (r.json().get("items") or []) == [] and r.json()["time"]["taken_entries"] == 0
      and r.json()["time"]["skipped_billed"] == 2, "a second call bills nothing twice " + str(r.json().get("time")))
check(A.delete(B + f"{D}/{r.json()['id']}").ok, "the empty draft is deleted")
check(entry(A, E1["id"])["billed"]["id"] == INV["id"], "deleting another draft leaves the entries billed")

# deleting the draft frees them
check(A.delete(B + f"{D}/{INV['id']}").ok, "the draft is deleted")
check(entry(A, E1["id"])["billed"] is None and opened(A, CL)["open_seconds"] == 9000, "deleting the draft frees the entries")

# two parallel calls: every entry once
res = []
th = [threading.Thread(target=lambda: res.append(A.post(B + f"{D}/from-time", json={"client_id": CL, **P}))) for _ in range(2)]
for x in th:
    x.start()
for x in th:
    x.join()
check(all(x.status_code == 201 for x in res), f"parallel calls: both 201 {[x.status_code for x in res]}")
taken = sorted(x.json()["time"]["taken_entries"] for x in res if x.ok)
check(taken == [0, 2], f"parallel calls: the entries land on one invoice only {taken}")
WIN = next(x.json()["id"] for x in res if x.ok and x.json()["time"]["taken_entries"])
for x in res:
    if x.ok and x.json()["id"] != WIN:
        A.delete(B + f"{D}/{x.json()['id']}")

# ---------------------------------------------------------------- a cancelled invoice: release, undo
check(A.post(B + f"{D}/{WIN}/time-release", json={}).status_code == 409, "release on a draft: 409")
dbx("UPDATE office_docs SET status='cancelled', locked_at='2026-06-01T10:00:00', number='RE-2026-901' WHERE id=?", (WIN,))
e = A.patch(B + f"{T}/{E1['id']}", json={"note": "Schnitt"}).json()  # a write: the answer is fresh (the direct change bumped nothing)
check(e["billed"]["number"] == "RE-2026-901", f"the entry shows the invoice number: {e['billed']}")
if e["billed"]["number"] != "RE-2026-901":  # diagnostics
    print("DIAG", dbx("SELECT id, number, status, org_id, locked_at FROM office_docs WHERE id=?", (WIN,)),
          dbx("SELECT id, billed_doc_id FROM time_entries WHERE id=?", (E1["id"],)), flush=True)
check(Bo.post(B + f"{D}/{WIN}/time-release", json={}).status_code == 403, "a member cannot release (403)")
check(Ca.post(B + f"{D}/{WIN}/time-release", json={}).status_code == 404, "tenant-matrix: office -- release of a foreign invoice = 404")
check(requests.post(B + f"{D}/{WIN}/time-release", json={}, headers=AGH).status_code == 403, "agent: release = 403")
r = A.post(B + f"{D}/{WIN}/time-release", json={})
check(r.ok and sorted(r.json()["released"]) == sorted([E1["id"], E3["id"]]) and r.json()["time_billed"]["entries"] == 0, "the admin releases " + r.text[:160])
check(entry(A, E1["id"])["billed"] is None, "released: the entry is open")
r = A.post(B + f"{D}/{WIN}/time-release", json={"undo": [E1["id"], E3["id"], E2["id"] + 999999]})
check(r.ok and r.json()["time_billed"]["entries"] == 2, "the undo binds them again " + r.text[:160])
check(entry(A, E1["id"])["billed"]["id"] == WIN, "after the undo the entry is billed again")
check(A.post(B + f"{D}/{WIN}/time-release", json={"undo": "x"}).status_code == 400, "undo: invalid ids 400")
check(A.delete(B + f"{D}/{WIN}").status_code == 409, "a finalised invoice cannot be deleted (the entries stay billed)")
# 2.144.6 (#2053, review): someone else who sees the entry (list member) gets "billed" without the invoice id / number
for q in (None, {"user": "all"}, {"list_id": LID}):
    eb = next((x for x in Bo.get(B + T, params={**P, **(q or {})}).json().get("entries", []) if x["id"] == E1["id"]), None)
    if eb is not None:
        check(eb["billed"] and eb["billed"]["id"] is None and eb["billed"]["number"] == "", f"a list member sees billed without the number: {eb['billed']}")
        break

# ---------------------------------------------------------------- a vanished document frees the entry
E4 = add(A, LID, "2026-05-07T08:00:00Z", 45)
dbx("UPDATE time_entries SET billed_doc_id=987654321, billed_at='2026-05-08T00:00:00' WHERE id=?", (E4["id"],))
r = A.patch(B + f"{T}/{E4['id']}", json={"minutes": 50})
check(r.ok and r.json()["seconds"] == 3000 and r.json()["billed"] is None, "an entry of a vanished document is open again " + r.text[:120])

# ---------------------------------------------------------------- another organisation, agents
check(Ca.get(B + O + "/time-open", params={"client_id": CL, **P}).status_code == 404, "tenant-matrix: office -- time-open with a foreign client = 404")
check(requests.get(B + O + "/time-open", params={"client_id": CL, **P}, headers=AGH).status_code == 403, "agent: time-open = 403")
check(A.get(B + O + "/time-open", params={"client_id": CL, "from": "2026-05-31", "to": "2026-05-01"}).status_code == 400, "time-open: period validated")
check(A.get(B + O + "/time-open", params={"client_id": "x", **P}).status_code == 400, "time-open: invalid client 400")

# ---------------------------------------------------------------- API v1
V = B + "/api/v1"
r = requests.get(V + "/openapi.json", headers=AGH)
spec = r.json() if r.ok else {}
props = spec.get("components", {}).get("schemas", {}).get("TimeEntry", {}).get("properties", {})
check("billable" in props and "billed" in props, f"OpenAPI: TimeEntry has billable / billed {sorted(props)[:20]}")
inp = spec.get("components", {}).get("schemas", {}).get("TimeEntryInput", {}).get("properties", {})
check("billable" in inp, "OpenAPI: TimeEntryInput has billable")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
r = Fr.post(B + "/api/clients", json={"name": "Suedlicht AG", "org_id": None, "rate": 100})
assert r.status_code == 201, r.text
FCL = r.json()["id"]
r = Fr.post(B + "/api/lists", json={"name": "Eigenes Projekt", "time_tracking": True})
assert r.ok, r.text
FL = r.json()["id"]
check(Fr.patch(B + f"/api/lists/{FL}", json={"client_id": FCL}).ok, "freelancer: the private list belongs to the private client")
F1 = add(Fr, FL, "2026-05-04T08:00:00Z", 90)
F2 = add(Fr, FL, "2026-05-05T08:00:00Z", 30, billable=False)
o = opened(Fr, FCL)
check(o["open_seconds"] == 5400 and o["unbillable_seconds"] == 1800, f"freelancer: time-open {o}")
r = Fr.post(B + f"{D}/from-time", json={"client_id": FCL, **P})
check(r.status_code == 201 and len(r.json().get("items") or []) == 1 and float(r.json()["items"][0]["qty"]) == 1.5,
      "freelancer: the invoice from time has the private list's billable hours " + r.text[:200])
FD = r.json()["id"] if r.ok else 0
check(entry(Fr, F1["id"])["billed"]["id"] == FD and entry(Fr, F2["id"])["billed"] is None, "freelancer: the entry is billed")
check(Fr.patch(B + f"{T}/{F1['id']}", json={"minutes": 10}).status_code == 409, "freelancer: billed entry locked (409)")
r = Fr.post(B + f"{D}/from-time", json={"client_id": FCL, **P})
check(r.status_code == 201 and r.json()["time"]["taken_entries"] == 0, "freelancer: a second call takes nothing")
Fr.delete(B + f"{D}/{r.json()['id']}")
check(Fr.post(B + f"{D}/{FD}/time-release", json={}).status_code == 409, "freelancer: release only on a cancelled invoice (409)")
check(Fr.delete(B + f"{D}/{FD}").ok and entry(Fr, F1["id"])["billed"] is None, "freelancer: deleting the draft frees the entry")
check(A.get(B + O + "/time-open", params={"client_id": FCL, **P}).status_code == 404, "the freelancer's private client stays private (404)")
r = Fr.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "time"]})
check(r.ok, "freelancer: an API token " + r.text[:120])
FH = {"Authorization": "Bearer " + (r.json().get("token") or "") if r.ok else "", **H}
r = requests.get(V + "/time/entries", params={"from": "2026-05-01", "to": "2026-05-31"}, headers=FH)
v = {x["id"]: x for x in (r.json().get("data") or [])} if r.ok else {}
check(v.get(F2["id"], {}).get("billable") is False and v.get(F1["id"], {}).get("billed") is False, f"v1: billable / billed on the entries {r.status_code} {v.get(F2['id'])}")
r = requests.post(V + "/time/entries", json={"list_id": FL, "start": "2026-05-08T08:00:00Z", "minutes": 15, "billable": False}, headers=FH)
check(r.status_code == 201 and r.json().get("billable") is False, "v1: billable false on create " + r.text[:160])
V1E = r.json().get("id") if r.ok else 0
r = requests.patch(V + f"/time/entries/{V1E}", json={"billable": True}, headers=FH)
check(r.ok and r.json().get("billable") is True, "v1: PATCH billable " + r.text[:160])

print(f"p21446_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
