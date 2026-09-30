#!/usr/bin/env python3
"""1.1 API tests: "Getting started" sample list + welcome tour for NEW accounts only (setup, user admin),
language / device / module awareness, idempotency, existing accounts never, KALMIDO_ONBOARDING=0, and the
new user settings (celebrate, tour). Starts its OWN test containers (start.sh, KALMIDO_ONBOARDING=1).
usage: v11_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
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


def start(onboarding="1", keep=False):
    env = {**os.environ, "KALMIDO_ONBOARDING": onboarding}
    if keep:
        env["KEEP"] = "1"
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, env=env, stdout=subprocess.DEVNULL)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def setup(user="alice"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/setup", json={"username": user, "display_name": user.capitalize(), "password": "password123"})
    assert r.ok, r.text
    return sess(user)


def state(s):
    return s.get(B + "/api/state").json()


def onboarding_list(st, name):
    ls = [l for l in st["lists"] if l["name"] == name]
    if not ls:
        return None, []
    return ls[0], [t for t in st["tasks"] if t["list_id"] == ls[0]["id"]]


# ---- 1: first admin after setup: pending, created once (desktop, English), idempotent
start("1")
a = setup("alice")
st = state(a)
check(st["settings"].get("onboard") == "pending" and st["settings"].get("tour") == "pending", "setup: onboard + tour pending")
check(len([l for l in st["lists"] if not l["is_inbox"]]) == 0, "setup: nothing created before the first start")
r = a.post(B + "/api/onboarding", json={"touch": False, "mac": False}).json()
check(r.get("created") is True, "onboarding: created")
st = state(a)
lst, ts = onboarding_list(st, "Getting started")
titles = [t["title"] for t in ts if not t["parent_id"]]
check(lst is not None and lst["color"] == "#2dd4bf", "list 'Getting started' (mint)")
check(titles[:4] == ["Tick me off", "Click me for details, notes and subtasks", "Try quick add: Dentist tomorrow 3pm !high #private",
                     "Drag me onto Tomorrow in the sidebar"], "desktop titles in order: " + repr(titles[:4]))
check("Press Ctrl+K to search and run commands" in titles, "desktop: Ctrl+K task")
today = st["settings"] and [t for t in ts if t["title"] == "Tick me off"][0]["due"]
check(today and all(t["due"] == today for t in ts if t["title"] in titles[:4]), "first four tasks due today")
check(all(not t["due"] for t in ts if t["title"] not in titles[:4]), "module tasks without a date")
check([t["priority"] for t in ts if t["title"] == "Tick me off"] == [5], "priority on the first task (bar)")
det = [t for t in ts if t["title"].startswith("Click me")][0]
check(len([t for t in ts if t["parent_id"] == det["id"]]) == 2 and "- [ ]" in det["content"], "details task: 2 subtasks + checklist")
for t in ("Create a habit under Habits", "Start a focus timer on a task", "Share this list with someone", "Start a timer on a task"):
    check(t in titles, "all modules on: " + t)
check(titles[-1] == "Delete this list when you are done", "last task: delete the list")
check(st["settings"]["onboard"] == "done", "onboard -> done")
r = a.post(B + "/api/onboarding", json={"touch": False}).json()
check(r.get("created") is False and len([l for l in state(a)["lists"] if l["name"] == "Getting started"]) == 1, "second call: nothing new")
# settings: tour can only be finished, onboard is server-only, celebrate is a flag
check(a.patch(B + "/api/settings", json={"tour": "done"}).ok and state(a)["settings"]["tour"] == "done", "tour -> done")
check(a.patch(B + "/api/settings", json={"tour": "pending"}).status_code == 400, "tour -> pending refused")
a.patch(B + "/api/settings", json={"onboard": "pending"})
check(state(a)["settings"]["onboard"] == "done", "onboard not writable by the client")
check(st["settings"].get("celebrate") == "1", "celebrate on by default")
check(a.patch(B + "/api/settings", json={"celebrate": "0"}).ok and state(a)["settings"]["celebrate"] == "0", "celebrate off")
check(a.patch(B + "/api/settings", json={"celebrate": "maybe"}).status_code == 400, "celebrate: invalid value refused")
a.patch(B + "/api/settings", json={"celebrate": "1"})

# ---- 2: new users from the user admin: own language, touch device, module-aware
r = a.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
check(r.ok, "admin creates bob")
b = sess("bob")
check(state(b)["settings"]["onboard"] == "pending" and state(b)["settings"]["tour"] == "pending", "bob: pending")
b.patch(B + "/api/settings", json={"lang": "de"})
b.post(B + "/api/onboarding", json={"touch": True, "mac": False})
lst, ts = onboarding_list(state(b), "Erste Schritte")
titles = [t["title"] for t in ts if not t["parent_id"]]
check(lst is not None, "bob: German list name 'Erste Schritte'")
check("Hak mich ab" in titles and "Wisch mich nach links zum Verschieben" in titles and "Tipp mich an für Details, Notizen und Unteraufgaben" in titles, "bob: German touch titles " + repr(titles[:4]))
check(not any(t.startswith("Drück") for t in titles), "touch: no keyboard task")
check(not [l for l in state(a)["lists"] if l["name"] == "Erste Schritte"], "alice does not see bob's list")
a.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"})
c = sess("carol")
c.patch(B + "/api/settings", json={"features": "cal,matrix,pomo,kanban,collab,stats,progress"})
c.post(B + "/api/onboarding", json={"touch": False, "mac": True})
_, ts = onboarding_list(state(c), "Getting started")
titles = [t["title"] for t in ts if not t["parent_id"]]
check("Create a habit under Habits" not in titles and "Start a timer on a task" not in titles, "modules off: no habit / timer task")
check("Start a focus timer on a task" in titles and "Share this list with someone" in titles, "modules on: focus + share task")
check("Press ⌘K to search and run commands" in titles, "Mac: ⌘K")
a.patch(B + "/api/admin/settings", json={"collab_all": False})
a.post(B + "/api/users", json={"username": "dave", "display_name": "Dave", "password": "password123"})
dv = sess("dave")
dv.post(B + "/api/onboarding", json={})
_, ts = onboarding_list(state(dv), "Getting started")
check(ts and "Share this list with someone" not in [t["title"] for t in ts], "collaboration off for the server: no share task")
a.patch(B + "/api/admin/settings", json={"collab_all": True})

# ---- 3: existing accounts (from before 1.1: no tour / onboard rows) never get it
db = sqlite3.connect(os.path.join(DATA, "tasks.db"))
db.execute("DELETE FROM user_settings WHERE key IN ('tour','onboard','celebrate') AND user_id=(SELECT id FROM users WHERE username='dave')")
db.commit()
db.close()
start("1", keep=True)
dv = sess("dave")
s = state(dv)["settings"]
check(s["tour"] == "done" and s["onboard"] == "done" and s["celebrate"] == "1", "existing account after restart: tour/onboard done, celebrate on")

# ---- 4: KALMIDO_ONBOARDING=0: new accounts start empty
start("0")
a = setup("alice")
s = state(a)["settings"]
check(s["onboard"] == "done" and s["tour"] == "done", "KALMIDO_ONBOARDING=0: nothing pending after setup")
check(a.post(B + "/api/onboarding", json={}).json().get("created") is False, "KALMIDO_ONBOARDING=0: endpoint creates nothing")
a.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
check(state(sess("bob"))["settings"]["onboard"] == "done", "KALMIDO_ONBOARDING=0: new user not pending")
# static files of 1.1: fonts with the right type, quips
r = requests.get(B + "/static/fonts/Geist-Variable.woff2")
check(r.ok and r.headers.get("Content-Type") == "font/woff2", "Geist font served as font/woff2")
q = requests.get(B + "/static/sloth-quips.json").json()
check(len(q.get("en", [])) >= 50 and len(q.get("de", [])) >= 50, "sloth quips: 50 en + 50 de")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
