#!/usr/bin/env python3
"""2.90.0 API tests, part C (#1922): tax dates as recurring tasks, own container (start.sh). Invented people only.
 - tenant-matrix: office (office admins only: a member 403, an agent 403, another organisation has its own settings and never
   reaches a foreign person or task, a person without organisation = own personal office, the task lands in their Basket)
 - the setting tax_dates is written only by /api/office/tax-dates (the general settings route ignores it)
 - one repeating task per switched-on kind: RRULE + due, the lead, the permanent extension, off ends the task (done, never deleted),
   on again makes a new one, a finished / deleted task is made again on the next save, the person changes -> a new task
 - the preview `next`
usage: p290_c_api_test.py <datadir>"""
import os
import subprocess
import sys
import time
from datetime import date

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients"
O = "/api/office"
URL = B + O + "/tax-dates"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def task(tid):
    r = sql("SELECT title,content,due,repeat,status,deleted_at,created_by,assignee_id,list_id FROM tasks WHERE id=?", (tid,))
    return r[0] if r else None


def nxt(day, months, lead, today):
    """Independent calculation: first (deadline, due) with due >= today."""
    y, m = today.year, today.month
    for _ in range(30):
        if m in months:
            d = date(y, m, day)
            if d.toordinal() - lead >= today.toordinal():
                return d, date.fromordinal(d.toordinal() - lead)
        y, m = y + (m == 12), m % 12 + 1


if not os.environ.get("P290C_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
for u in ("bob", "carol", "dave", "dora"):
    assert A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"}).ok
S = {u: sess(u) for u in ("bob", "carol", "dave", "dora")}
S["alice"] = A
for s in S.values():
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
me = lambda s: s.get(B + "/api/state").json()["me"]["id"]
ALICE, BOB, CAROL, DAVE, DORA = (me(S[u]) for u in ("alice", "bob", "carol", "dave", "dora"))
Bo, Ca, Da, Do = S["bob"], S["carol"], S["dave"], S["dora"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "dave@example.com", "role": "admin"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Da, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
TODAY = testclock.today()

# ---------------------------------------------------------------- rights
r = A.get(URL)
j = r.json() if r.ok else {}
check(r.ok and j.get("ustva") == "none" and j.get("est") == 0 and j.get("gewst") == 0 and j.get("lead_days") == 3 and j.get("next") == [], "defaults " + r.text[:200])
check({p["id"] for p in j.get("people", [])} == {ALICE, DAVE}, "the people: the admins of the office " + str(j.get("people")))
check(Bo.get(URL).status_code == 403 and Bo.put(URL, json={"est": 1}).status_code == 403, "a member gets 403")
r = A.post(B + "/api/my/agents", json={"username": "taxbot", "display_name": "Tax Bot", "scopes": ["read", "office"], "org_id": ORG})
AGH = {**H, "Authorization": "Bearer " + r.json()["token"]}
check(requests.get(URL, headers=AGH).status_code == 403 and requests.put(URL, headers=AGH, json={"est": 1}).status_code == 403, "an agent gets 403")
check(requests.get(URL, headers=H).status_code in (401, 403), "no login: refused")
check(A.put(URL, json={"ustva": "weekly"}).status_code == 400, "an unknown VAT mode: 400")
check(A.put(URL, json={"lead_days": 31}).status_code == 400 and A.put(URL, json={"lead_days": -1}).status_code == 400
      and A.put(URL, json={"lead_days": True}).status_code == 400 and A.put(URL, json={"lead_days": "x"}).status_code == 400, "lead_days 0-30 only")
check(A.put(URL, json={"user": CAROL, "est": 1}).status_code == 400 and A.put(URL, json={"user": BOB, "est": 1}).status_code == 400, "a person from another organisation / a member: 400")
check(A.put(URL, json={"user": True}).status_code == 400, "user must be an id")
check(sql("SELECT COUNT(*) FROM tasks WHERE title LIKE '%deadline%'")[0][0] == 0, "refused saves made no task")
# the general settings route cannot write it
A.put(B + O + "/settings", json={"tax_dates": {"est": 1, "tasks": {"est": 99999}}})
check(A.get(URL).json()["est"] == 0 and A.get(B + O + "/settings").json()["settings"].get("tax_dates", {}).get("est", 0) == 0, "the general settings route ignores tax_dates")

# ---------------------------------------------------------------- the tasks
r = A.put(URL, json={"ustva": "month", "lead_days": 3})
j = r.json() if r.ok else {}
T = j.get("tasks", {}).get("ustva")
check(r.ok and T and j["tasks"].get("est") is None and j["tasks"].get("gewst") is None, "monthly VAT: one task " + r.text[:200])
dl, due = nxt(10, range(1, 13), 3, TODAY)
t = task(T)
check(t and t[2] == due.isoformat() and t[3] == f"FREQ=MONTHLY;BYMONTHDAY={due.day}" and t[4] == 0, f"monthly VAT: due {due} + RRULE " + str(t))
check(t and t[6] == ALICE and t[7] == ALICE and "deadline: the 10th" in t[0], "monthly VAT: in alice's task, titled with the deadline " + str(t and t[0]))
check(t and "No tax advice; figures without guarantee." in t[1] and "#office/books/ustva" in t[1], "monthly VAT: note + link in the text")
check(sql("SELECT url FROM tasks WHERE id=?", (T,))[0][0].endswith("/#office/books/ustva"), "monthly VAT: the task link")
nx = j.get("next", [])
check(len(nx) == 3 and nx[0]["kind"] == "ustva" and nx[0]["due"] == (lambda d: date.fromordinal(d.toordinal() - 3).isoformat())(
    next(date(TODAY.year + (TODAY.month + i - 1) // 12, (TODAY.month + i - 1) % 12 + 1, 10) for i in range(0, 14)
         if date(TODAY.year + (TODAY.month + i - 1) // 12, (TODAY.month + i - 1) % 12 + 1, 10) >= TODAY)), "next: three, the first is the next 10th " + str(nx))
# same save again: no new task
j = A.put(URL, json={"ustva": "month"}).json()
check(j["tasks"]["ustva"] == T, "saving the same again keeps the task")
# other kinds
j = A.put(URL, json={"est": 1, "gewst": 1}).json()
TE, TG = j["tasks"]["est"], j["tasks"]["gewst"]
de, due_e = nxt(10, (3, 6, 9, 12), 3, TODAY)
dg, due_g = nxt(15, (2, 5, 8, 11), 3, TODAY)
te, tg = task(TE), task(TG)
check(te and te[2] == due_e.isoformat() and te[3].startswith("FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=") and "10th" in te[0], "income tax: quarterly rule from March " + str(te))
check(tg and tg[2] == due_g.isoformat() and tg[3].startswith("FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=") and "15th" in tg[0], "trade tax: quarterly rule from February " + str(tg))
check(j["tasks"]["ustva"] == T, "the other kinds leave the VAT task alone")
# quarterly VAT + extension
j = A.put(URL, json={"ustva": "quarter"}).json()
check(j["tasks"]["ustva"] != T and task(T)[3] == "" and task(T)[4] == 2 and task(T)[5] is None, "monthly -> quarterly: the old task ended (done, not deleted)")
T2 = j["tasks"]["ustva"]
dq, due_q = nxt(10, (1, 4, 7, 10), 3, TODAY)
tq = task(T2)
check(tq and tq[2] == due_q.isoformat() and "INTERVAL=3" in tq[3], "quarterly VAT: Jan / Apr / Jul / Oct " + str(tq))
j = A.put(URL, json={"ustva_ext": 1}).json()
T3 = j["tasks"]["ustva"]
dx, due_x = nxt(10, (2, 5, 8, 11), 3, TODAY)
check(T3 != T2 and task(T3)[2] == due_x.isoformat() and task(T2)[4] == 2, "extension: one month later (Feb / May / Aug / Nov) " + str(task(T3)))
check(all(n["date"] >= TODAY.isoformat() for n in j["next"]) and j["next"] == sorted(j["next"], key=lambda n: (n["date"], n["kind"])), "next: sorted, not in the past")
# lead
j = A.put(URL, json={"lead_days": 0}).json()
check(task(j["tasks"]["ustva"])[2] == nxt(10, (2, 5, 8, 11), 0, TODAY)[1].isoformat(), "lead 0: due on the deadline day")
j = A.put(URL, json={"lead_days": 30}).json()
t30 = task(j["tasks"]["gewst"])
d30, due30 = nxt(15, (2, 5, 8, 11), 30, TODAY)
check(t30[2] == due30.isoformat() and ("BYMONTHDAY=-" in t30[3] if due30.month != d30.month else True), "lead 30: due a month before, rule counts from the month end " + str(t30))
check(j["lead_days"] == 30, "lead stored")
A.put(URL, json={"lead_days": 3})
# off ends, never deletes
j = A.put(URL, json={"est": 0}).json()
check(j["tasks"]["est"] is None and task(TE) is not None and task(TE)[3] == "" and task(TE)[4] == 2 and task(TE)[5] is None, "off: the task is ended (done, no repeat), not deleted")
j = A.put(URL, json={"est": 1}).json()
check(j["tasks"]["est"] not in (None, TE), "on again: a new task")
TE2 = j["tasks"]["est"]
# the user finished it / deleted it -> made again on the next save
sql_done = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
sql_done.execute("UPDATE tasks SET status=2 WHERE id=?", (TE2,))
sql_done.commit()
sql_done.close()
j = A.put(URL, json={"est": 1}).json()
check(j["tasks"]["est"] not in (None, TE2) and task(j["tasks"]["est"])[4] == 0, "a finished task is made again on the next save")
r = A.delete(B + f"/api/tasks/{j['tasks']['gewst']}")
j = A.put(URL, json={"gewst": 1}).json()
check(task(j["tasks"]["gewst"])[5] is None and task(j["tasks"]["gewst"])[4] == 0, "a deleted task is made again on the next save")
# the person changes
check(Da.get(URL).status_code == 200, "a second admin opens it")
j = A.put(URL, json={"user": DAVE}).json()
check(j["user"] == DAVE and task(j["tasks"]["ustva"])[6] == DAVE and task(j["tasks"]["ustva"])[7] == DAVE and task(T3)[4] == 2 and task(T3)[3] == "", "another person: new tasks for them, the old ones ended")
check({task(j["tasks"][k])[8] for k in ("ustva", "est", "gewst")} == {sql("SELECT id FROM lists WHERE is_inbox=1 AND owner_id=?", (DAVE,))[0][0]}, "all in dave's inbox")
# all off
j = A.put(URL, json={"ustva": "none", "est": 0, "gewst": 0}).json()
check(all(v is None for v in j["tasks"].values()) and j["next"] == [], "all off: no task, no preview")
check(sql("SELECT COUNT(*) FROM tasks WHERE repeat LIKE 'FREQ=MONTHLY%' AND status=0 AND deleted_at IS NULL AND title LIKE '%deadline%'")[0][0] == 0, "all off: no running task is left")

# ---------------------------------------------------------------- small business: a hint, not a ban
A.put(B + O + "/settings", json={"small_business": 1})
j = A.put(URL, json={"ustva": "quarter"}).json()
check(j["small_business"] is True and j["ustva"] == "quarter" and j["tasks"]["ustva"], "small business: allowed, the flag is returned for the hint")
A.put(URL, json={"ustva": "none"})

# ---------------------------------------------------------------- another organisation
r = Ca.get(URL)
check(r.ok and r.json()["ustva"] == "none" and {p["id"] for p in r.json()["people"]} == {CAROL}, "other org: its own empty settings, only its own people")
check(Ca.put(URL, json={"user": ALICE, "est": 1}).status_code == 400 and Ca.put(URL, json={"user": DAVE, "est": 1}).status_code == 400, "other org: a foreign person is refused")
j = Ca.put(URL, json={"est": 1}).json()
check(task(j["tasks"]["est"])[6] == CAROL and A.get(URL).json()["est"] == 0, "other org: its task is carol's, alice's settings are untouched")

# ---------------------------------------------------------------- a person without organisation
r = Do.get(B + O + "/settings")
check(r.ok and r.json().get("personal") == 1, "personal office " + r.text[:120])
r = Do.get(URL)
check(r.ok and [p["id"] for p in r.json()["people"]] == [DORA], "personal office: the person is the admin")
j = Do.put(URL, json={"ustva": "month", "est": 1}).json()
td = task(j["tasks"]["ustva"])
check(td and td[6] == DORA and td[7] == DORA and td[8] == sql("SELECT id FROM lists WHERE is_inbox=1 AND owner_id=?", (DORA,))[0][0], "personal office: the task is in dora's Basket " + str(td))
check(Do.put(URL, json={"user": ALICE}).status_code == 400, "personal office: only the owner")
check(A.get(URL).json()["ustva"] == "none", "the others are untouched")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
