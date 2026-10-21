#!/usr/bin/env python3
"""2.125.0 API tests, part A (#2118 working days per person, #2117 vacation account + vacation requests). Invented names only.
 - working days (setting workdays): validated; the workload spreads the weekly hours over them and takes absent working days
   off (a day off on a non-working day costs nothing); without the setting exactly Monday..Friday as before; the time gaps
   ("maybe forgotten") look only at the person's working days; an organisation's admin sets them for members (a member not
   for others, another organisation's admin 404)
 - vacation account: entitlement + carry-over per person / area / year (the area's admins; a freelancer for themselves),
   taken = approved vacation working days (half days 0.5, public holidays of the state and non-working days not counted,
   only the part within the year), requested = open requests, rest
 - requests: off by default (a member's vacation is approved at once, as before); switched on, a member's own vacation is a
   request: the team, the workload, the assign check and agents do not count it as away; the admins get a News item; only
   the area's admins decide (a member 403, another organisation 404); approve / reject (note) / reopen (Undo); a changed
   rejected request asks again; sick leave never needs an approval; switched off again: approved at once
 - a person without an organisation: own account, never a request
 - rollback: only new columns (with defaults) and a new table; a row written like 2.124 does is approved
tenant-matrix: hub
freelancer-matrix: hub
usage: p2125_a_api_test.py <datadir>      (a fresh container; the suite restarts it in mode workspaces)"""
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402; 2.148.1 (#2480): an invited member accepts

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


if not os.environ.get("P2125A_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = ids["bob"], ids["carol"], ids["dave"], ids["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
check((Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG)), "setup: carol joins Alpha")
check((Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "erin@example.com"}).ok and org_join(B, "erin", ORG)), "setup: erin joins Alpha")
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?,?)) OR (org_id=? AND user_id!=?)",
    (ORG, BOB, CAROL, ERIN, ORG2, DAVE), write=True)
FID, Fr = freelancer(B, A)
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "collab,workload,time"})

# ---- rollback: new columns with defaults, a new table
cols = {r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_name='hub_absences'")}
check({"status", "decided_by", "decided_at", "decision_note"} <= cols, f"new columns of hub_absences ({sorted(cols)})")
check(dbx("SELECT 1 FROM information_schema.columns WHERE table_name='orgs' AND column_name='hub_leave_approval'"), "new column orgs.hub_leave_approval")
check(dbx("SELECT 1 FROM information_schema.tables WHERE table_name='hub_leave_quota'"), "new table hub_leave_quota")
dbx("INSERT INTO hub_absences(org_id,user_id,kind,start_date,end_date,half_day,note,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
    (ORG, BOB, "off", "2025-01-02", "2025-01-02", "", "", BOB, "2025-01-01T00:00:00+00:00"), write=True)
check(dbx("SELECT status FROM hub_absences WHERE user_id=? AND start_date='2025-01-02'", (BOB,))[0][0] == "approved",
      "a row written like 2.124 (no status) is approved")

# ======================================================================== #2118 working days
check(Ca.patch(B + "/api/settings", json={"workdays": "7"}).status_code == 400, "#2118: workdays 7 is invalid")
check(Ca.patch(B + "/api/settings", json={"workdays": "x,1"}).status_code == 400, "#2118: workdays x is invalid")
check(Ca.patch(B + "/api/settings", json={"workdays": "3,0,1,2,2"}).ok, "#2118: carol works Monday..Thursday (own setting)")
j = Ca.get(B + "/api/team/leave").json()
me_ = next(p for p in j["people"] if p["id"] == CAROL)
check(me_["workdays"] == [0, 1, 2, 3], f"#2118: stored sorted, without doubles ({me_['workdays']})")
check(Ca.patch(B + "/api/settings", json={"workdays": "0,1,2,3,4"}).ok, "#2118: back to the default")
check(not dbx("SELECT value FROM user_settings WHERE user_id=? AND key='workdays' AND value!=''", (CAROL,)), "#2118: Monday..Friday is stored as the default ('')")
# an admin sets them for a member; a member not for others; another organisation's admin cannot
r = Bo.put(B + f"/api/team/leave/worktime/{CAROL}", json={"workdays": [0, 1, 2, 3], "hours": 32})
check(r.ok and r.json()["workdays"] == [0, 1, 2, 3] and r.json()["capacity_h"] == 32, f"#2118: the admin sets carol's working week ({r.status_code} {r.text[:200]})")
check(Ca.put(B + f"/api/team/leave/worktime/{BOB}", json={"hours": 10}).status_code == 403, "#2118: a member cannot set someone else's working week")
check(Ca.put(B + f"/api/team/leave/worktime/{CAROL}", json={"workdays": "0,1,2,3"}).ok, "#2118: a person sets their own")
check(Da.put(B + f"/api/team/leave/worktime/{CAROL}", json={"hours": 1}).status_code == 404, "#2118: another organisation's admin: 404")
check(Da.put(B + f"/api/team/leave/worktime/{CAROL}", json={"hours": 1, "org": ORG}).status_code == 404, "#2118: another organisation's area: 404")
check(Bo.put(B + f"/api/team/leave/worktime/{CAROL}", json={"workdays": "9"}).status_code == 400, "#2118: invalid working days: 400")
check(Bo.put(B + f"/api/team/leave/worktime/{CAROL}", json={"hours": -3}).status_code == 400, "#2118: invalid hours: 400")
# workload: carol 32 h over Monday..Thursday; a day off on Friday costs nothing, one on Monday a quarter
check(Bo.post(B + "/api/team/absences", json={"kind": "off", "start_date": "2026-11-27", "user_id": CAROL}).status_code == 201, "setup: carol off on a Friday")
check(Bo.post(B + "/api/team/absences", json={"kind": "off", "start_date": "2026-11-27"}).status_code == 201, "setup: bob off on a Friday")
w = Bo.get(B + "/api/workload", params={"start": "2026-11-23", "weeks": 2, "org": ORG}).json()
pc = next((p for p in w["people"] if p["id"] == CAROL), {})
pb = next((p for p in w["people"] if p["id"] == BOB), {})
check(pc and pc["weeks"][0]["capacity_h"] == 32 and pc["weeks"][0]["absent_days"] == 0,
      f"#2118: a day off on a non-working day leaves carol's week full ({pc and pc['weeks'][0]})")
check(pb and abs(pb["weeks"][0]["capacity_h"] - pb["capacity_h"] * 4 / 5) < 0.01 and pb["weeks"][0]["absent_days"] == 1,
      f"#2118: without the setting a Friday off takes a fifth as before ({pb and pb['weeks'][0]})")
check(Bo.post(B + "/api/team/absences", json={"kind": "off", "start_date": "2026-11-30", "user_id": CAROL}).status_code == 201, "setup: carol off on a Monday")
w = Bo.get(B + "/api/workload", params={"start": "2026-11-23", "weeks": 2, "org": ORG}).json()
pc = next((p for p in w["people"] if p["id"] == CAROL), {})
check(pc and pc["weeks"][1]["capacity_h"] == 24 and pc["weeks"][1]["absent_days"] == 1, f"#2118: a Monday off takes a quarter of carol's 32 h ({pc and pc['weeks'][1]})")
# time gaps only on working days (the freelancer: own project list with time tracking)
L = Fr.post(B + "/api/lists", json={"name": "Work", "kind": "project", "time_tracking": True}).json()["id"]
T = Fr.post(B + "/api/tasks", json={"title": "Cut the trailer", "list_id": L}).json()["id"]
g0 = Fr.get(B + "/api/time/gaps").json()
to = date.fromisoformat(g0["to"])
days14 = [to - timedelta(days=i) for i in range(0, 14)]
busy = datetime.now(timezone.utc).date()
mon = next(d for d in days14 if d.weekday() == 0 and abs((d - busy).days) > 1)
sat = next(d for d in days14 if d.weekday() == 5)
for d in (mon, sat):
    dbx("INSERT INTO comments(task_id, user_id, body, created_at) VALUES(?,?,?,?)", (T, FID, "worked", f"{d.isoformat()}T11:00:00+00:00"), write=True)
gd = {x["date"] for x in Fr.get(B + "/api/time/gaps").json()["days"]}
check(mon.isoformat() in gd and sat.isoformat() not in gd, f"#2118: default gaps Monday..Friday ({sorted(gd)}, mon {mon}, sat {sat})")
check(Fr.patch(B + "/api/settings", json={"workdays": "1,2,3,4,5"}).ok, "#2118: the freelancer works Tuesday..Saturday")
gd = {x["date"] for x in Fr.get(B + "/api/time/gaps").json()["days"]}
check(sat.isoformat() in gd and mon.isoformat() not in gd, f"#2118: gaps follow the working days ({sorted(gd)})")
Fr.patch(B + "/api/settings", json={"workdays": ""})

# ======================================================================== #2117 vacation account
check(Bo.put(B + "/api/team/absences/holidays", json={"state": "BY"}).ok, "setup: Alpha in Bavaria (6 January a holiday)")
check(Ca.put(B + "/api/team/leave/quota", json={"user_id": CAROL, "year": 2027, "days": 30}).status_code == 403, "#2117: a member cannot set an entitlement")
check(Da.put(B + "/api/team/leave/quota", json={"user_id": CAROL, "year": 2027, "days": 30}).status_code == 404, "#2117: another organisation's admin: 404")
check(Da.put(B + "/api/team/leave/quota", json={"user_id": CAROL, "year": 2027, "days": 30, "org": ORG}).status_code == 404, "#2117: another organisation's area: 404")
check(Bo.put(B + "/api/team/leave/quota", json={"user_id": CAROL, "year": 2027, "days": 30.3}).status_code == 400, "#2117: only whole / half days")
check(Bo.put(B + "/api/team/leave/quota", json={"user_id": DAVE, "year": 2027, "days": 30}).status_code == 404, "#2117: not a member: 404")
r = Bo.put(B + "/api/team/leave/quota", json={"user_id": CAROL, "year": 2027, "days": 30, "carry": 2.5})
check(r.ok and r.json()["quota"] == {"days": 30, "carry": 2.5}, f"#2117: the admin sets carol's 2027 account ({r.status_code} {r.text[:200]})")
# approved vacation (entered by the admin): 4.-8.1.2027 Mon..Fri = Mon..Thu minus 6.1. (holiday) = 3; 1.2. half = 0.5;
# 20.12.2027-4.1.2028 = 8 working days within 2027 (Mon..Thu, 24.12. and 31.12. are Fridays)
for b in ({"start_date": "2027-01-04", "end_date": "2027-01-08"}, {"start_date": "2027-02-01", "half_day": "am"},
          {"start_date": "2027-12-20", "end_date": "2028-01-04"}):
    r = Bo.post(B + "/api/team/absences", json={"kind": "vacation", "user_id": CAROL, **b})
    check(r.status_code == 201 and r.json()["status"] == "approved", f"setup: vacation of carol ({r.status_code} {r.text[:150]})")
check(Bo.post(B + "/api/team/absences", json={"kind": "sick", "user_id": CAROL, "start_date": "2027-05-03", "end_date": "2027-05-04"}).status_code == 201, "setup: sick leave (not vacation)")


def acc(s, who, year=2027, **kw):
    j = s.get(B + "/api/team/leave", params={"year": year, **kw}).json()
    return j, next((p for p in j.get("people", []) if p["id"] == who), None)


j, pc = acc(Bo, CAROL)
check(j["admin"] is True and {p["id"] for p in j["people"]} == {BOB, CAROL, ERIN}, f"#2117: the admin sees everybody's account ({[p['id'] for p in j['people']]})")
check(pc["taken"] == 11.5 and pc["requested"] == 0 and pc["rest"] == 21, f"#2117: taken 3 + 0.5 + 8 = 11.5, rest 32.5 - 11.5 = 21 ({pc})")
j, pc = acc(Ca, CAROL)
check(j["admin"] is False and [p["id"] for p in j["people"]] == [CAROL] and pc["rest"] == 21, f"#2117: carol sees only her own account ({j['people']})")
check(acc(Er, CAROL)[1] is None, "#2117: another member does not see carol's account")
check(Da.get(B + "/api/team/leave", params={"org": ORG}).status_code == 404, "#2117: another organisation: 404")
_, pb = acc(Bo, BOB)
check(pb["quota"] is None and pb["rest"] is None, "#2117: no entitlement = no account")

# ======================================================================== #2117 requests
Ag = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "helper", "display_name": "Helper"}).json()
AGH = {"Authorization": "Bearer " + Ag["token"], **H}
check(A.patch(B + f"/api/admin/agents/{Ag['id']}", json={"org_id": ORG}).ok, "setup: an agent of Alpha")
# off by default: a member's vacation is approved at once (as before)
r = Ca.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2027-04-12"})
check(r.status_code == 201 and r.json()["status"] == "approved", f"#2117: approvals off: carol's vacation is approved at once ({r.text[:150]})")
Ca.delete(B + f"/api/team/absences/{r.json()['id']}")
check(Ca.put(B + "/api/team/leave/approval", json={"on": True}).status_code == 403, "#2117: a member cannot switch on approvals")
check(Da.put(B + "/api/team/leave/approval", json={"on": True, "org": ORG}).status_code == 404, "#2117: another organisation cannot")
r = Bo.put(B + "/api/team/leave/approval", json={"on": True})
check(r.ok and r.json()["approval"] is True, "#2117: the admin switches on approvals")
n0 = len(dbx("SELECT 1 FROM notifications WHERE user_id=? AND kind='leavereq'", (BOB,)))
r = Ca.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2027-03-01", "end_date": "2027-03-05", "note": "family"})
check(r.status_code == 201 and r.json()["status"] == "pending", f"#2117: carol's vacation is a request ({r.text[:150]})")
REQ = r.json()["id"]
check(len(dbx("SELECT 1 FROM notifications WHERE user_id=? AND kind='leavereq'", (BOB,))) == n0 + 1, "#2117: the admin gets a News item")
r = Ca.post(B + "/api/team/absences", json={"kind": "sick", "start_date": "2027-03-08"})
check(r.status_code == 201 and r.json()["status"] == "approved", "#2117: sick leave never needs an approval")
# 2.125.0 R (#2117): reopen only undoes a decision on a vacation request (a sick leave set to pending would count nowhere)
SICK = r.json()["id"]
check(Bo.post(B + f"/api/team/absences/{SICK}/decide", json={"action": "reopen"}).status_code == 409, "#2117: a sick leave cannot be reopened (409)")
check(Bo.get(B + "/api/team/absences/check", params={"user": CAROL, "date": "2027-03-08"}).json().get("absent") is True, "#2117: the sick leave still counts as away")
r = Bo.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2027-03-15"})
check(r.status_code == 201 and r.json()["status"] == "approved", "#2117: an admin's own vacation is approved")
_, pc = acc(Ca, CAROL)
check(pc["requested"] == 4 and pc["rest"] == 17, f"#2117: requested 4 (Mon..Thu), rest 17 ({pc})")
j = Ca.get(B + "/api/team/leave", params={"year": 2027}).json()
check([x["id"] for x in j["pending"]] == [REQ] and j["pending"][0]["days"] == 4, f"#2117: carol sees her open request ({j['pending']})")
j = Bo.get(B + "/api/team/leave", params={"year": 2027}).json()
check([x["id"] for x in j["pending"]] == [REQ] and j["pending"][0]["note"] == "family", "#2117: the admin sees the request with its note")
check(not Er.get(B + "/api/team/leave").json()["pending"], "#2117: another member sees no request")
q = {"start": "2027-03-01", "end": "2027-03-31"}
check(not any(x["id"] == REQ for x in Er.get(B + "/api/team/absences", params=q).json()["items"]), "#2117: the team does not see the request")
it = next((x for x in Ca.get(B + "/api/team/absences", params=q).json()["items"] if x["id"] == REQ), {})
check(it.get("status") == "pending", "#2117: carol sees it marked as requested")
check(Er.get(B + "/api/team/absences/check", params={"user": CAROL, "date": "2027-03-02"}).json().get("absent") is False, "#2117: assigning: a request is not away")
w = Bo.get(B + "/api/workload", params={"start": "2027-03-01", "weeks": 1, "org": ORG}).json()
pc = next((p for p in w["people"] if p["id"] == CAROL), {})
check(pc and pc["weeks"][0]["capacity_h"] == 32, f"#2117: workload: a request does not lower the capacity ({pc and pc['weeks'][0]})")
r = requests.get(B + "/api/v1/absences", params=q, headers=AGH)
check(r.ok and not any(x["start_date"] == "2027-03-01" for x in r.json()["items"]) and "status" not in r.text, f"#2117: agents never see a request ({r.text[:200]})")
# deciding: only the area's admins
check(Ca.post(B + f"/api/team/absences/{REQ}/decide", json={"action": "approve"}).status_code == 403, "#2117: carol cannot approve her own request")
check(Er.post(B + f"/api/team/absences/{REQ}/decide", json={"action": "approve"}).status_code == 403, "#2117: a member cannot approve (403)")
check(Da.post(B + f"/api/team/absences/{REQ}/decide", json={"action": "approve"}).status_code == 404, "#2117: another organisation's admin: 404")
check(Bo.post(B + f"/api/team/absences/{REQ}/decide", json={"action": "maybe"}).status_code == 400, "#2117: unknown action 400")
n1 = len(dbx("SELECT 1 FROM notifications WHERE user_id=? AND kind='leavedecide'", (CAROL,)))
r = Bo.post(B + f"/api/team/absences/{REQ}/decide", json={"action": "approve"})
check(r.ok and r.json()["status"] == "approved", f"#2117: the admin approves ({r.status_code} {r.text[:150]})")
check(len(dbx("SELECT 1 FROM notifications WHERE user_id=? AND kind='leavedecide'", (CAROL,))) == n1 + 1, "#2117: carol gets a News item")
check(Bo.post(B + f"/api/team/absences/{REQ}/decide", json={"action": "approve"}).status_code == 400, "#2117: decided already: 400")
check(Er.get(B + "/api/team/absences/check", params={"user": CAROL, "date": "2027-03-02"}).json().get("absent") is True, "#2117: approved = away")
_, pc = acc(Ca, CAROL)
check(pc["taken"] == 15.5 and pc["requested"] == 0 and pc["rest"] == 17, f"#2117: approved counts as taken ({pc})")
r = requests.get(B + "/api/v1/absences", params=q, headers=AGH)
check(r.ok and any(x["start_date"] == "2027-03-01" for x in r.json()["items"]), "#2117: agents see the approved vacation as away")
r = Bo.post(B + f"/api/team/absences/{REQ}/decide", json={"action": "reopen"})
check(r.ok and r.json()["status"] == "pending", "#2117: Undo of a decision: open again")
check(Bo.post(B + f"/api/team/absences/{REQ}/decide", json={"action": "approve"}).ok, "#2117: approved again")
# rejecting with a note; a changed rejected request asks again; a changed approved vacation too
r = Ca.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2027-06-07", "end_date": "2027-06-08"})
REQ2 = r.json()["id"]
r = Bo.post(B + f"/api/team/absences/{REQ2}/decide", json={"action": "reject", "note": "the trade fair"})
check(r.ok and r.json()["status"] == "rejected" and r.json()["decision_note"] == "the trade fair", "#2117: rejected with a note")
q6 = {"start": "2027-06-01", "end": "2027-06-30"}
it = next((x for x in Ca.get(B + "/api/team/absences", params=q6).json()["items"] if x["id"] == REQ2), {})
check(it.get("status") == "rejected" and it.get("decision_note") == "the trade fair", "#2117: carol reads the decision and its note")
check(not any(x["id"] == REQ2 for x in Er.get(B + "/api/team/absences", params=q6).json()["items"]), "#2117: the team never sees a rejected request")
_, pc = acc(Ca, CAROL)
check(pc["requested"] == 0 and pc["taken"] == 15.5, "#2117: a rejected request counts nowhere")
r = Ca.patch(B + f"/api/team/absences/{REQ2}", json={"start_date": "2027-06-14", "end_date": "2027-06-14"})
check(r.ok and r.json()["status"] == "pending", "#2117: carol changes the rejected request: asks again")
r = Ca.patch(B + f"/api/team/absences/{REQ2}", json={"kind": "off"})
check(r.ok and r.json()["status"] == "approved", "#2117: a day off needs no approval")
r = Ca.patch(B + f"/api/team/absences/{REQ}", json={"note": "family visit"})
check(r.ok and r.json()["status"] == "approved", "#2117: changing only the note keeps the approval")
r = Ca.patch(B + f"/api/team/absences/{REQ}", json={"end_date": "2027-03-04"})
check(r.ok and r.json()["status"] == "pending", "#2117: changing the period asks again")
check(Bo.patch(B + f"/api/team/absences/{REQ}", json={"end_date": "2027-03-05"}).json()["status"] == "pending", "#2117: an admin's change keeps the status")
# notifications can be switched off (the row "leave" of the admin's notification settings)
check(Bo.patch(B + "/api/settings", json={"notify": {"leave": {"news": 0, "push": 0}}}).ok, "setup: bob switches off the row Vacation requests")
n2 = len(dbx("SELECT 1 FROM notifications WHERE user_id=? AND kind='leavereq'", (BOB,)))
r = Ca.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2027-07-05"})
check(r.json()["status"] == "pending" and len(dbx("SELECT 1 FROM notifications WHERE user_id=? AND kind='leavereq'", (BOB,))) == n2,
      "#2117: no News item when the admin switched them off")
# switched off again: approved at once; open requests stay decidable
check(Bo.put(B + "/api/team/leave/approval", json={"on": False}).ok, "#2117: approvals off again")
r = Ca.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2027-08-02"})
check(r.json()["status"] == "approved", "#2117: switched off: approved at once")
check(Bo.post(B + f"/api/team/absences/{REQ}/decide", json={"action": "approve"}).ok, "#2117: an open request stays decidable")

# ======================================================================== a person without an organisation
j = Fr.get(B + "/api/team/leave", params={"year": 2027}).json()
check(j["admin"] is True and j["personal"] is True and j["approval"] is False and [p["id"] for p in j["people"]] == [FID],
      f"#2117 freelancer: own area, own admin, no approvals ({j.get('people')})")
check(Fr.put(B + "/api/team/leave/approval", json={"on": True}).status_code == 403, "#2117 freelancer: no approvals in a personal area")
check(Fr.put(B + "/api/team/leave/quota", json={"user_id": FID, "year": 2027, "days": 24}).ok, "#2117 freelancer: sets their own entitlement")
check(Fr.put(B + f"/api/team/leave/worktime/{FID}", json={"workdays": "0,1,2,3,4", "hours": 30}).ok, "#2118 freelancer: sets their own working week")
r = Fr.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2027-05-10", "end_date": "2027-05-14"})
check(r.status_code == 201 and r.json()["status"] == "approved", "#2117 freelancer: vacation is approved at once")
_, pf = acc(Fr, FID)
check(pf["taken"] == 5 and pf["rest"] == 19, f"#2117 freelancer: own account ({pf})")
check(Bo.put(B + "/api/team/leave/quota", json={"user_id": FID, "year": 2027, "days": 1}).status_code == 404, "#2117: nobody else sets a freelancer's account")
check(Bo.put(B + f"/api/team/leave/worktime/{FID}", json={"hours": 1}).status_code == 404, "#2118: nobody else sets a freelancer's working week")
check(Bo.post(B + f"/api/team/absences/{r.json()['id']}/decide", json={"action": "reopen"}).status_code == 404, "#2117: nobody else decides on a freelancer's absence")
check(Bo.put(B + "/api/team/leave/quota", json={"user_id": CAROL, "year": 2027, "days": None}).ok, "#2117: removing an account")
check(acc(Bo, CAROL)[1]["quota"] is None, "#2117: removed: no account")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
