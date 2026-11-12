#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1037.0 (#5801): the bell's deadline lines. Two computed lines at the top of "For you" -- "{n} tasks due today" and "{n}
tasks overdue" -- counted from the tasks (collab/duebell.py), no stored News item; each line counts 1 at the bell. Seen for
today = a read mark of the shared core (obj_seen kind 'due'). Invented names only.
 (1) counted: my open tasks due today / before today (own list without assignee, assigned to me); not: done, deleted,
     tomorrow, someone else's, a task of my list assigned to someone else
 (2) /api/news, /api/state (news) and the delta carry the same due state; unread_me = the lines that count (+ News for me)
 (3) the app icon's number (notify/push.py badge_count) = the bell's (news unread_me + direct messages)
 (4) "seen for today": the line stops counting; one more task due today brings it back; the mark lives in obj_seen (kind due)
 (5) a mark of an earlier day does not hold (the line counts again on the next day)
 (6) a follow-up day (kind followup) counts "For you" (to_me), as the dashboard showed it
 (7) a person without an organisation (freelancer) gets the same lines; collab off = no lines, nothing counted
freelancer-matrix: tasks (a person without an organisation sees her deadline lines and marks one seen for today)
usage: p21037_b_due_test.py <datadir>"""
import json
import os
import subprocess
import sys
from datetime import timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, CT, check, dbx, done, fresh, sess, today  # noqa: E402

fresh(prefix="P21037B")

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"}).json().get("id")
FID, Fr = freelancer(B, A)
T0 = today()
D0, DY, DT = T0.isoformat(), (T0 - timedelta(days=3)).isoformat(), (T0 + timedelta(days=1)).isoformat()


def plist(s, name, **kw):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": None, **kw})
    check(r.ok, f"setup: project {name} {r.text[:120]}")
    return r.json().get("id")


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    check(r.ok, f"setup: task {title} {r.text[:120]}")
    return r.json().get("id")


def in_app(code):
    """Lines of Python inside the container; prints the JSON of `out`."""
    head = "import json\nimport app\n"
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", head + code + "\nprint('OUT' + json.dumps(out))"],
                       capture_output=True, text=True, timeout=200)
    for line in r.stdout.splitlines():
        if line.startswith("OUT"):
            return json.loads(line[3:])
    raise AssertionError(r.stdout[-800:] + r.stderr[-1500:])


def news(s):
    return s.get(B + "/api/news").json()


# ---- (1) + (2) the freelancer: her own project, nobody else in it
L = plist(Fr, "Garden plans")
task(Fr, L, "Water the roses", due=D0)
task(Fr, L, "Cut the hedge", due=D0)
task(Fr, L, "Order seeds", due=DY)
task(Fr, L, "Plan the pond", due=DT)  # tomorrow: not counted
t_done = task(Fr, L, "Rake leaves", due=D0)
check(Fr.post(B + f"/api/tasks/{t_done}/complete").ok, "setup: one task done")
t_del = task(Fr, L, "Old idea", due=DY)
Fr.delete(B + f"/api/tasks/{t_del}")
j = news(Fr)
d = j.get("due") or {}
check(d.get("day") == D0 and d.get("today") == 2 and d.get("overdue") == 1, f"(1) the freelancer: 2 due today, 1 overdue on {D0}: {d}")
check(d.get("n") == 2 and j.get("unread_me") == 2, f"(2) each line counts 1 at the bell: n={d.get('n')} unread_me={j.get('unread_me')}")
st = Fr.get(B + "/api/state").json()
check(st["news"].get("due") == d and st["news"]["unread_me"] == 2, f"(2) /api/state carries the same due state: {st['news']}")

# ---- (3) the app icon = the bell
out = in_app(f"from kalmido.notify.push import badge_count\nout = badge_count({FID})")
check(out == st["news"]["unread_me"] + st["team"]["dm_unread"], f"(3) the app icon's badge = the bell's number: {out} vs {st['news']['unread_me']} + {st['team']['dm_unread']}")

# ---- (4) seen for today
r = Fr.post(B + "/api/news/due-seen", json={"line": "today"})
check(r.ok and r.json().get("unread_me") == 1 and r.json()["due"]["seen_today"] == 2, f"(4) seen for today: only the overdue line counts: {r.text[:300]}")
check(news(Fr)["due"]["n"] == 1, "(4) the mark holds on the next fetch")
mk = dbx("SELECT ref_id, seen_id FROM obj_seen WHERE kind='due' AND user_id=?", (FID,))
check(len(mk) == 1 and mk[0][0] == 1, f"(4) the mark is a row of the core's obj_seen (kind due, ref 1 = today): {mk}")
check(Fr.post(B + "/api/news/due-seen", json={"line": "nonsense"}).status_code == 400, "(4) an unknown line is refused")
task(Fr, L, "Mow the lawn", due=D0)
d = news(Fr)["due"]
check(d["today"] == 3 and d["n"] == 2, f"(4) one more task due today brings the line back: {d}")
Fr.post(B + "/api/news/due-seen", json={"line": "today"})
Fr.post(B + "/api/news/due-seen", json={"line": "overdue"})
j = news(Fr)
check(j["due"]["n"] == 0 and j["unread_me"] == 0, f"(4) both seen: the bell is empty: {j['due']} {j['unread_me']}")
b2 = in_app(f"from kalmido.notify.push import badge_count\nout = badge_count({FID})")
check(b2 == 0, f"(4) the app icon follows: {b2}")

# ---- (5) a mark of an earlier day does not hold
dbx("UPDATE obj_seen SET seen_id=seen_id-1000000 WHERE kind='due' AND user_id=? AND ref_id=2", (FID,))
d = news(Fr)["due"]
check(d["seen_overdue"] == -1 and d["n"] == 1, f"(5) yesterday's mark: the overdue line counts again: {d}")

# ---- (1) assigned: alice's project shared with bob, a task assigned to bob is not alice's; one assigned to alice is
LA = plist(A, "Studio work", kind="project")
r = A.put(B + f"/api/lists/{LA}/members", json={"user_id": BOB, "role": "edit"})
check(r.ok, "setup: bob in the project " + r.text[:200])
t_b = task(A, LA, "Send the sketches", due=D0)
r = A.patch(B + f"/api/tasks/{t_b}", json={"assignee_id": BOB})
check(r.ok, "setup: assigned to bob " + r.text[:200])
task(A, LA, "Check the invoice", due=DY)
d = news(A)["due"]
check(d.get("today") == 0 and d.get("overdue") == 1, f"(1) a task of my list assigned to someone else is not mine: {d}")
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
d = news(Bo).get("due") or {}
check(d.get("today") == 1 and d.get("overdue") == 0, f"(1) assigned to me counts (bob): {d}")

# ---- (6) a follow-up day is "For you"
out = in_app("from kalmido.collab.news import news_to_me\nout = [news_to_me('followup', None, {}, set()), news_to_me('proposal', 9, {}, {9})]")
check(out == [True, True], f"(6) a follow-up day and an agent's proposal are For you (to_me): {out}")

# ---- (7) collab off: no lines, nothing counted
Fr.patch(B + "/api/settings", json={"features": FEATURES.replace("collab,", "")})
j = Fr.get(B + "/api/state").json()["news"]
check(not j.get("due") and not j.get("unread_me"), f"(7) collab off: no deadline lines: {j}")

sys.exit(done("p21037_b_due"))
