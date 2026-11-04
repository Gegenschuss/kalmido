#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.528.0 part A (#4305): lost writes. Own container (start.sh), invented names only.
 - B1 "Skip this occurrence" twice: the same Idempotency-Key (a resent request) and a second device with the old due date
   (expect) skip ONE occurrence; the stale one answers 409 code skip_stale with the current task; without expect as before
 - A8 accepting an agent's triage proposal: a task the person changed after the proposal was stored is not overwritten
   (409 naming it, nothing applied); without it selected the rest applies; an unchanged task applies as before
 - A3 office settings: a save with expect_updated_at (the version the page loaded) after another session's save answers 409
   with the current settings and saves nothing (B no longer resets A's payment terms); with the current version it saves;
   without expect_updated_at (other callers, old clients) as before; two saves in the same second are told apart
 - a person without an organisation (the own private workspace, its own admin): the same -- freelancer-matrix: tasks, agents, office
usage: p2528_a_test.py <datadir>      (P2528A_NOSTART=1: use a running server)"""
import os
import subprocess
import sys
from datetime import date

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
V = B + "/api/v1"


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def post(self, p, **k):
        return requests.post(V + p, headers=self.h, timeout=30, **k)

    def get(self, p, **k):
        return requests.get(V + p, headers=self.h, timeout=30, **k)

if not os.environ.get("P2528A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab", "office"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A2 = sess("alice")  # a second device of the same person


def task(s, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, **kw})
    assert r.ok, r.text
    return r.json()


def one(s, tid):
    return s.get(B + f"/api/tasks/{tid}").json()


def skip_twice(s1, s2, lid, who):
    """B1: a daily task with COUNT=10; a resent skip (same key) and a stale skip of a second device move it ONE day."""
    today = testclock.today().isoformat()
    t = task(s1, f"Feed the fish {who}", list_id=lid, due=today, repeat="FREQ=DAILY;COUNT=10")
    tid = t["id"]
    k = f"oxa-{who}-1"
    r1 = s1.post(B + f"/api/tasks/{tid}/skip", json={"expect": today}, headers={"Idempotency-Key": k})
    check(r1.ok and r1.json().get("next_due") and r1.json()["next_due"] > today, f"{who}: first skip ok {r1.status_code} {r1.text[:200]}")
    nxt = r1.json().get("next_due")
    r2 = s1.post(B + f"/api/tasks/{tid}/skip", json={"expect": today}, headers={"Idempotency-Key": k})
    check(r2.ok and r2.headers.get("Idempotent-Replayed") == "true" and r2.json().get("next_due") == nxt,
          f"{who}: the resent skip (same key) gets the first answer {r2.status_code} {dict(r2.headers).get('Idempotent-Replayed')}")
    check(one(s1, tid)["due"] == nxt, f"{who}: after the resent skip the date moved once {one(s1, tid)['due']} != {nxt}")
    r3 = s2.post(B + f"/api/tasks/{tid}/skip", json={"expect": today}, headers={"Idempotency-Key": f"oxa-{who}-2"})
    j3 = r3.json() if r3.headers.get("content-type", "").startswith("application/json") else {}
    check(r3.status_code == 409 and j3.get("code") == "skip_stale" and (j3.get("task") or {}).get("due") == nxt and j3.get("error"),
          f"{who}: the second device with the old date: 409 skip_stale + the current task {r3.status_code} {r3.text[:200]}")
    cur = one(s1, tid)
    check(cur["due"] == nxt and "COUNT=9" in (cur.get("repeat") or ""), f"{who}: one occurrence skipped in all {cur['due']} {cur.get('repeat')}")
    r4 = s2.post(B + f"/api/tasks/{tid}/skip", json={})  # an old client / v1 without expect: skips as before
    check(r4.ok and r4.json().get("next_due") > nxt, f"{who}: a skip without expect still skips {r4.status_code} {r4.text[:200]}")
    r5 = s2.post(B + f"/api/tasks/{tid}/skip", json={"expect": r4.json().get("next_due")})
    check(r5.ok and date.fromisoformat(r5.json()["next_due"]) > date.fromisoformat(r4.json()["next_due"]),
          f"{who}: a skip with the current date skips {r5.status_code} {r5.text[:200]}")


def triage_stale(s, s2, cl, ag, who):
    """A8: the agent proposes new titles for two inbox tasks; the person renames one on a second device; apply -> 409, both
    untouched; apply without the changed one -> only the other renamed, the person's title stays."""
    lid = s.post(B + "/api/lists", json={"name": f"Garden {who}"}).json()["id"]
    i1 = task(s, f"buy seeds {who}")["id"]
    i2 = task(s, f"fix fence {who}")["id"]
    r = s.post(B + "/api/proposals", json={"agent_id": ag, "kind": "triage", "task_ids": [i1, i2], "lists": [lid]})
    check(r.status_code == 201, f"{who}: triage asked {r.status_code} {r.text[:200]}")
    jid = r.json()["id"]
    r = cl.post(f"/agent/jobs/{jid}/proposal", json={"items": [{"task_id": i1, "rewrite_title": "Buy tomato seeds"},
                                                               {"task_id": i2, "rewrite_title": "Repair the fence", "list_id": lid}]})
    check(r.status_code == 201, f"{who}: proposal stored {r.status_code} {r.text[:200]}")
    r = s2.patch(B + f"/api/tasks/{i1}", json={"title": f"buy seeds and soil {who}"})  # the person, after the proposal
    check(r.ok, f"{who}: renamed on the second device {r.status_code}")
    r = s.post(B + f"/api/proposals/{jid}/apply", json={"select": ["0", "1"]})
    check(r.status_code == 409 and "buy seeds and soil" in (r.json().get("error") or ""),
          f"{who}: apply with the changed task: 409 naming it {r.status_code} {r.text[:200]}")
    check(one(s, i1)["title"] == f"buy seeds and soil {who}" and one(s, i2)["title"] == f"fix fence {who}",
          f"{who}: nothing applied: {one(s, i1)['title']} / {one(s, i2)['title']}")
    r = s.post(B + f"/api/proposals/{jid}/apply", json={"select": ["1"]})
    check(r.ok and r.json().get("changed") == 1, f"{who}: apply without the changed task {r.status_code} {r.text[:200]}")
    t1, t2 = one(s, i1), one(s, i2)
    check(t1["title"] == f"buy seeds and soil {who}" and t2["title"] == "Repair the fence" and t2["list_id"] == lid,
          f"{who}: the person's title stays, the other applied: {t1['title']} / {t2['title']} {t2['list_id']}")


def dayplan_stale(s, s2, cl, ag, who):
    """2.528.0 (#4305, review Fable 2): a day plan compares only what it writes - a new title of the task since the proposal
    does not refuse it; a duration set on the second device does (409, the person's duration stays)."""
    ds = date.today().isoformat()
    t1 = task(s, f"write report {who}", due=ds)["id"]
    def ask():
        r = s.post(B + "/api/proposals", json={"agent_id": ag, "kind": "dayplan", "date": ds})
        check(r.status_code == 201, f"{who}: day plan asked {r.status_code} {r.text[:200]}")
        j = r.json()["id"]
        r = cl.post(f"/agent/jobs/{j}/proposal", json={"kind": "dayplan", "items": [{"task_id": t1, "start": "08:00", "duration": 30}]})
        check(r.status_code == 201, f"{who}: day plan stored {r.status_code} {r.text[:200]}")
        return j
    j = ask()
    check(s2.patch(B + f"/api/tasks/{t1}", json={"title": f"write the report {who}"}).ok, f"{who}: renamed after the day plan")
    r = s.post(B + f"/api/proposals/{j}/apply", json={"select": ["0"]})
    check(r.ok and one(s, t1)["plan_start"] == ds + "T08:00", f"{who}: a new title does not refuse the day plan {r.status_code} {r.text[:200]}")
    s.post(B + f"/api/proposals/{j}/undo")
    j = ask()
    check(s2.patch(B + f"/api/tasks/{t1}", json={"duration": 90}).ok, f"{who}: duration set after the day plan")
    r = s.post(B + f"/api/proposals/{j}/apply", json={"select": ["0"]})
    check(r.status_code == 409 and one(s, t1)["duration"] == 90, f"{who}: a changed duration refuses it {r.status_code} {r.text[:200]}")


OS = "/api/office/settings"


def office_stale(s1, s2, who):
    """A3: s1 loaded the page, s2 sets the payment terms, s1 saves its stale whole page -> 409, the terms stay."""
    g1 = s1.get(B + OS).json()
    at1 = g1["settings"].get("updated_at")
    r = s1.put(B + OS, json={"color": "#123456"})  # make sure a row exists (a fresh office has no version yet)
    check(r.ok and r.json()["settings"].get("updated_at"), f"{who}: a save answers the version {r.status_code} {r.text[:200]}")
    at1 = s1.get(B + OS).json()["settings"]["updated_at"]
    check(at1 != g1["settings"].get("updated_at"), f"{who}: the version moves on with a save")
    r = s2.put(B + OS, json={"payment_days": 21, "expect_updated_at": at1})
    check(r.ok and r.json()["settings"]["payment_days"] == 21, f"{who}: B saves the payment terms {r.status_code} {r.text[:200]}")
    at2 = r.json()["settings"]["updated_at"]
    old_page = {**g1["settings"], "payment_days": g1["settings"].get("payment_days"), "reminder_fee": 7}
    old_page.pop("updated_at", None)
    r = s1.put(B + OS, json={**old_page, "expect_updated_at": at1})  # A's page from before: the whole old form
    j = r.json()
    check(r.status_code == 409 and (j.get("settings") or {}).get("payment_days") == 21 and (j.get("settings") or {}).get("updated_at") == at2,
          f"{who}: A's stale save: 409 with the current settings {r.status_code} {r.text[:200]}")
    cur = s1.get(B + OS).json()["settings"]
    check(cur["payment_days"] == 21 and cur.get("reminder_fee") != 7, f"{who}: nothing of the stale save stored {cur['payment_days']} {cur.get('reminder_fee')}")
    r = s1.put(B + OS, json={"reminder_fee": 7, "expect_updated_at": at2})  # only the changed field, with the current version
    check(r.ok and r.json()["settings"]["payment_days"] == 21 and r.json()["settings"]["reminder_fee"] == 7,
          f"{who}: with the current version A's field saves, B's terms stay {r.status_code} {r.text[:200]}")
    at3 = r.json()["settings"]["updated_at"]
    r = s2.put(B + OS, json={"payment_days": 30, "expect_updated_at": at3})
    r2 = s1.put(B + OS, json={"payment_days": 14, "expect_updated_at": at3})  # in the same second as the save before
    check(r.ok and r2.status_code == 409, f"{who}: two saves right after each other are told apart {r.status_code} {r2.status_code}")
    r = s1.put(B + OS, json={"reminder_fee": 8})  # without expect_updated_at: as before
    check(r.ok and r.json()["settings"]["payment_days"] == 30 and r.json()["settings"]["reminder_fee"] == 8,
          f"{who}: without expect_updated_at saved as before {r.status_code} {r.text[:200]}")


LID = A.post(B + "/api/lists", json={"name": "Aquarium"}).json()["id"]
skip_twice(A, A2, LID, "alice")
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "gardener", "display_name": "Gardener"})
assert r.status_code in (200, 201), r.text
AG, CL = r.json()["id"], Api(r.json()["token"])
assert A.patch(B + f"/api/admin/agents/{AG}", json={"proposals": "all"}).ok
triage_stale(A, A2, CL, AG, "alice")
dayplan_stale(A, A2, CL, AG, "alice")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}", "features": "cal,comments,collab,office,clients,agents"})
office_stale(A, A2, "org admin")

# ============================================================ a person without an organisation (freelancer-matrix: tasks)
FID, Fr = freelancer(B, A)
Fr2 = sess("frida")
FL = Fr.post(B + "/api/lists", json={"name": "Studio"}).json()["id"]
skip_twice(Fr, Fr2, FL, "frida")
triage_stale(Fr, Fr2, CL, AG, "frida")
dayplan_stale(Fr, Fr2, CL, AG, "frida")
check(Fr.get(B + OS).json().get("role") == "admin", "frida: admin of the personal office")
office_stale(Fr, Fr2, "frida")

print(f"p2528_a: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
