#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.367.2 (#2968, #2969): what waits for a person reaches them, under its own name. Invented names only.
freelancer-matrix: tasks
#2968
 (1) an approval request: "Approval needed" (News, push, mail line) instead of "assigned you", also when the approver already had the task
 (2) the decision reaches the asker at once inside a burst window, as ONE event (no "completed" / "assigned" besides)
 (3) a review approved: News + push to the assignee; by a linked pull request too (no person acted)
 (4) an agent's approval card / question pushes past agent_push and the burst gate, in its own words; a plain comment stays quiet
 (5) the approval News are on by default; a list-wide one survives reading
 (6) a task assigned to a group: push like a plain assignment, an agent in the group gets none
 (7) a person without an organisation asks for an approval and decides on a review
usage: p23672_notify_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm
from freelancer_fixture import freelancer
from kt import FAILS, OKS, check, sess

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
V = B + "/api/v1"


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        cur = c.execute(sql, args)
        rows = cur.fetchall() if sql.lstrip().upper().startswith("SELECT") else []
        c.commit()
        return rows
    finally:
        c.close()


def in_app(code):
    """Lines of Python inside the container; prints the JSON of `out`."""
    head = "import json\nimport app\nfrom kalmido.core.config import app as flask_app\nfrom kalmido.core.db import connect\nc = connect()\n"
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", head + code + "\nprint('OUT' + json.dumps(out))"],
                       capture_output=True, text=True, timeout=200)
    for line in r.stdout.splitlines():
        if line.startswith("OUT"):
            return json.loads(line[3:])
    raise AssertionError(r.stdout[-800:] + r.stderr[-1500:])


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def clear():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


def wait_push(pred, sec=8):
    """The push that meets pred, once it arrived (they leave after the request, in a thread)."""
    end = time.time() + sec
    while time.time() < end:
        hit = [x for x in pushes() if pred(x)]
        if hit:
            return hit[0]
        time.sleep(0.1)
    return None


def pushed(topic, title):
    return wait_push(lambda x: x["topic"] == topic and x.get("title") == title)


def titles(topic):
    return [x.get("title") for x in pushes() if x["topic"] == topic]


def news(s, kind=None):
    its = s.get(B + "/api/news").json()["items"]
    return [x for x in its if kind is None or x["kind"] == kind]


def task(s, title, lid=None, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, **({"list_id": lid} if lid else {}), **kw})
    assert r.status_code < 300, r.text
    return r.json()["id"]


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
ids = {"alice": 1}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for x in (A, Bo, Ca, Da):
    x.patch(B + "/api/settings", json={"lang": "en"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"}).json()
AG = ag["id"]
AGH = {"Authorization": "Bearer " + ag["token"]}
L = A.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
for uid in (BOB, CAROL, DAVE, AG):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": uid, "role": "edit"}).ok
clear()

# ---- (1) the request has its own name
T1 = task(Bo, "Flyer", L)
r = Bo.post(B + f"/api/tasks/{T1}/approval", json={"action": "request", "approver_id": CAROL, "note": "Until Friday"})
check(r.ok, f"(1) request {r.status_code} {r.text[:200]}")
p = pushed("t-carol", "Approval needed: Flyer")
check(p and "Until Friday" in p["msg"] and "Bob" in p["msg"], f"(1) the push says it, with the note and who asks: {p}")
check("Bob assigned you: Flyer" not in titles("t-carol"), f"(1) no assignment push besides: {titles('t-carol')}")
it = news(Ca, "aprequest")
check(len(it) == 1 and it[0]["task_id"] == T1 and it[0]["to_me"] and it[0]["data"]["note"] == "Until Friday", f"(1) News, for me: {it}")
check(not news(Ca, "assign"), "(1) no assignment in the News besides")
T2 = task(Bo, "Poster", L, assignee_id=CAROL)
time.sleep(0.2)
clear()
Bo.post(B + f"/api/tasks/{T2}/approval", json={"action": "request", "approver_id": CAROL})
check(pushed("t-carol", "Approval needed: Poster"), "(1) the approver already had the task: the request still arrives, past the burst window")
out = in_app("""
from kalmido.notify.channels import EVM_KINDS, evm_line
out = {"a": evm_line("aprequest", "Bob", "Flyer", "de"), "d": evm_line("apdecide", "Carol", "Flyer", "en"), "k": EVM_KINDS["aprequest"]}
""")
check(out == {"a": "Freigabe nötig: Flyer (von Bob)", "d": "Carol decided on your approval request: Flyer", "k": "mail_assign"}, f"(1) the mail lines: {out}")

# ---- (2) one decision, at once
Ca.post(B + f"/api/tasks/{T1}/comments", json={"body": "Looking at it"})  # opens bob's burst window on this task
check(wait_push(lambda x: x["topic"] == "t-bob" and x.get("title") == "Flyer"), "(2) the comment pushes (window open)")
clear()
r = Ca.post(B + f"/api/tasks/{T1}/approval", json={"action": "approve", "note": "Fine"})
check(r.ok, f"(2) approve {r.status_code} {r.text[:200]}")
p = pushed("t-bob", "Carol approved: Flyer")
check(p and "Fine" in p["msg"], f"(2) the decision comes at once inside the window: {pushes()}")
check(not [x for x in titles("t-bob") if "completed" in x], f"(2) no second push: {titles('t-bob')}")
check(len(news(Bo, "apdecide")) == 1 and not news(Bo, "complete"), f"(2) one News item: {[x['kind'] for x in news(Bo)]}")
T3 = task(Bo, "Banner", L)
Bo.post(B + f"/api/tasks/{T3}/approval", json={"action": "request", "approver_id": CAROL})
time.sleep(0.2)
clear()
r = Ca.post(B + f"/api/tasks/{T3}/approval", json={"action": "changes", "note": "Bigger"})
check(pushed("t-bob", "Carol asks for changes: Banner"), f"(2) changes reach the asker: {r.text[:100]} {pushes()}")
check(not [x for x in titles("t-bob") if "assigned you" in x], f"(2) no assignment push besides: {titles('t-bob')}")
check(not [x for x in news(Bo, "assign") if x["task_id"] == T3], "(2) no assignment in the News besides")
check(dbw("SELECT assignee_id FROM tasks WHERE id=?", (T3,))[0][0] == BOB, "(2) the task went back to the asker all the same")

# ---- (3) a review approved
check(A.put(B + f"/api/lists/{L}/review", json={"on": True, "reviewer": CAROL, "gate": True}).ok, "(3) review step on")
T4 = task(A, "Report", L, assignee_id=BOB)
Bo.post(B + f"/api/tasks/{T4}/review", json={"action": "request"})
check(pushed("t-carol", "Bob asks you to review: Report"), "(3) the request pushes")
clear()
r = Ca.post(B + f"/api/tasks/{T4}/review", json={"action": "approve", "note": "Good"})
check(r.ok, f"(3) approve {r.status_code} {r.text[:200]}")
p = pushed("t-bob", "Review approved: Report")
check(p and p["msg"] == "Good", f"(3) the assignee hears of it: {pushes()}")
it = [x for x in news(Bo, "review") if x["task_id"] == T4]
check(len(it) == 1 and it[0]["data"]["state"] == "approved" and it[0]["to_me"], f"(3) News: {it}")
T5 = task(A, "Report 2", L, assignee_id=BOB)
Bo.post(B + f"/api/tasks/{T5}/review", json={"action": "request"})
time.sleep(0.2)
clear()
out = in_app(f"""
from kalmido.tasks.review import rvw_approved_by_pr
out = rvw_approved_by_pr(c, {T5}, "acme/site#7 Fix", "https://example.test/7")
c.commit()
""")
check(out is True and pushed("t-bob", "Review approved: Report 2"), f"(3) a merged pull request approves, without a request: {out} {pushes()}")
it = [x for x in news(Bo, "review") if x["task_id"] == T5 and x["data"].get("pr")]
check(len(it) == 1 and it[0]["to_me"] and "Fix" in it[0]["data"]["pr"], f"(3) News names the pull request, for me: {it}")
check(A.put(B + f"/api/lists/{L}/review", json={"on": False}).ok, "(3) review step off")

# ---- (4) an agent asks (agent_push stays 0)
T6 = task(A, "Release", L, assignee_id=DAVE)
time.sleep(0.2)
clear()
r = requests.post(V + f"/tasks/{T6}/comments", headers=AGH, json={"body": "May I?", "approval": {"title": "Publish the cut"}})
check(r.status_code == 201, f"(4) card {r.status_code} {r.text[:200]}")
p = pushed("t-dave", "Approval needed: Publish the cut")
check(p and "Helper" in p["msg"], f"(4) the card pushes in its own words: {pushes()}")
r = requests.post(V + f"/tasks/{T6}/comments", headers=AGH, json={"body": "Which one?", "choices": ["Short", "Long"]})
p = wait_push(lambda x: x["topic"] == "t-dave" and "Helper asks: Which one?" in x.get("msg", ""))
check(p, f"(4) a question right after, inside the window, pushes too: {pushes()}")
T7 = task(A, "Quiet", L, assignee_id=DAVE)
time.sleep(0.2)
clear()
requests.post(V + f"/tasks/{T7}/comments", headers=AGH, json={"body": "Just so you know"})
wait_push(lambda x: False, 0.6)
check(not titles("t-dave"), f"(4) a plain comment of an agent stays quiet: {titles('t-dave')}")
check(not dbw("SELECT 1 FROM task_push WHERE task_id=? AND user_id=? AND (pending>0 OR events>0)", (T7, DAVE)), "(4) and leaves nothing for a later summary")

# ---- (5) approval News
st = Da.get(B + "/api/state").json()["settings"]
check(not json.loads(st.get("notify") or "{}").get("approval"), "(5) nobody chose anything")
c0 = len(news(Da, "approval"))
dbw("""INSERT INTO notifications(user_id,kind,task_id,list_id,actor_id,comment_id,data,created_at)
       VALUES(?,'approval',NULL,?,?,NULL,?,'2026-10-31T10:00:00.000Z')""", (DAVE, L, AG, json.dumps({"title": "Delete the list", "job": 1})))
it = news(Da, "approval")
check(len(it) == c0 + 1 and any(x["data"].get("title") == "Delete the list" and x["to_me"] for x in it), f"(5) a list-wide approval stays when read: {it}")
out = in_app("""
from kalmido.collab.news import notif_matrix
out = notif_matrix({})["approval"]
""")
check(out == {"news": True, "push": True}, f"(5) on by default: {out}")

# ---- (6) a group
gid = A.post(B + "/api/admin/groups", json={"name": "Office"}).json()["id"]
check(A.patch(B + f"/api/admin/groups/{gid}", json={"members": [BOB, CAROL]}).ok, "(6) group")
check(A.put(B + f"/api/lists/{L}/groups/{gid}", json={"role": "edit"}).ok, "(6) shared with the group")
time.sleep(3.2)  # the burst window of the sections above (a real gap of the rule, not of the test)
clear()
T8 = task(A, "Open the door", L, assignee_group_id=gid)
check(pushed("t-bob", "Alice assigned Office: Open the door") and pushed("t-carol", "Alice assigned Office: Open the door"), f"(6) every member: {pushes()}")
check(len(news(Bo, "assign")) >= 1 and any(x["task_id"] == T8 and x["data"].get("group") == "Office" for x in news(Bo, "assign")), "(6) News as before")
check(not titles("t-alice"), f"(6) not the person who assigned: {titles('t-alice')}")

# ---- (7) without an organisation
FID, Fr = freelancer(B, A, "frida")
A.patch(B + f"/api/users/{FID}", json={"ntfy_topic": "t-frida"})
FL = Fr.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
assert Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": BOB, "role": "edit"}).ok, "share"
T9 = task(Bo, "Offer", FL)
r = Bo.post(B + f"/api/tasks/{T9}/approval", json={"action": "request", "approver_id": FID})
check(r.ok and news(Fr, "aprequest"), f"(7) frida is asked: {r.status_code} {r.text[:200]}")
check(pushed("t-frida", "Approval needed: Offer"), f"(7) by push: {pushes()}")
T10 = task(Fr, "Own one", FL)
r = Fr.post(B + f"/api/tasks/{T10}/approval", json={"action": "request", "approver_id": BOB})
check(r.ok and Bo.post(B + f"/api/tasks/{T10}/approval", json={"action": "reject"}).ok, "(7) frida asks, bob rejects")
check([x for x in news(Fr, "apdecide") if x["data"]["state"] == "rejected"], "(7) frida hears of it")

print(f"p23672_notify: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
