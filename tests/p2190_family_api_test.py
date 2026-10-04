#!/usr/bin/env python3
"""2.19.0 API tests: the module "Family" (#653), own container (start.sh) with the fake CardDAV server (fake_carddav.py)
inside. "What do you use Kalmido for?" (setup + /api/me/purpose: modules, starter lists once, in the person's language),
birthdays + anniversaries (validation, next date, 29 February, age, reminders, gift ideas kept when the year rolls on),
household deadlines (types, notice period, the next term of a passed contract), household rotation (who, rights, the next
person per completion with undo, by hand, weekly in the watchdog, moving a task), who comes along (validation, a
participant / kid sees the task, reminders for everyone), kid accounts (participant only, parents, stars per completion +
undo + reopen, bonus stars, rewards: request / approve / decline / once, rights), shopping lists (areas, the area memory,
amounts), meal ingredients to the shopping list (no doubles), packing templates, the overview GET /api/family, CardDAV
address books (discovery, BDAY / ANNIVERSARY / Apple dates, updates, sealed password, errors, private), REST API v1 + OpenAPI."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def until(fn, secs=20):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def dbx(q, a=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok, u
    return s


class Api:
    def __init__(self, token):
        self.h = {"Authorization": "Bearer " + token}

    def __getattr__(self, m):
        return lambda path, **kw: requests.request(m.upper(), B + "/api/v1" + path, headers=self.h, **kw)


def ntfy():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8")]
    except OSError:
        return []


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8096 -e KALMIDO_CALENDAR_TICK=1")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "fake_carddav.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_carddav.py"])
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
today = date.today()

# ================================================================== the setup: "What do you use Kalmido for?" = Family (German)
r = A.post(B + "/api/admin/setup", json={"lang": "de", "collab_all": True, "time_all": True,
                                          "modules": ["cal", "habits", "comments", "family"], "purpose": "family"})
check(r.ok, "setup with purpose family " + r.text[:200])
A.patch(B + "/api/settings", json={"tour": "done"})
st = A.get(B + "/api/state").json()
fs = st["settings"]["features"].split(",")
check("family" in fs and "collab" in fs and "timeline" not in fs and st["settings"]["purpose"] == "family", f"modules of the family setup: {fs}")
fl = {l["family"]: l for l in st["lists"] if l["family"]}
check(set(fl) == {"shopping", "household", "birthdays", "meals"}, f"four starter lists {sorted(fl)}")
check(fl["shopping"]["name"] == "Einkaufsliste" and fl["meals"]["name"] == "Essensplan" and all(l["folder"] == "Familie" for l in fl.values()),
      "… named in German, in the folder Familie " + str([(l["name"], l["folder"]) for l in fl.values()]))
SHOP, HOUSE, BDAYS, MEALS = (fl[k]["id"] for k in ("shopping", "household", "birthdays", "meals"))
secs = [s["name"] for s in st["sections"] if s["list_id"] == SHOP]
check(secs[:3] == ["Obst & Gemüse", "Brot & Backwaren", "Milchprodukte & Eier"] and len(secs) == 8 and fl["shopping"]["checklist"] == 1,
      f"the shopping list: 8 shop areas, done items at the bottom {secs}")
ex = [t for t in st["tasks"] if t["list_id"] == SHOP]
check({t["title"] for t in ex} == {"Äpfel", "Brot", "Milch"} and all(t["section_id"] for t in ex), "three example items, each in its area")
chores = [t for t in st["tasks"] if t["list_id"] == HOUSE]
check(len(chores) == 4 and all(t["repeat"] and t["due"] >= today.isoformat() for t in chores), "household: four repeating chores " + str([(t["title"], t["repeat"], t["due"]) for t in chores]))
meal = [t for t in st["tasks"] if t["list_id"] == MEALS]
check(len(meal) == 1 and meal[0]["due"] == today.isoformat() and "- Tomaten" in meal[0]["content"], "a meal for today with its ingredients")
check("Familie" in json.loads(st["settings"]["folders"]), "the folder is in the folder order")
r = A.post(B + "/api/me/purpose", json={"purpose": "family"})
check(r.ok and r.json()["created"] == [] and len([l for l in A.get(B + "/api/state").json()["lists"] if l["family"]]) == 4,
      "purpose family again: no second set of lists")
r = A.post(B + "/api/me/purpose", json={"purpose": "software"})
fs = r.json()["features"].split(",")
check(r.ok and len(r.json()["created"]) == 1 and "family" not in fs and {"kanban", "deps", "time", "timeline"} <= set(fs), f"purpose software: a project, the modules {fs}")
check(A.post(B + "/api/me/purpose", json={"purpose": "software"}).json()["created"] == [], "… once")
r = A.post(B + "/api/me/purpose", json={"purpose": "me"})
check(r.json()["features"].split(",") == ["cal"] or set(r.json()["features"].split(",")) <= {"cal", "paperless", "agents"}, "purpose me: the simple start " + r.json()["features"])
check(A.post(B + "/api/me/purpose", json={"purpose": "zoo"}).status_code == 400, "an unknown purpose: 400")
check(A.patch(B + "/api/settings", json={"purpose": "team"}).ok and A.get(B + "/api/state").json()["settings"]["purpose"] == "me", "purpose is server-only (PATCH /settings ignores it)")
A.post(B + "/api/me/purpose", json={"purpose": "family", "examples": False})
A.patch(B + "/api/settings", json={"lang": "en"})

# ================================================================== people: Bob (parent), Lina (kid), Max (another kid), Eve (stranger)
ids = {"alice": 1}
for u, n, kid in (("bob", "Bob", False), ("lina", "Lina", True), ("max", "Max", True), ("eve", "Eve", False)):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "kid": kid, **({"parents": [1]} if kid else {})})
    check(r.ok, f"user {u} " + r.text[:200])
    ids[u] = r.json()["id"]
BOB, LINA, MAX, EVE = ids["bob"], ids["lina"], ids["max"], ids["eve"]
for u in ("bob", "lina", "max", "eve"):
    A.patch(B + f"/api/users/{ids[u]}", json={"ntfy_topic": "t-" + u})
Bo, Li, Mx, Ev = (sess(u) for u in ("bob", "lina", "max", "eve"))
for s_ in (Bo, Li, Mx, Ev):
    s_.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "push_channel": "ntfy", "features": "cal,collab,comments,family"})
us = {u["id"]: u for u in A.get(B + "/api/users").json()["users"]}
check(us[LINA].get("kid") is True and us[LINA]["parents"] == [1] and not us[BOB].get("kid"), "admin list: kid flag + parents")
check(A.patch(B + f"/api/users/{LINA}", json={"is_admin": True}).status_code == 400, "a kid cannot become an admin")
check(A.patch(B + f"/api/users/{LINA}", json={"parents": [MAX]}).status_code == 400, "a kid is no parent")
check(A.patch(B + f"/api/users/{LINA}", json={"parents": [1, BOB]}).ok, "Bob is a parent of Lina too")
check(A.patch(B + f"/api/users/{BOB}", json={"kid": True, "is_admin": True}).status_code == 400, "kid + admin at once: 400")
for lid in (SHOP, HOUSE, MEALS):
    check(A.put(B + f"/api/lists/{lid}/members", json={"user_id": BOB, "role": "edit"}).ok, "share with Bob")
    A.put(B + f"/api/lists/{lid}/members", json={"user_id": LINA, "role": "edit"})
roles = dict(dbx("SELECT list_id, role FROM list_members WHERE user_id=?", (LINA,)))
check(set(roles.values()) == {"participant"}, f"a kid shared as Member takes part as participant {roles}")

# ================================================================== birthdays + anniversaries
nd = today + timedelta(days=5)
r = A.post(B + "/api/family/occasions", json={"name": "Grandma Erika", "date": f"1946-{nd:%m-%d}", "gifts": ["Book", "Scarf"]})
check(r.status_code == 201, "a birthday " + r.text[:200])
O = r.json()
check(O["title"] == "Birthday: Grandma Erika" and O["due"] == nd.isoformat() and O["repeat"] == "FREQ=YEARLY" and O["reminders"] == "10080,0",
      f"title, the next date, yearly, reminded 7 days before + on the day {O['title']} {O['due']} {O['reminders']}")
check(O["fam"] == {"kind": "birthday", "name": "Grandma Erika", "year": 1946, "lead": 7} and O["list_id"] == BDAYS, f"fam + the Birthdays list {O['fam']}")
gifts = [t for t in A.get(B + "/api/state").json()["tasks"] if t["parent_id"] == O["id"]]
check([g["title"] for g in sorted(gifts, key=lambda t: t["sort"])] == ["Book", "Scarf"], "gift ideas are subtasks")
past = today - timedelta(days=3)
r = A.post(B + "/api/family/occasions", json={"name": "Mum & Dad", "kind": "anniversary", "date": f"--{past:%m-%d}", "year": 1998, "lead_days": 0})
check(r.status_code == 201 and r.json()["due"] == past.replace(year=past.year + 1).isoformat() and r.json()["reminders"] == "0",
      "an anniversary that was 3 days ago: next year; lead 0 = on the day only " + r.text[:160])
ANNIV = r.json()["id"]
r = A.post(B + "/api/family/occasions", json={"name": "Leapling", "date": "2000-02-29"})
check(r.status_code == 201 and r.json()["repeat"] == "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1" and r.json()["due"][5:] in ("02-28", "02-29"),
      "29 February: the last day of February every year " + r.text[:200])
for bad, why in (({"date": "1990-01-01"}, "no name"), ({"name": "X", "date": "1990-02-30"}, "30 February"), ({"name": "X", "date": "abc"}, "no date"),
                 ({"name": "X", "date": "--01-01", "year": 1700}, "year too early"), ({"name": "X", "date": "--01-01", "year": today.year + 1}, "a future year"),
                 ({"name": "X", "date": "--01-01", "kind": "wedding"}, "unknown kind"), ({"name": "X", "date": "--01-01", "lead_days": 999}, "lead too long"),
                 ({"name": "X", "date": "--01-01", "list_id": 99999}, "unknown list")):
    check(A.post(B + "/api/family/occasions", json=bad).status_code in (400, 404), "occasion refused: " + why)
check(Ev.post(B + "/api/family/occasions", json={"name": "X", "date": "--01-01", "list_id": BDAYS}).status_code == 404, "someone else's list: 404")
# completing rolls on a year; the ticked gift idea stays ticked
A.post(B + f"/api/tasks/{gifts[0]['id']}/complete", json={})
j = A.post(B + f"/api/tasks/{O['id']}/complete", json={}).json()
check(j["next_due"] == nd.replace(year=nd.year + 1).isoformat(), "congratulated: next year " + str(j.get("next_due")))
g2 = {t["id"]: t["status"] for t in A.get(B + "/api/state").json()["tasks"] if t["parent_id"] == O["id"]}
check(g2.get(gifts[0]["id"]) == 2 and g2.get(gifts[1]["id"]) == 0, f"the given gift stays ticked, the other stays an idea {g2}")
A.post(B + f"/api/tasks/{O['id']}/undo", json=j["undo"])
check(A.get(B + f"/api/tasks/{O['id']}").json()["due"] == nd.isoformat(), "undo: back to this year")
# editing the family data
r = A.patch(B + f"/api/tasks/{O['id']}", json={"fam": {"kind": "birthday", "name": "Oma Erika", "year": 1945}})
check(r.ok and r.json()["fam"]["year"] == 1945, "fam can be changed")
for bad in ({"kind": "x"}, {"kind": "birthday", "name": 5}, {"kind": "birthday", "name": "a", "year": 1500}, {"kind": "birthday", "name": "a", "evil": 1},
            {"kind": "deadline", "type": "rocket"}, {"kind": "deadline", "expires": "2026-02-30"}):
    check(A.patch(B + f"/api/tasks/{O['id']}", json={"fam": bad}).status_code == 400, f"fam refused: {bad}")

# ================================================================== household deadlines
exp = today + timedelta(days=60)
r = A.post(B + "/api/family/deadlines", json={"type": "passport", "who": "Lina", "expires": exp.isoformat()})
P = r.json()
check(r.status_code == 201 and P["title"] == "Renew the passport: Lina" and P["due"] == exp.isoformat() and P["deadline"] == 2 and P["reminders"] == "129600,0"
      and P["list_id"] == HOUSE and P["fam"]["type"] == "passport", "passport: due on expiry, reminded 90 days before " + str((P.get("title"), P.get("reminders"))))
end = today + timedelta(days=200)
r = A.post(B + "/api/family/deadlines", json={"type": "insurance", "who": "Car insurance", "expires": end.isoformat()})
I = r.json()
due_i = date(end.year, end.month, end.day)
m = due_i.month - 3
y = due_i.year + (m - 1) // 12
m = (m - 1) % 12 + 1
check(r.status_code == 201 and I["repeat"] == "FREQ=YEARLY" and I["fam"]["notice"] == 3 and I["due"][:7] == f"{y:04d}-{m:02d}",
      f"insurance: due 3 months before the end, every year {I.get('due')} {I.get('repeat')}")
r = A.post(B + "/api/family/deadlines", json={"type": "contract", "who": "Gym", "expires": (today + timedelta(days=10)).isoformat()})
C_ = r.json()
check(r.status_code == 201 and C_["due"] > today.isoformat() and C_["fam"]["expires"] > (today + timedelta(days=300)).isoformat(),
      f"a contract whose last day to cancel has passed: the next term {C_.get('due')} {C_.get('fam')}")
check(A.post(B + "/api/family/deadlines", json={"type": "car", "who": "Car", "expires": exp.isoformat()}).json()["repeat"] == "FREQ=YEARLY;INTERVAL=2", "car inspection: every two years")
check(A.post(B + "/api/family/deadlines", json={"type": "other", "expires": exp.isoformat()}).status_code == 400, "other without a name: 400")
check(A.post(B + "/api/family/deadlines", json={"type": "other", "who": "Library books", "expires": exp.isoformat()}).json()["title"] == "Library books", "other: the name is the title")
check(A.post(B + "/api/family/deadlines", json={"type": "passport"}).status_code == 400, "no date: 400")
types = A.get(B + "/api/family/deadline-types").json()["types"]
check([t["key"] for t in types] == ["passport", "id_card", "car", "insurance", "contract", "other"], "the deadline types")

# ================================================================== household rotation
chore = chores[0]["id"]
r = A.patch(B + f"/api/tasks/{chore}", json={"rotation": {"who": [1, BOB, LINA], "mode": "done"}})
check(r.ok and r.json()["assignee_id"] == 1 and r.json()["rotation"]["who"] == [1, BOB, LINA], "rotation set: Alice first " + r.text[:200])
for bad, why in (({"who": [1]}, "one person"), ({"who": [1, EVE]}, "someone without the list"), ({"who": [1, 1]}, "twice the same"),
                 ({"who": [1, BOB], "mode": "daily"}, "unknown mode"), ({"who": [1, BOB], "evil": 1}, "unknown key"), ({"who": "1,2"}, "not a list")):
    check(A.patch(B + f"/api/tasks/{chore}", json={"rotation": bad}).status_code == 400, "rotation refused: " + why)
check(Li.patch(B + f"/api/tasks/{chore}", json={"rotation": {"who": [LINA, BOB]}}).status_code in (403, 404), "a participant cannot set a rotation")
n0 = len(ntfy())
j = A.post(B + f"/api/tasks/{chore}/complete", json={}).json()
t = A.get(B + f"/api/tasks/{chore}").json()
check(t["assignee_id"] == BOB and t["rotation"]["i"] == 1 and j["next_due"], f"completed: Bob's turn {t['assignee_id']} {t['rotation']}")
check(until(lambda: any(x["topic"] == "t-bob" for x in ntfy()[n0:]), 10), "Bob gets the assignment push")
cp = dbx("SELECT rotation, status FROM tasks WHERE title=? AND status=2 AND list_id=?", (chores[0]["title"], HOUSE))
check(cp and cp[0][0] == "", "the done copy carries no rotation")
A.post(B + f"/api/tasks/{chore}/undo", json=j["undo"])
t = A.get(B + f"/api/tasks/{chore}").json()
check(t["assignee_id"] == 1 and t["rotation"]["i"] == 0, f"undo: Alice's turn again {t['assignee_id']} {t['rotation']}")
Bo.post(B + f"/api/tasks/{chore}/complete", json={})
Bo.post(B + f"/api/tasks/{chore}/complete", json={})
t = A.get(B + f"/api/tasks/{chore}").json()
check(t["assignee_id"] == LINA, "two more: Lina's turn (a kid takes part in the rotation)")
check(any(x["id"] == chore for x in Li.get(B + "/api/state").json()["tasks"]), "… and Lina sees it now")
check(A.patch(B + f"/api/tasks/{chore}", json={"assignee_id": BOB}).json()["rotation"]["i"] == 1, "assigned by hand: the turn continues from Bob")
# weekly
chore2 = chores[1]["id"]
r = A.patch(B + f"/api/tasks/{chore2}", json={"rotation": {"who": [BOB, 1], "mode": "week"}})
check(r.ok and r.json()["assignee_id"] == BOB and r.json()["rotation"]["wk"], "weekly rotation starts with Bob, this week")
rot = json.loads(dbx("SELECT rotation FROM tasks WHERE id=?", (chore2,))[0][0])
rot["wk"] = "2020-W01"
dbx("UPDATE tasks SET rotation=? WHERE id=?", (json.dumps(rot), chore2))
n0 = len(ntfy())
check(until(lambda: A.get(B + f"/api/tasks/{chore2}").json()["assignee_id"] == 1, 15), "a new week (watchdog): Alice's turn")
check(json.loads(dbx("SELECT rotation FROM tasks WHERE id=?", (chore2,))[0][0])["wk"] != "2020-W01", "… once per week")
check(until(lambda: True, 1) and dbx("SELECT COUNT(*) FROM activity WHERE task_id=? AND kind='rotation'", (chore2,))[0][0] == 1, "an activity line")
check(Bo.patch(B + f"/api/tasks/{chore2}", json={"rotation": None}).json().get("rotation") is None, "rotation off (a member)")
# moving a rotating task into another list: only its people stay
r = A.patch(B + f"/api/tasks/{chore}", json={"list_id": BDAYS})
check(r.ok and r.json().get("rotation") is None, "moved to a list nobody else shares: the rotation ends " + str(r.json().get("rotation")))
A.patch(B + f"/api/tasks/{chore}", json={"list_id": HOUSE})

# ================================================================== who comes along (family events)
ev_due = (today + timedelta(days=1)).isoformat()
r = A.post(B + "/api/tasks", json={"title": "Zoo trip", "list_id": HOUSE, "due": ev_due, "due_time": "10:00", "people": [BOB, LINA]})
EVT = r.json()
check(r.ok and EVT["people"] == [BOB, LINA], "an event with people " + r.text[:200])
check(any(x["id"] == EVT["id"] for x in Li.get(B + "/api/state").json()["tasks"]), "Lina (participant) sees the event she comes along to")
check(not any(x["title"] == "Water the plants" for x in Li.get(B + "/api/state").json()["tasks"]), "… but not the other chores")
check(A.patch(B + f"/api/tasks/{EVT['id']}", json={"people": [EVE]}).status_code == 400, "people: only those sharing the list")
check(A.patch(B + f"/api/tasks/{EVT['id']}", json={"people": "x"}).status_code == 400, "people: a list")
# reminders: everyone who comes along
dbx("UPDATE tasks SET due=?, due_time=?, reminders='0', reminded='[]' WHERE id=?",
    ((datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d"), (datetime.now() - timedelta(minutes=1)).strftime("%H:%M"), EVT["id"]))
n0 = len(ntfy())
check(until(lambda: {x["topic"] for x in ntfy()[n0:] if x["title"] == "Zoo trip"} >= {"t-bob", "t-lina"}, 15),
      "the reminder reaches Bob and Lina " + str([(x["topic"], x["title"]) for x in ntfy()[n0:]]))

# ================================================================== kids: stars + rewards
KT = A.post(B + "/api/tasks", json={"title": "Tidy up your room", "list_id": HOUSE, "assignee_id": LINA, "stars": 3}).json()
KT2 = A.post(B + "/api/tasks", json={"title": "Feed the cat", "list_id": HOUSE, "assignee_id": LINA}).json()
check(KT.get("stars") == 3 and "stars" not in KT2, "stars on a task (default = not stored)")
check(A.patch(B + f"/api/tasks/{KT2['id']}", json={"stars": 99}).status_code == 400, "at most 50 stars")
st_l = Li.get(B + "/api/state").json()
check(st_l["me"].get("kid") is True and st_l["kids"][0]["id"] == LINA and st_l["kids"][0]["stars"] == 0, "the kid's state: itself, 0 stars")
j = Li.post(B + f"/api/tasks/{KT['id']}/complete", json={}).json()
check(Li.get(B + "/api/family/kids").json()["kids"][0]["stars"] == 3, "completed by the kid: +3 stars")
Li.post(B + f"/api/tasks/{KT['id']}/undo", json=j["undo"])
check(Li.get(B + "/api/family/kids").json()["kids"][0]["stars"] == 0, "undo: the stars are gone again")
Li.post(B + f"/api/tasks/{KT['id']}/complete", json={})
Li.post(B + f"/api/tasks/{KT2['id']}/complete", json={})
check(Li.get(B + "/api/family/kids").json()["kids"][0]["stars"] == 4, "3 + 1 (default)")
Li.post(B + f"/api/tasks/{KT2['id']}/reopen", json={})
check(Li.get(B + "/api/family/kids").json()["kids"][0]["stars"] == 3, "reopened: its star is taken back")
A.post(B + f"/api/tasks/{KT2['id']}/complete", json={})
check(Li.get(B + "/api/family/kids").json()["kids"][0]["stars"] == 3, "a parent completing it gives no stars")
r = Bo.post(B + f"/api/family/kids/{LINA}/stars", json={"delta": 5, "note": "helped with the dishes"})
check(r.ok and r.json()["stars"] == 8 and r.json()["history"][0]["title"] == "helped with the dishes", "Bob (parent) gives 5 stars")
check(Ev.post(B + f"/api/family/kids/{LINA}/stars", json={"delta": 5}).status_code == 404, "a stranger: 404")
check(Li.post(B + f"/api/family/kids/{LINA}/stars", json={"delta": 5}).status_code in (403, 404), "the kid itself: no")
check(Li.patch(B + f"/api/tasks/{KT['id']}", json={"stars": 50}).status_code == 403 and A.get(B + f"/api/tasks/{KT['id']}").json()["stars"] == 3,
      "a kid cannot change its own stars (403)")
check(Li.post(B + "/api/lists", json={"name": "Mine"}).status_code == 403 and Li.post(B + "/api/tasks", json={"title": "x", "list_id": HOUSE}).status_code == 403,
      "a kid creates no lists or tasks")
check(Li.patch(B + "/api/settings", json={"allday_time": "08:00"}).ok, "… but its own settings, yes")
check(Bo.post(B + f"/api/family/kids/{LINA}/stars", json={"delta": -50}).status_code == 409, "not below zero")
check(Bo.post(B + f"/api/family/kids/{LINA}/stars", json={"delta": 0}).status_code == 400, "0: 400")
check(A.post(B + f"/api/family/kids/{BOB}/stars", json={"delta": 1}).status_code == 404, "Bob is no kid")
check(A.post(B + f"/api/family/kids/{MAX}/stars", json={"delta": 1}).ok, "an admin looks after every kid")
check(Bo.post(B + f"/api/family/kids/{MAX}/stars", json={"delta": 1}).status_code == 404, "Bob is not Max's parent")
r = A.post(B + f"/api/family/kids/{LINA}/rewards", json={"title": "Ice cream", "cost": 5, "emoji": "🍦"})
ICE = r.json()["id"]
check(r.status_code == 201 and r.json()["state"] == "open" and not r.json()["once"], "a reward")
ZOO = A.post(B + f"/api/family/kids/{LINA}/rewards", json={"title": "Zoo", "cost": 20, "once": True}).json()["id"]
check(A.post(B + f"/api/family/kids/{LINA}/rewards", json={"title": "", "cost": 5}).status_code == 400, "a reward needs a title")
check(A.post(B + f"/api/family/kids/{LINA}/rewards", json={"title": "x", "cost": 0}).status_code == 400, "cost >= 1")
check(Li.post(B + f"/api/family/kids/{LINA}/rewards", json={"title": "x", "cost": 1}).status_code in (403, 404), "a kid cannot add rewards")
check(Li.post(B + f"/api/family/rewards/{ZOO}/request").status_code == 409, "not enough stars: 409")
n0 = len(ntfy())
r = Li.post(B + f"/api/family/rewards/{ICE}/request")
check(r.ok and next(x for x in r.json()["rewards"] if x["id"] == ICE)["state"] == "requested", "Lina asks for ice cream")
check(until(lambda: {x["topic"] for x in ntfy()[n0:] if "would like a reward" in x["title"]} >= {"t-bob"}, 10), "her parents get a push")
check(Li.post(B + f"/api/family/rewards/{ICE}/request").status_code == 409, "asked twice: 409")
check(Bo.post(B + f"/api/family/rewards/{ICE}/request").status_code == 403, "only the kid asks")
r = Bo.post(B + f"/api/family/rewards/{ICE}/decide", json={"approve": True})
check(r.ok and r.json()["stars"] == 3 and next(x for x in r.json()["rewards"] if x["id"] == ICE)["state"] == "open", "approved: -5 stars, it can be asked for again")
check(Bo.post(B + f"/api/family/rewards/{ICE}/decide", json={"approve": False}).status_code == 409, "decline without a request: 409")
Bo.post(B + f"/api/family/kids/{LINA}/stars", json={"delta": 30})
Li.post(B + f"/api/family/rewards/{ZOO}/request")
r = Bo.post(B + f"/api/family/rewards/{ZOO}/decide", json={"approve": False})
check(r.ok and next(x for x in r.json()["rewards"] if x["id"] == ZOO)["state"] == "open" and r.json()["stars"] == 33, "declined: open again, stars kept")
r = A.post(B + f"/api/family/rewards/{ZOO}/decide", json={"approve": True})
check(r.ok and next(x for x in r.json()["rewards"] if x["id"] == ZOO)["state"] == "redeemed" and r.json()["stars"] == 13, "redeemed right away (once): gone for good")
check(A.post(B + f"/api/family/rewards/{ZOO}/decide", json={"approve": True}).status_code == 409, "redeemed twice: 409")
check(A.patch(B + f"/api/family/rewards/{ICE}", json={"cost": 7}).json()["cost"] == 7, "a parent changes a reward")
check(Ev.patch(B + f"/api/family/rewards/{ICE}", json={"cost": 1}).status_code == 404, "a stranger: 404")
check(Li.delete(B + f"/api/family/rewards/{ICE}").status_code in (403, 404), "the kid cannot delete")
kd = A.get(B + "/api/family/kids").json()["kids"]
check({k["id"] for k in kd} == {LINA, MAX}, "an admin sees every kid")
check([k["id"] for k in Bo.get(B + "/api/family/kids").json()["kids"]] == [LINA], "Bob sees his kid")
check(Ev.get(B + "/api/family/kids").json()["kids"] == [], "a stranger sees none")

# ================================================================== shopping lists: areas + the area memory
st = A.get(B + "/api/state").json()
area = {s["name"]: s["id"] for s in st["sections"] if s["list_id"] == SHOP}
milk = next(t for t in st["tasks"] if t["list_id"] == SHOP and t["title"] == "Milch")
check(milk["section_id"] == area["Milchprodukte & Eier"], "the example milk is in the dairy area")
t1 = A.post(B + "/api/tasks", json={"title": "2 l Milch", "list_id": SHOP}).json()
check(t1["section_id"] == area["Milchprodukte & Eier"], "a new '2 l Milch' goes to the dairy area (amount ignored)")
nut = A.post(B + "/api/tasks", json={"title": "Nutella", "list_id": SHOP}).json()
check(nut["section_id"] is None, "an unknown item: no area")
ban = A.post(B + "/api/tasks", json={"title": "Bananen", "list_id": SHOP}).json()
spa = A.post(B + "/api/tasks", json={"title": "1 kg Reis", "list_id": SHOP}).json()
check(ban["section_id"] == area["Obst & Gemüse"] and spa["section_id"] == area["Vorrat"], "a first guess for common items: Bananen -> fruit, Reis -> pantry")
Bo.patch(B + f"/api/tasks/{nut['id']}", json={"section_id": area["Vorrat"]})
nut2 = Bo.post(B + "/api/tasks", json={"title": "1 Glas Nutella", "list_id": SHOP}).json()
check(nut2["section_id"] == area["Vorrat"], "moved once to Pantry: the next Nutella goes there too")
r = A.post(B + "/api/lists", json={"name": "Weekend shop", "family": "shopping"})
check(r.ok and r.json()["family"] == "shopping" and r.json()["checklist"] == 1, "a new shopping list")
WS = r.json()["id"]
check(len([s for s in A.get(B + "/api/state").json()["sections"] if s["list_id"] == WS]) == 8, "… with the 8 areas (English)")
L2 = A.post(B + "/api/lists", json={"name": "Plain"}).json()["id"]
r = A.post(B + f"/api/lists/{L2}/shop-areas")
check(r.ok and r.json()["added"] == 8 and A.post(B + f"/api/lists/{L2}/shop-areas").json()["added"] == 0, "shop areas for an existing list, once")
L3 = A.post(B + "/api/lists", json={"name": "Drugstore"}).json()["id"]
check(A.patch(B + f"/api/lists/{L3}", json={"family": "shopping"}).ok and len([s for s in A.get(B + "/api/state").json()["sections"] if s["list_id"] == L3]) == 8,
      "a list switched to 'Used for: Shopping list' gets the areas too (the list dialog's way)")
check(next(l for l in A.get(B + "/api/state").json()["lists"] if l["id"] == L2)["family"] == "shopping", "… which becomes a shopping list")
check(A.patch(B + f"/api/lists/{L2}", json={"family": "rocket"}).status_code == 400, "an unknown list kind: 400")
check(Bo.patch(B + f"/api/lists/{SHOP}", json={"family": ""}).status_code == 403, "only the owner changes what a list is for")

# ================================================================== meal plan -> shopping list
MEAL = meal[0]["id"]
r = A.post(B + f"/api/tasks/{MEAL}/to-shopping", json={})
j = r.json()
check(r.ok and j["list_id"] == SHOP and [x["title"] for x in j["added"]] == ["Spaghetti", "Tomaten", "Zwiebel", "Parmesan"] and j["skipped"] == [],
      "the ingredients go to the shopping list " + r.text[:200])
j = A.post(B + f"/api/tasks/{MEAL}/to-shopping", json={}).json()
check(j["added"] == [] and len(j["skipped"]) == 4, "again: nothing doubled")
r = A.post(B + "/api/tasks", json={"title": "Pancakes", "list_id": MEALS, "due": today.isoformat(),
                                   "content": "# Pancakes\n- [x] Flour\n- [ ] 3 Eggs\n* 500 ml Milch\nsome text"})
j = A.post(B + f"/api/tasks/{r.json()['id']}/to-shopping", json={"list_id": WS}).json()
check([x["title"] for x in j["added"]] == ["3 Eggs", "500 ml Milch"], "only open checklist / bullet lines; into the chosen list " + str(j))
j = A.post(B + f"/api/tasks/{MEAL}/to-shopping", json={"items": ["Basilikum"]}).json()
check([x["title"] for x in j["added"]] == ["Basilikum"], "explicit items")
check(A.post(B + f"/api/tasks/{MEAL}/to-shopping", json={"list_id": L2 + 999}).status_code == 404, "unknown list: 404")
check(A.post(B + f"/api/tasks/{MEAL}/to-shopping", json={"list_id": BDAYS}).status_code == 400, "not a shopping list: 400")
empty = A.post(B + "/api/tasks", json={"title": "Leftovers", "list_id": MEALS}).json()
check(A.post(B + f"/api/tasks/{empty['id']}/to-shopping", json={}).status_code == 400, "no ingredients: 400")
check(Ev.post(B + f"/api/tasks/{MEAL}/to-shopping", json={}).status_code == 404, "a stranger: 404")

# ================================================================== packing lists
tp = A.get(B + "/api/family/packing").json()["templates"]
check([t["key"] for t in tp] == ["holiday", "pool", "daycare", "camping", "business"] and tp[0]["sections"][0]["items"], "five packing templates")
r = A.post(B + "/api/family/packing", json={"template": "pool"})
PK = r.json()["list_id"]
st = A.get(B + "/api/state").json()
pl = next(l for l in st["lists"] if l["id"] == PK)
check(r.status_code == 201 and pl["name"] == "Packing list: Swimming pool" and pl["checklist"] == 1 and pl["family"] == "packing"
      and len([t for t in st["tasks"] if t["list_id"] == PK]) == 10, "a packing list from the template (done at the bottom)")
r = Bo.post(B + "/api/family/packing", json={"template": "camping", "name": "Lake weekend"})
check(r.status_code == 201 and len([s for s in Bo.get(B + "/api/state").json()["sections"] if s["list_id"] == r.json()["list_id"]]) == 3, "camping: with sections, own name")
check(A.post(B + "/api/family/packing", json={"template": "moon"}).status_code == 400, "unknown template: 400")

# ================================================================== the overview
A.patch(B + f"/api/tasks/{chore}", json={"rotation": {"who": [1, BOB], "mode": "done"}})
ov = A.get(B + "/api/family").json()
oc = next(x for x in ov["occasions"] if x["task_id"] == O["id"])
check(oc["age"] == nd.year - 1945 and oc["days"] == 5 and oc["gifts"] == 1 and oc["kind"] == "birthday", f"overview: the birthday with age, days, open gift ideas {oc}")
check(ov["occasions"][0]["task_id"] == O["id"], "sorted by the next date")
check([d["type"] for d in ov["deadlines"]][:1] and all(d["due"] >= ov["deadlines"][0]["due"] for d in ov["deadlines"]), "deadlines by date")
check(any(x["task_id"] == chore for x in ov["rotations"]) and ov["week"] == (today - timedelta(days=today.weekday())).isoformat(), "rotations + the week (Monday)")
check({m["task_id"] for m in ov["meals"]} >= {MEAL} and next(m for m in ov["meals"] if m["task_id"] == MEAL)["ingredients"][:1] == ["Spaghetti"], "the meals of the week with ingredients")
check(next(s for s in ov["shopping"] if s["list_id"] == SHOP)["open"] >= 7 and {k["id"] for k in ov["kids"]} == {LINA, MAX}, "shopping lists + kids")
nw = A.get(B + "/api/family?week=" + (today + timedelta(days=7)).isoformat()).json()
check(nw["week"] == (today + timedelta(days=7 - today.weekday())).isoformat() and all(m["task_id"] != MEAL for m in nw["meals"]), "?week = another week")
check(A.get(B + "/api/family?week=x").status_code == 400, "a bad week: 400")
check(Ev.get(B + "/api/family").json()["occasions"] == [], "a stranger sees nothing of it")

# ================================================================== CardDAV address books
open(os.path.join(DATA, "cards.vcf"), "w", encoding="utf-8").write(
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:c1\r\nFN:Tante Anna\r\nBDAY:19600315\r\nEND:VCARD\r\n"
    "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c2\r\nFN:Onkel\r\n  Peter\r\nBDAY:--0704\r\nANNIVERSARY:1985-07-20\r\nEND:VCARD\r\n"
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:c3\r\nN:Muster;Max;;;\r\nBDAY;X-APPLE-OMIT-YEAR=1604:1604-11-02\r\nitem1.X-ABDATE:2001-09-09\r\nitem1.X-ABLabel:_$!<Anniversary>!$_\r\nEND:VCARD\r\n"
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:c4\r\nFN:No Date\r\nEND:VCARD\r\n")
r = A.post(B + "/api/family/contacts", json={"url": "http://127.0.0.1:8096/", "username": "u", "password": "wrong"})
check(r.status_code == 400 and "denied" in r.json()["error"].lower(), "a wrong password: refused, not kept " + r.text[:200])
check(A.get(B + "/api/family/contacts").json()["sources"] == [], "… nothing stored")
r = A.post(B + "/api/family/contacts", json={"url": "http://127.0.0.1:8096/", "username": "u", "password": "pw", "list_id": BDAYS, "lead_days": 3})
check(r.status_code == 201 and r.json()["count"] == 5 and r.json()["status"] == "ok", "the address book: 5 dates " + r.text[:300])
SRC = r.json()["id"]
st = A.get(B + "/api/state").json()
occ = {t["fam"]["name"] + "|" + t["fam"]["kind"]: t for t in st["tasks"] if t.get("fam", {}).get("src") == f"carddav:{SRC}"}
check(set(occ) == {"Tante Anna|birthday", "Onkel Peter|birthday", "Onkel Peter|anniversary", "Max Muster|birthday", "Max Muster|anniversary"}, f"from BDAY / ANNIVERSARY / Apple dates {sorted(occ)}")
check(occ["Tante Anna|birthday"]["fam"].get("year") == 1960 and occ["Tante Anna|birthday"]["due"][5:] == "03-15" and occ["Tante Anna|birthday"]["reminders"] == "4320,0",
      "year + date + the lead of the address book")
check("year" not in occ["Onkel Peter|birthday"]["fam"] and "year" not in occ["Max Muster|birthday"]["fam"] and occ["Max Muster|anniversary"]["fam"]["year"] == 2001,
      "no year (--MMDD, Apple's omit-year), the anniversary's year")
row = dbx("SELECT url, password FROM contact_srcs WHERE id=?", (SRC,))[0]
check(row[0].startswith("v1.") and row[1].startswith("v1.") and "pw" not in row[1] and "8096" not in row[0], "address + password sealed in the database")
check("password" not in A.get(B + "/api/family/contacts").json()["sources"][0], "the password never goes back to the client")
check(occ["Tante Anna|birthday"]["fam"].get("card") == "c1" and occ["Max Muster|anniversary"]["fam"].get("card") == "c3", "the vCard UID is kept in the task (fam.card)")
lk = dbx("SELECT uid, kind, book FROM contact_links WHERE src_id=? ORDER BY uid, kind", (SRC,))
check(len(lk) == 5 and all(x[2].startswith("v1.") and "8096" not in x[2] for x in lk), "every link: the UID + the address book's URL (sealed) " + repr([x[:2] for x in lk]))
A.patch(B + f"/api/tasks/{occ['Tante Anna|birthday']['id']}", json={"title": "Anna's 66th!"})
A.delete(B + f"/api/tasks/{occ['Onkel Peter|anniversary']['id']}")
open(os.path.join(DATA, "cards.vcf"), "w", encoding="utf-8").write(
    "BEGIN:VCARD\r\nUID:c1\r\nFN:Tante Anna B.\r\nBDAY:19600316\r\nEND:VCARD\r\n"
    "BEGIN:VCARD\r\nUID:c2\r\nFN:Onkel Peter\r\nBDAY:--0704\r\nANNIVERSARY:1985-07-20\r\nEND:VCARD\r\n"
    "BEGIN:VCARD\r\nUID:c5\r\nFN:Neue Nichte\r\nBDAY:2020-01-05\r\nEND:VCARD\r\n")
time.sleep(1.2)
r = A.post(B + f"/api/family/contacts/{SRC}/sync")
check(r.ok and r.json()["status"] == "ok", "read again " + r.text[:200])
st = A.get(B + "/api/state").json()
anna = next(t for t in st["tasks"] if t["id"] == occ["Tante Anna|birthday"]["id"])
check(anna["due"][5:] == "03-16" and anna["fam"]["name"] == "Tante Anna B." and anna["title"] == "Anna's 66th!", "a changed date + name; the own title stays")
check(sum(1 for t in st["tasks"] if t.get("fam", {}).get("card") == "c1" and not t.get("deleted_at")) == 1 and anna["fam"].get("card") == "c1", "read again: updated by UID, no second Anna")
check(not any(t.get("fam", {}).get("kind") == "anniversary" and t["fam"].get("name") == "Onkel Peter" and not t.get("deleted_at") for t in st["tasks"]),
      "a birthday deleted by hand is not created again")
check(any(t.get("fam", {}).get("name") == "Neue Nichte" for t in st["tasks"]), "a new contact: a new birthday")
check(any(t["id"] == occ["Max Muster|birthday"]["id"] for t in st["tasks"]), "a contact that is gone: its task stays")
check(Bo.post(B + f"/api/family/contacts/{SRC}/sync").status_code == 404 and Bo.get(B + "/api/family/contacts").json()["sources"] == [], "private per person")
check(A.patch(B + f"/api/family/contacts/{SRC}", json={"lead_days": 1, "name": "Family book"}).json()["lead_days"] == 1, "edit")
dbx("UPDATE contact_srcs SET tried_at=? WHERE id=?", ("2020-01-01T00:00:00+00:00", SRC))
check(until(lambda: dbx("SELECT tried_at FROM contact_srcs WHERE id=?", (SRC,))[0][0] > "2021", 15), "the daily sync runs by itself")
check(A.delete(B + f"/api/family/contacts/{SRC}").ok and any(t.get("fam", {}).get("name") == "Neue Nichte" for t in A.get(B + "/api/state").json()["tasks"]),
      "removed: the birthdays stay")
check(A.post(B + "/api/family/contacts", json={"url": "http://10.0.0.1/", "username": "u", "password": "pw"}).status_code == 400, "a private address (not allowed): refused")

# ================================================================== REST API v1 + OpenAPI
tok = A.post(B + "/api/me/tokens", json={"name": "fam", "scopes": ["read", "tasks:write", "structure", "delete"]}).json()["token"]
ro = A.post(B + "/api/me/tokens", json={"name": "ro", "scopes": ["read"]}).json()["token"]
V, R = Api(tok), Api(ro)
f1 = V.get("/family").json()
check(f1.get("occasions") and f1.get("kids") is not None, "v1: GET /family")
r = V.post("/family/occasions", json={"name": "Api Bday", "date": "1990-12-24", "gifts": ["Socks"]})
check(r.status_code == 201 and r.json()["family"]["kind"] == "birthday" and r.json()["repeat"] == "FREQ=YEARLY", "v1: an occasion (task with family) " + r.text[:200])
check(V.post("/family/occasions", json={"name": "x", "date": "--01-01", "evil": 1}).status_code == 400, "v1: unknown field refused")
check(R.post("/family/occasions", json={"name": "x", "date": "--01-01"}).status_code == 403, "v1: read scope cannot write")
r = V.post("/family/deadlines", json={"type": "id_card", "who": "Me", "expires": exp.isoformat()})
check(r.status_code == 201 and r.json()["deadline"] is True and r.json()["family"]["type"] == "id_card", "v1: a deadline")
check(V.get("/family/deadline-types").json()["types"][0]["key"] == "passport", "v1: deadline types")
t = V.get(f"/tasks/{chore}").json()
check(t["rotation"]["who"] == [1, BOB] and t["people"] == [] and t["stars"] is None, "v1 task: rotation, people, stars")
r = V.patch(f"/tasks/{EVT['id']}", json={"people": [BOB], "stars": 2})
check(r.ok and r.json()["people"] == [BOB] and r.json()["stars"] == 2, "v1: set people + stars")
r = V.patch(f"/tasks/{chore2}", json={"rotation": {"who": [1, BOB], "mode": "done"}})
check(r.ok and r.json()["rotation"]["who"] == [1, BOB], "v1: set a rotation")
r = V.post(f"/tasks/{MEAL}/to-shopping", json={"items": ["Oregano"]})
check(r.ok and r.json()["added"][0]["title"] == "Oregano", "v1: ingredients to shopping")
check(V.post(f"/lists/{L2}/shop-areas").ok, "v1: shop areas")
check(V.get("/family/packing").json()["templates"] and V.post("/family/packing", json={"template": "daycare"}).status_code == 201, "v1: packing")
check(V.get("/family/kids").json()["data"] and V.post(f"/family/kids/{LINA}/stars", json={"delta": 1}).ok, "v1: kids + stars (admin)")
r = V.post(f"/family/kids/{LINA}/rewards", json={"title": "Book", "cost": 3})
RW = r.json()["id"]
check(r.status_code == 201 and V.patch(f"/family/rewards/{RW}", json={"cost": 4}).json()["cost"] == 4, "v1: rewards")
check(V.post(f"/family/rewards/{RW}/decide", json={"approve": True}).ok and V.delete(f"/family/rewards/{RW}").status_code == 204, "v1: decide + delete")
check(V.post(f"/family/rewards/{RW}/request").status_code == 404, "v1: gone")
check(V.post("/me/purpose", json={"purpose": "family"}).status_code == 403, "v1: /me/purpose needs the scope account")
lst = next(x for x in V.get("/lists").json()["data"] if x["id"] == SHOP)
check(lst["family"] == "shopping", "v1 list: family")
r = V.post("/lists", json={"name": "V1 shop", "family": "shopping"})
check(r.status_code == 201 and r.json()["family"] == "shopping", "v1: create a shopping list")
check(V.patch(f"/lists/{r.json()['id']}", json={"family": None}).json()["family"] is None, "v1: family null = an ordinary list")
spec = requests.get(B + "/api/v1/openapi.json").json()
for p_, m_, sc in (("/family", "get", "read"), ("/family/occasions", "post", "tasks:write"), ("/family/deadlines", "post", "tasks:write"),
                   ("/tasks/{id}/to-shopping", "post", "tasks:write"), ("/lists/{id}/shop-areas", "post", "structure"),
                   ("/family/packing", "post", "structure"), ("/family/kids/{id}/rewards", "post", "tasks:write"),
                   ("/family/rewards/{id}", "delete", "delete"), ("/me/purpose", "post", "account")):
    check(spec["paths"].get(p_, {}).get(m_, {}).get("x-kalmido-scope") == sc, f"OpenAPI {m_.upper()} {p_}: scope {sc}")
tp_ = spec["components"]["schemas"]["Task"]["properties"]
check({"family", "rotation", "stars", "people"} <= set(tp_) and {"family", "rotation", "stars", "people"} <= set(spec["components"]["schemas"]["TaskInput"]["properties"]),
      "OpenAPI: the task fields")

# ================================================================== the module off: data and API stay
A.patch(B + "/api/settings", json={"features": "cal,collab"})
check(A.get(B + "/api/family").ok and A.post(B + "/api/family/occasions", json={"name": "Still", "date": "--05-05"}).status_code == 201,
      "module off: the API still works (the app hides it)")
# deleting a kid removes its stars + rewards
r = A.delete(B + f"/api/users/{MAX}")
check(r.ok and dbx("SELECT COUNT(*) FROM kid_stars WHERE kid_id=?", (MAX,))[0][0] == 0, "a deleted kid takes its stars along")

print(f"p2190_family_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
