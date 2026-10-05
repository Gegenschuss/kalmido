#!/usr/bin/env python3
"""2.22.0 API tests: "Home & life" (#663 / #662), own container (start.sh) with a fake Karakeep inside (fake_karakeep.py).
The seven modules are off by default and refuse while off (409); contracts (due = the last day to cancel, the next term of
a passed one, the renewal as the repeat, cost per month / year, notice in days / weeks / months, editing the fam fields),
devices + upkeep (warranty, presets, repeat), staying in touch (per person, only visible contacts, "today", the daily push
once), health (a private list: never an agent's, refused as an agent member, hidden from tokens without the scope
"private", no webhooks, no agent events, medication = a daily task per time), the review (day / week: done, open, moved,
next) + journal (private, mood, empty = deleted, the scope), trips (sections, packing, the all-day event, PATCH trip),
Karakeep (sealed key never shown, two pages, a source list, archive back, errors, SSRF guard), the REST API v1 + OpenAPI,
the data export, #681 today_inbox setting."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date, timedelta

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


def ntfy():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8")]
    except OSError:
        return []


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_SMTP_HOST=127.0.0.1"
           " -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "fake_karakeep.py"), DATA)
json.dump([], open(os.path.join(DATA, "kk.json"), "w"))
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_karakeep.py"])
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "cal,comments,collab"})
T0 = date.today()
D = lambda n: (T0 + timedelta(days=n)).isoformat()  # noqa: E731
LIFE = "contracts,home,care,health,review,travel,reading"

# ================================================================== off by default: every module refuses
st = A.get(B + "/api/state").json()
check(not any(m in st["settings"]["features"].split(",") for m in LIFE.split(",")), "the seven modules are off by default")
j = A.get(B + "/api/life").json()
check(j["modules"] == [] and "contracts" not in j, "GET /api/life with everything off: no module, no data")
for path, body in (("contracts", {"name": "x", "ends": D(90)}), ("devices", {"name": "x"}), ("upkeep", {"title": "x", "every_months": 12}),
                   ("health", {"type": "appointment", "title": "x", "date": D(3)}), ("trips", {"name": "x", "from": D(10), "to": D(12)})):
    r = A.post(B + f"/api/life/{path}", json=body)
    check(r.status_code == 409 and "turned off" in r.json().get("error", ""), f"{path}: refused while off ({r.status_code})")
check(A.get(B + "/api/life/review").status_code == 409 and A.put(B + f"/api/life/journal/{D(0)}", json={"text": "x"}).status_code == 409,
      "review + journal refused while off")
A.patch(B + "/api/settings", json={"features": "cal,comments,collab,contacts,events," + LIFE})

# ================================================================== contracts (#662)
r = A.post(B + "/api/life/contracts", json={"name": "Mobile phone", "provider": "Telco", "cost": "19,99", "per": "month", "ends": D(100),
                                            "notice": 1, "notice_unit": "m", "renew_months": 12, "lead_days": 14, "account": "Joint account"})
check(r.status_code == 201, "a contract " + r.text[:200])
C1 = r.json()
from dateutil.relativedelta import relativedelta  # noqa: E402
check(C1["due"] == (date.fromisoformat(D(100)) - relativedelta(months=1)).isoformat() and C1["repeat"] == "FREQ=YEARLY" and C1["deadline"] == 2
      and C1["reminders"] == "20160,0" and C1["fam"]["kind"] == "contract" and C1["fam"]["cost"] == 19.99 and C1["title"] == "Cancel or renew the contract: Mobile phone",
      "due = end minus the notice, yearly renewal, a deadline with reminders 14 days before and on the day " + json.dumps(C1)[:300])
lists = {l["life"]: l for l in A.get(B + "/api/state").json()["lists"] if l.get("life")}
check("contracts" in lists and lists["contracts"]["name"] == "Contracts" and C1["list_id"] == lists["contracts"]["id"], "a Contracts list was created")
r = A.post(B + "/api/life/contracts", json={"name": "Gym", "cost": 120, "per": "year", "ends": D(-20), "notice": 4, "notice_unit": "w", "renew_months": 1})
C2 = r.json()
check(r.status_code == 201 and C2["due"] >= D(0) and C2["repeat"] == "FREQ=MONTHLY", "a passed term: the next one (monthly renewal) " + str(C2.get("due")))
r = A.post(B + "/api/life/contracts", json={"name": "Old insurance", "ends": D(-5), "notice": 0, "renew_months": 0, "cost": 30, "per": "quarter"})
check(r.status_code == 201 and r.json()["due"] == D(-5) and r.json()["repeat"] == "", "no renewal: due on the end, no repeat (overdue)")
C3 = r.json()
for bad, what in (({"name": "x"}, "no end"), ({"ends": D(5)}, "no name"), ({"name": "x", "ends": D(5), "cost": "abc"}, "cost text"),
                  ({"name": "x", "ends": D(5), "per": "week"}, "period"), ({"name": "x", "ends": D(5), "notice_unit": "y"}, "notice unit"),
                  ({"name": "x", "ends": D(5), "renew_months": 500}, "renewal too long"), ({"name": "x", "ends": D(5), "cost": -1}, "negative cost")):
    check(A.post(B + "/api/life/contracts", json=bad).status_code == 400, "contract validation: " + what)
j = A.get(B + "/api/life").json()
cs = {x["name"]: x for x in j["contracts"]["items"]}
check(cs["Mobile phone"]["monthly"] == 19.99 and cs["Gym"]["monthly"] == 10.0 and cs["Old insurance"]["monthly"] == 10.0
      and j["contracts"]["monthly"] == round(19.99 + 10 + 10, 2) and j["contracts"]["yearly"] == round(19.99 * 12 + 120 + 120, 2),
      "the overview: cost per month (a year / 12, a quarter / 3) and the sums " + json.dumps(j["contracts"])[:300])
check(cs["Mobile phone"]["ends"] == D(100) and cs["Mobile phone"]["renew_months"] == 12 and cs["Mobile phone"]["account"] == "Joint account",
      "… the end of the term, the renewal, paid from")
check([x["name"] for x in j["contracts"]["items"]][0] == "Old insurance", "… sorted by the last day to cancel (the overdue first)")
# editing the fam fields through the task (as the app does)
r = A.patch(B + f"/api/tasks/{C1['id']}", json={"fam": {**C1["fam"], "cost": 24.5}})
check(r.ok and A.get(B + f"/api/tasks/{C1['id']}").json()["fam"]["cost"] == 24.5, "PATCH fam: the cost changes")
check(A.patch(B + f"/api/tasks/{C1['id']}", json={"fam": {**C1["fam"], "evil": 1}}).status_code == 400, "PATCH fam: an unknown field is refused")
check(A.patch(B + f"/api/tasks/{C1['id']}", json={"fam": {"kind": "bookmark", "src": "x", "bid": "1"}}).status_code == 400, "PATCH fam: a bookmark needs src karakeep")
# completing = extended: the next term
A.post(B + f"/api/tasks/{C1['id']}/complete")
nxt = [t for t in A.get(B + "/api/state").json()["tasks"] if t.get("fam", {}).get("name") == "Mobile phone" and t["status"] == 0]
check(len(nxt) == 1 and nxt[0]["due"] == (date.fromisoformat(C1["due"]) + relativedelta(years=1)).isoformat(), "ticked off = renewed: due a year later")
j = A.get(B + "/api/life").json()
check({x["name"]: x for x in j["contracts"]["items"]}["Mobile phone"]["ends"] == (date.fromisoformat(D(100)) + relativedelta(years=1)).isoformat(),
      "… and the end of the term moves along")

# ================================================================== home: devices + upkeep
r = A.post(B + "/api/life/devices", json={"name": "Washing machine", "model": "W 123", "bought": D(-30), "warranty": D(700)})
check(r.status_code == 201 and r.json()["due"] == D(700) and r.json()["title"] == "Warranty ends: Washing machine" and r.json()["reminders"] == "43200,0",
      "a device: due when the warranty ends, reminders 30 days before " + r.text[:200])
r2 = A.post(B + "/api/life/devices", json={"name": "Old lamp"})
check(r2.status_code == 201 and r2.json()["due"] is None and r2.json()["title"] == "Old lamp", "a device without a warranty: a plain entry")
check(A.post(B + "/api/life/devices", json={"name": "x", "bought": D(0), "warranty": D(-1)}).status_code == 400, "the warranty before the purchase: 400")
pre = A.get(B + "/api/life/upkeep-presets").json()["presets"]
check(len(pre) >= 6 and pre[0]["title"] and pre[0]["every_months"] in (3, 6, 12), "upkeep presets")
r = A.post(B + "/api/life/upkeep", json={"title": "Service the heating", "every_months": 12, "next": D(20)})
check(r.status_code == 201 and r.json()["repeat"] == "FREQ=YEARLY" and r.json()["due"] == D(20), "upkeep: a yearly task")
r = A.post(B + "/api/life/upkeep", json={"title": "Descale", "every_months": 3})
check(r.status_code == 201 and r.json()["repeat"] == "FREQ=MONTHLY;INTERVAL=3" and r.json()["due"] == D(0), "upkeep every 3 months from today")
check(A.post(B + "/api/life/upkeep", json={"title": "x", "every_months": 0}).status_code == 400, "upkeep: every 0 months is 400")
h = A.get(B + "/api/life").json()["home"]
check([d["name"] for d in h["devices"]] == ["Washing machine", "Old lamp"] and h["devices"][0]["days"] == 700 and len(h["upkeep"]) == 2
      and h["upkeep"][0]["title"] == "Descale" and h["upkeep"][1]["every_months"] == 12, "the overview: devices + upkeep " + json.dumps(h)[:300])

# ================================================================== staying in touch (needs contacts)
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "contacts,care"})
c1 = A.post(B + "/api/contacts", json={"fn": "Erika Mustermann"}).json()
c2 = A.post(B + "/api/contacts", json={"fn": "Max Muster"}).json()
c3 = Bo.post(B + "/api/contacts", json={"fn": "Bob's friend"}).json()
r = A.put(B + f"/api/contacts/{c1['id']}/care", json={"every_days": 30, "last": D(-40), "note": "Talked about the garden"})
check(r.ok and r.json() == {"every_days": 30, "last": D(-40), "note": "Talked about the garden", "due": D(-10)}, "care: every 30 days, last 40 days ago " + r.text)
check(A.put(B + f"/api/contacts/{c2['id']}/care", json={"every_days": 14}).json()["due"] == D(0), "never in touch: due today")
check(A.put(B + f"/api/contacts/{c3['id']}/care", json={"every_days": 7}).status_code == 404, "someone else's contact: 404")
check(A.put(B + f"/api/contacts/{c1['id']}/care", json={"last": D(3)}).status_code == 400, "the last contact in the future: 400")
check(A.put(B + f"/api/contacts/{c1['id']}/care", json={"every_days": -1}).status_code == 400, "negative interval: 400")
car = A.get(B + "/api/life").json()["care"]
check(car["contacts"] and [x["fn"] for x in car["items"]] == ["Erika Mustermann", "Max Muster"] and car["items"][0]["days"] == -10,
      "the overview: the most overdue first " + json.dumps(car)[:300])
check(A.get(B + f"/api/contacts/{c1['id']}").json()["care"]["every_days"] == 30, "the contact card carries my care setting")
check(Bo.get(B + "/api/life").json()["care"]["items"] == [], "per person: Bob sees none of Alice's")
r = A.put(B + f"/api/contacts/{c1['id']}/care", json={"last": "today"})
check(r.json()["last"] == D(0) and r.json()["due"] == D(30), '"today" = in touch today')
# the daily push (from the all-day reminder time on), once
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
A.patch(B + "/api/settings", json={"allday_time": "00:00", "push_channel": "ntfy"})
p = until(lambda: [x for x in ntfy() if x.get("title") == "Time to get in touch"], 25)
check(p and "Max Muster" in p[0].get("msg", "") and "Erika" not in p[0].get("msg", "") and p[0]["click"].endswith("#life"), "the daily push lists who is due " + json.dumps(p[:1])[:200])
time.sleep(3)
check(len([x for x in ntfy() if x.get("title") == "Time to get in touch"]) == 1, "… once a day")

# ================================================================== health (private)
r = A.post(B + "/api/life/health", json={"type": "appointment", "title": "Dentist", "who": "Lina", "date": D(2), "time": "09:30"})
check(r.status_code == 201 and r.json()["tasks"][0]["due"] == D(2) and r.json()["tasks"][0]["due_time"] == "09:30"
      and r.json()["tasks"][0]["reminders"] == "1440,60,0" and r.json()["tasks"][0]["fam"] == {"kind": "health", "type": "appointment", "who": "Lina", "lead": 1},
      "an appointment: reminders a day + an hour before " + r.text[:300])
HL = r.json()["tasks"][0]["list_id"]
check(A.get(B + "/api/state").json()["lists"][[l["id"] for l in A.get(B + "/api/state").json()["lists"]].index(HL)]["life"] == "health", "a private Health list")
r = A.post(B + "/api/life/health", json={"type": "medication", "title": "Vitamin D", "times": ["20:00", "08:00", "08:00"]})
check(r.status_code == 201 and [t["due_time"] for t in r.json()["tasks"]] == ["08:00", "20:00"] and all(t["repeat"] == "FREQ=DAILY" for t in r.json()["tasks"]),
      "medication: a daily task per time (doubles once)")
r = A.post(B + "/api/life/health", json={"type": "vaccination", "title": "Tetanus", "date": D(400), "every_months": 120})
check(r.status_code == 201 and r.json()["tasks"][0]["repeat"] == "FREQ=YEARLY;INTERVAL=10", "a vaccination every 10 years")
check(A.post(B + "/api/life/health", json={"type": "medication", "title": "x", "times": ["25:00"]}).status_code == 400, "medication: a bad time is 400")
check(A.post(B + "/api/life/health", json={"type": "appointment", "title": "x"}).status_code == 400, "an appointment needs a date")
check(A.post(B + "/api/life/health", json={"type": "appointment", "title": "x", "date": D(1), "list_id": lists["contracts"]["id"]}).status_code == 400,
      "health entries only in a health list")
# an agent never sees it
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
AG, AGT = r.json()["id"], r.json()["token"]
AGH = {"Authorization": "Bearer " + AGT}
r = A.put(B + f"/api/lists/{HL}/members", json={"user_id": AG, "role": "edit"})
check(r.status_code == 409 and "agent" in r.json()["error"], "sharing a health list with an agent: 409")
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,?,?)", (HL, AG, "edit", "edit", 99, "2026-01-01T00:00:00Z"))
V = B + "/api/v1"
check(HL not in [l["id"] for l in requests.get(V + "/lists", headers=AGH).json()["data"]], "an agent (even as a member): the health list is not in GET /lists")
hid = A.get(B + "/api/life").json()["health"]["items"][0]["task_id"]
check(requests.get(V + f"/tasks/{hid}", headers=AGH).status_code == 404, "… nor its tasks (404)")
check(requests.get(V + "/search", headers=AGH, params={"q": "Dentist"}).json()["data"] == [], "… nor in the search")
ev0 = dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=?", (AG,))[0][0]
A.patch(B + f"/api/tasks/{hid}", json={"title": "Dentist (moved)"})
A.post(B + f"/api/tasks/{hid}/comments", json={"body": "@Claude look"})
time.sleep(0.5)
check(dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=?", (AG,))[0][0] == ev0, "no agent event from a health list (change, mention)")
dbx("DELETE FROM list_members WHERE list_id=? AND user_id=?", (HL, AG))
# tokens: only with the scope private
def tok(scopes):
    r = A.post(B + "/api/me/tokens", json={"name": "t" + str(time.time()), "scopes": scopes})
    return {"Authorization": "Bearer " + r.json()["token"]}


rw, pv, legacy = tok(["read", "tasks:write"]), tok(["read", "tasks:write", "private"]), tok(["read", "write"])
check(HL not in [l["id"] for l in requests.get(V + "/lists", headers=rw).json()["data"]]
      and HL not in [l["id"] for l in requests.get(V + "/lists", headers=legacy).json()["data"]], "a token without private (also an old write token): no health list")
check(requests.get(V + f"/tasks/{hid}", headers=rw).status_code == 404 and requests.get(V + f"/lists/{HL}", headers=rw).status_code == 404, "… no health task / list")
check("health" not in requests.get(V + "/life", headers=rw).json(), "GET /life without private: no health part")
check(HL in [l["id"] for l in requests.get(V + "/lists", headers=pv).json()["data"]] and requests.get(V + f"/tasks/{hid}", headers=pv).ok
      and requests.get(V + "/life", headers=pv).json()["health"]["items"], "with the scope private: visible")
check(requests.post(V + "/life/health", headers=rw, json={"type": "appointment", "title": "x", "date": D(1)}).status_code == 403
      and requests.post(V + "/life/health", headers=pv, json={"type": "appointment", "title": "GP", "date": D(1)}).status_code == 201,
      "POST /life/health needs private")
check(requests.post(V + "/tasks", headers=rw, json={"title": "sneak in", "list_id": HL}).status_code in (403, 404), "a task into the health list without private: refused")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "private"], "username": "robo", "display_name": "Robo"})
check(r.status_code == 400 and "Health" in r.json()["error"], "an agent never gets the scope private (400)")
# webhooks: nothing of a health list
wh = A.post(B + "/api/me/webhooks", json={"name": "h", "url": "http://127.0.0.1:9/hook", "events": ["task.created", "task.updated"]})
if wh.ok:
    n0 = dbx("SELECT COUNT(*) FROM webhook_deliveries")[0][0] if dbx("SELECT name FROM sqlite_master WHERE name='webhook_deliveries'") else 0
    A.patch(B + f"/api/tasks/{hid}", json={"title": "Dentist again"})
    time.sleep(0.4)
    n1 = dbx("SELECT COUNT(*) FROM webhook_deliveries")[0][0] if dbx("SELECT name FROM sqlite_master WHERE name='webhook_deliveries'") else 0
    check(n1 == n0, "no webhook for a change in a health list")
# the person's own app sees everything, the members they share it with too
A.put(B + f"/api/lists/{HL}/members", json={"user_id": BOB, "role": "view"})
check(HL in [l["id"] for l in Bo.get(B + "/api/state").json()["lists"]], "a person the list is shared with sees it in the app")

# ================================================================== review + journal
t1 = A.post(B + "/api/tasks", json={"title": "Done today"}).json()
A.post(B + f"/api/tasks/{t1['id']}/complete")
A.post(B + "/api/tasks", json={"title": "Overdue thing", "due": D(-3)})
A.post(B + "/api/tasks", json={"title": "Next week thing", "due": D(8)})
mv = A.post(B + "/api/tasks", json={"title": "Moved one", "due": D(0)}).json()
A.patch(B + f"/api/tasks/{mv['id']}", json={"due": D(2)})
r = A.get(B + "/api/life/review", params={"period": "day"}).json()
check(any(x["title"] == "Done today" for x in r["done"]) and any(x["title"] == "Overdue thing" and x["overdue"] for x in r["open"])
      and any(x["title"] == "Moved one" for x in r["moved"]) and r["from"] == r["to"] == D(0), "the day: done, still open, moved " + json.dumps(r)[:300])
w = A.get(B + "/api/life/review", params={"period": "week"}).json()
mon = T0 - timedelta(days=T0.weekday())
check(w["from"] == mon.isoformat() and w["to"] == (mon + timedelta(days=6)).isoformat() and any(x["title"] == "Done today" for x in w["done"]),
      "the week: Monday to Sunday, today's completion in it")
check(A.get(B + "/api/life/review", params={"period": "month"}).status_code == 400 and A.get(B + "/api/life/review", params={"date": "x"}).status_code == 400,
      "review: bad period / date 400")
r = A.put(B + f"/api/life/journal/{D(0)}", json={"text": "  A good day.  ", "mood": 4})
check(r.ok and r.json() == {"day": D(0), "text": "A good day.", "mood": 4}, "journal: write")
check(A.get(B + "/api/life/review").json()["journal"] == [{"day": D(0), "text": "A good day.", "mood": 4}], "the review carries the journal of the range")
check(A.put(B + f"/api/life/journal/{D(5)}", json={"text": "x"}).status_code == 400 and A.put(B + f"/api/life/journal/{D(0)}", json={"mood": 9}).status_code == 400,
      "journal: no far future, mood 1..5")
check(Bo.get(B + "/api/life/review").status_code == 409, "Bob without the review module: 409")
Bo.patch(B + "/api/settings", json={"features": "contacts,care,review"})
check(Bo.get(B + "/api/life/review").json()["journal"] == [], "per person: Bob does not see Alice's journal")
check("journal" not in requests.get(V + "/life/review", headers=rw).json() and requests.get(V + "/life/review", headers=pv).json()["journal"],
      "API: the journal only with the scope private")
check(requests.put(V + f"/life/journal/{D(-1)}", headers=rw, json={"text": "x"}).status_code == 403
      and requests.put(V + f"/life/journal/{D(-1)}", headers=pv, json={"text": "Yesterday"}).ok, "PUT /life/journal needs private")
check(A.put(B + f"/api/life/journal/{D(0)}", json={"text": "", "mood": None}).json()["text"] == ""
      and not dbx("SELECT 1 FROM journal WHERE user_id=1 AND day=?", (D(0),)), "an empty entry is deleted")

# ================================================================== travel
r = A.post(B + "/api/life/trips", json={"name": "Summer in Italy", "where": "Rome", "from": D(30), "to": D(37), "packing": "holiday", "event": True})
check(r.status_code == 201 and r.json()["list_id"] and r.json()["event_id"], "a trip with the packing list and an all-day event " + r.text[:200])
TL = r.json()["list_id"]
st = A.get(B + "/api/state").json()
tl = next(l for l in st["lists"] if l["id"] == TL)
secs = [s["name"] for s in st["sections"] if s["list_id"] == TL]
check(tl["life"] == "travel" and tl["trip"] == {"from": D(30), "to": D(37), "where": "Rome"} and tl["checklist"] == 1, "the trip list: life travel, dates, done at the bottom")
check(secs == [] and len([t for t in st["tasks"] if t["list_id"] == TL]) > 10, "#747: no preset sections: the things to do + the packing list " + str(secs))
todo = [t for t in st["tasks"] if t["list_id"] == TL and t["due"]]
check(any(t["title"] == "Check passports and ID cards" and t["due"] == D(0) for t in todo) and any(t["title"] == "Pack" and t["due"] == D(29) for t in todo),
      "things to do before: dated from the start (never in the past)")
ev = A.get(B + f"/api/events/{r.json()['event_id']}").json()
check(ev["title"] == "Summer in Italy" and ev["all_day"] and ev["start"] == D(30) and ev["end"] == D(38) and ev["location"] == "Rome", "the all-day event")
r = A.patch(B + f"/api/lists/{TL}", json={"trip": {"from": D(31), "to": D(38), "where": "Florence"}})
check(r.ok and next(l for l in A.get(B + "/api/state").json()["lists"] if l["id"] == TL)["trip"]["where"] == "Florence", "PATCH trip")
check(A.patch(B + f"/api/lists/{TL}", json={"trip": {"from": D(5), "to": D(1)}}).status_code == 400, "a trip ending before it starts: 400")
check(A.post(B + "/api/life/trips", json={"name": "x", "from": D(1), "to": D(2), "packing": "moon"}).status_code == 400, "an unknown packing template: 400")
r = A.post(B + "/api/life/trips", json={"name": "Weekend", "from": D(-10), "to": D(-8), "packing": ""})
tv = A.get(B + "/api/life").json()["travel"]["trips"]
check([x["name"] for x in tv] == ["Summer in Italy", "Weekend"] and tv[0]["state"] == "upcoming" and tv[1]["state"] == "past", "the overview: upcoming first, past last")

# ================================================================== Karakeep (read later)
check(A.get(B + "/api/life/karakeep").json() == {"connected": False}, "Karakeep: not connected")
check(A.post(B + "/api/life/karakeep/sync").status_code == 400, "sync without a connection: 400")
r = A.put(B + "/api/life/karakeep", json={"url": "http://10.1.2.3:8097", "token": "kk-secret"})
check(r.ok and r.json()["token_set"] and "token" not in r.json(), "connected (the key is write-only)")
r = A.post(B + "/api/life/karakeep/sync")
check(r.status_code == 400 and A.get(B + "/api/life/karakeep").json()["error"], "an internal address not allowed by the admin: refused, the error stored " + r.text[:200])
json.dump([{"id": "bm_1", "title": "A long read", "content": {"type": "link", "url": "https://example.org/long"}},
           {"id": "bm_2", "title": None, "content": {"type": "link", "url": "https://example.org/b", "title": "From the page"}},
           {"id": "bm_3", "title": "A note", "content": {"type": "text", "text": "remember this"}},
           {"id": "bm_4", "title": "Archived", "archived": True, "content": {"type": "link", "url": "https://example.org/x"}},
           {"id": "bm_5", "title": "In the list", "lists": ["lst_1"], "content": {"type": "link", "url": "https://example.org/l"}}],
          open(os.path.join(DATA, "kk.json"), "w"))
A.put(B + "/api/life/karakeep", json={"url": "http://127.0.0.1:8097/api/v1"})
r = A.post(B + "/api/life/karakeep/sync")
check(r.ok and r.json()["added"] == 4, "sync: 4 bookmarks over two pages (not the archived one) " + r.text[:200])
RL = r.json()["list_id"]
rt = {t["title"]: t for t in A.get(B + "/api/state").json()["tasks"] if t["list_id"] == RL}
check(rt["A long read"]["url"] == "https://example.org/long" and "From the page" in rt and rt["A note"]["url"] is None
      and rt["A long read"]["fam"] == {"kind": "bookmark", "src": "karakeep", "bid": "bm_1"}, "titles, links, a note without a link")
check(A.post(B + "/api/life/karakeep/sync").json()["added"] == 0, "a second sync adds nothing")
A.delete(B + f"/api/tasks/{rt['A note']['id']}")
check(A.post(B + "/api/life/karakeep/sync").json()["added"] == 0, "a deleted bookmark task does not come back")
A.post(B + f"/api/tasks/{rt['A long read']['id']}/complete")
r = A.post(B + "/api/life/karakeep/sync").json()
check(r["archived"] == 1 and next(m for m in json.load(open(os.path.join(DATA, "kk.json"))) if m["id"] == "bm_1")["archived"], "ticked = archived in Karakeep")
check(A.post(B + "/api/life/karakeep/sync").json()["archived"] == 0, "… once")
log = [json.loads(x) for x in open(os.path.join(DATA, "kk.log"))]
check(all(x["auth"] for x in log) and any("cursor=2" in x["p"] for x in log), "every request with the key, the second page followed")
check(len(A.get(B + "/api/life/karakeep/lists").json()["lists"]) == 1, "the Karakeep lists (a bad id dropped)")
A.put(B + "/api/life/karakeep", json={"source": "lst_1"})
json.dump(json.load(open(os.path.join(DATA, "kk.json"))) + [{"id": "bm_6", "title": "Not in the list", "content": {"type": "link", "url": "https://e.org/6"}}],
          open(os.path.join(DATA, "kk.json"), "w"))
check(A.post(B + "/api/life/karakeep/sync").json()["added"] == 0, "a source list: only its bookmarks")
A.put(B + "/api/life/karakeep", json={"token": "wrong"})
r = A.post(B + "/api/life/karakeep/sync")
check(r.status_code == 400 and "refused the API key" in r.json()["error"], "a wrong key: a clear error")
st = A.get(B + "/api/life/karakeep").json()
check(st["error"] == "auth" and "token" not in json.dumps(st).replace("token_set", ""), "the error is stored, the key never shown")
raw = dbx("SELECT token FROM kk_conns WHERE user_id=1")[0][0]
check(raw.startswith("v1.") and "wrong" not in raw, "the key is sealed at rest")
check(A.put(B + "/api/life/karakeep", json={"url": "ftp://x"}).status_code == 400 and A.put(B + "/api/life/karakeep", json={"evil": 1}).status_code == 400,
      "Karakeep: bad URL / unknown field 400")
check(requests.put(V + "/life/karakeep", headers=pv, json={"token": "x"}).status_code in (403, 404, 405), "the connection itself is not in the API")
r = requests.post(V + "/life/karakeep/sync", headers=pv)
check(r.status_code == 400, "API sync: the stored error")
check(A.delete(B + "/api/life/karakeep").ok and A.get(B + "/api/life/karakeep").json() == {"connected": False} and RL in [l["id"] for l in A.get(B + "/api/state").json()["lists"]],
      "disconnect: the key goes, the list stays")
check(requests.put(V + "/life/karakeep", headers=AGH, json={}).status_code in (403, 404, 405), "an agent has no connection route")

# ================================================================== the REST API v1 + OpenAPI
r = requests.post(V + "/life/contracts", headers=rw, json={"name": "Streaming", "ends": D(60), "cost": 9.99})
check(r.status_code == 201 and r.json()["family"]["kind"] == "contract", "API: POST /life/contracts")
check(requests.post(V + "/life/contracts", headers=rw, json={"name": "x", "ends": D(60), "nope": 1}).status_code == 400, "API: unknown field 400")
check(requests.post(V + "/life/devices", headers=rw, json={"name": "Phone", "warranty": D(300)}).status_code == 201, "API: POST /life/devices")
check(requests.post(V + "/life/upkeep", headers=rw, json={"title": "Smoke detectors", "every_months": 12}).status_code == 201, "API: POST /life/upkeep")
check(requests.post(V + "/life/trips", headers=rw, json={"name": "x", "from": D(1), "to": D(2)}).status_code == 403
      and requests.post(V + "/life/trips", headers=tok(["read", "structure"]), json={"name": "Trip API", "from": D(1), "to": D(2)}).status_code == 201,
      "API: trips need the scope structure")
check(requests.put(V + f"/contacts/{c2['id']}/care", headers=rw, json={"last": "today"}).status_code == 403
      and requests.put(V + f"/contacts/{c2['id']}/care", headers=tok(["read", "contacts"]), json={"last": "today"}).ok, "API: care needs the scope contacts")
spec = requests.get(V + "/openapi.json", headers=rw).json()
sc = {(p, m): o["x-kalmido-scope"] for p, ms_ in spec["paths"].items() for m, o in ms_.items()}
check(sc[("/life/health", "post")] == "private" and sc[("/life/journal/{day}", "put")] == "private" and sc[("/life", "get")] == "read"
      and sc[("/contacts/{id}/care", "put")] == "contacts" and sc[("/life/contracts", "post")] == "tasks:write", "OpenAPI: the scopes")
lst = requests.get(V + "/lists", headers=pv).json()["data"]
check(any(l.get("life") == "travel" and l.get("trip") for l in lst) and all("life" in l for l in lst), "API lists: life + trip")

# ================================================================== the data export, settings
ex = A.get(B + "/api/export.json").json()
check(any(x["text"] == "Yesterday" for x in ex["journal"]) and ex["contact_care"] and "token" not in json.dumps(ex.get("karakeep", [])), "the export: journal, care, no Karakeep key")
check(A.patch(B + "/api/settings", json={"today_inbox": "1"}).ok and A.get(B + "/api/state").json()["settings"]["today_inbox"] == "1", "#681: the setting today_inbox")
check(A.patch(B + "/api/settings", json={"care_sent": "2020-01-01"}).ok and A.get(B + "/api/state").json()["settings"]["care_sent"] != "2020-01-01", "care_sent is server-only")
# switching a module off keeps the data
A.patch(B + "/api/settings", json={"features": "cal,comments,collab,contacts"})
j = A.get(B + "/api/life").json()
check(j["modules"] == [] and A.post(B + "/api/life/devices", json={"name": "x"}).status_code == 409
      and any(t.get("fam", {}).get("kind") == "device" for t in A.get(B + "/api/state").json()["tasks"]), "off again: refused, the tasks stay")

# ================================================================== #693: "<name> is writing …" in comments
SL = A.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
A.put(B + f"/api/lists/{SL}/members", json={"user_id": BOB, "role": "edit"})
ST = A.post(B + "/api/tasks", json={"title": "Discuss", "list_id": SL}).json()["id"]
r = Bo.post(B + f"/api/tasks/{ST}/typing")
check(r.ok and r.json()["seconds"] == 8, "#693: Bob writes a comment")
ty = A.get(B + "/api/version").json()["ty"]
check({"task_id": ST, "user_id": BOB, "name": "Bob"} in ty, "#693: Alice sees it in /api/version " + json.dumps(ty))
check(Bo.get(B + "/api/version").json()["ty"] == [], "#693: never one's own signal")
EVE = A.post(B + "/api/users", json={"username": "eve", "display_name": "Eve", "password": "password123"}).json()["id"]
Ev = sess("eve")
check(Ev.post(B + f"/api/tasks/{ST}/typing").status_code == 404 and Ev.get(B + "/api/version").json()["ty"] == [], "#693: a stranger: 404, sees nothing")
A.put(B + f"/api/lists/{SL}/members", json={"user_id": AG, "role": "edit"})
check(requests.post(V + f"/tasks/{ST}/typing", headers=AGH).ok and any(x["user_id"] == AG for x in A.get(B + "/api/version").json()["ty"]),
      "#693: an agent's signal over the API")
check(requests.post(V + f"/tasks/{ST}/typing", headers=tok(["read"])).status_code == 403, "#693: the API needs the scope comments")
time.sleep(8.5)
check(A.get(B + "/api/version").json()["ty"] == [], "#693: gone after 8 s")

# ================================================================== #697: invitations / reset links
import email as _em  # noqa: E402
def mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8")]
    except OSError:
        return []


r = A.post(B + "/api/users", json={"username": "patrick", "display_name": "Patrick", "email": "patrick@example.org", "invite": True, "lang": "de"})
check(r.ok and r.json()["invitation"]["sent"] and r.json()["invite"] == "invited" and not r.json()["has_password"], "#697: a new person invited by e-mail " + r.text[:300])
link = r.json()["invitation"]["link"]
tok = link.split("#invite/")[1]
check(link.startswith("https://kalmido.example/#invite/") and len(tok) >= 40, "#697: the link (a fragment: never in a server log)")
m = until(lambda: [x for x in mails() if "patrick@example.org" in x["to"]])
msg = _em.message_from_string(m[0]["raw"]) if m else None
parts = {p.get_content_type(): p for p in msg.walk()} if msg else {}
htm = parts["text/html"].get_payload(decode=True).decode() if "text/html" in parts else ""
check(m and "Willkommen bei Kalmido, Patrick" in str(_em.header.make_header(_em.header.decode_header(msg["Subject"]))) and "image/png" in parts
      and "cid:logo" in htm and tok in htm and "Konto einrichten" in htm and "text/plain" in parts, "#697: the mail: German, HTML + text, the logo inline, the button with the link")
check(not dbx("SELECT 1 FROM user_invites WHERE token_hash=?", (tok,)) and len(dbx("SELECT token_hash FROM user_invites")[0][0]) == 64, "#697: only the hash is stored")
P0 = requests.Session(); P0.headers.update(H)
r = P0.post(B + "/api/auth/invite/check", json={"token": tok})
check(r.ok and r.json()["username"] == "patrick" and r.json()["kind"] == "invite" and r.json()["lang"] == "de", "#697: the page knows whom it is for (open)")
check(P0.post(B + "/api/auth/invite/check", json={"token": tok[:-2] + "xx"}).status_code == 404, "#697: a wrong token: 404")
check(P0.post(B + "/api/auth/invite/accept", json={"token": tok, "password": "short"}).status_code == 400, "#697: a short password: 400")
r = P0.post(B + "/api/auth/invite/accept", json={"token": tok, "password": "patrick-secret-1"})
check(r.ok and r.json()["ok"] and P0.get(B + "/api/me").json()["username"] == "patrick", "#697: the password set, signed in")
check(P0.post(B + "/api/auth/invite/accept", json={"token": tok, "password": "another-pass-1"}).status_code == 404, "#697: the link is used up")
check(requests.Session().post(B + "/api/auth/login", headers=H, json={"username": "patrick", "password": "patrick-secret-1"}).ok, "#697: login with the own password")
check(next(u for u in A.get(B + "/api/users").json()["users"] if u["username"] == "patrick")["invite"] is None, "#697: the status is active")
check("agents" in P0.get(B + "/api/state").json()["settings"]["features"].split(","), "#739: a new person starts with the module Agents")
# a reset link for someone with a password: ends the sessions
r = A.post(B + f"/api/users/{BOB}/invite", json={"send": False})
check(r.ok and r.json()["kind"] == "reset" and not r.json()["sent"] and "#invite/" in r.json()["link"], "#697: a reset link to copy")
t2 = r.json()["link"].split("#invite/")[1]
r = requests.post(B + "/api/auth/invite/accept", headers=H, json={"token": t2, "password": "bob-new-pass-1"})
check(r.ok and Bo.get(B + "/api/me").status_code == 401, "#697: reset: new password, the old sessions end")
Bo = sess.__call__(None); Bo.post(B + "/api/auth/login", json={"username": "bob", "password": "bob-new-pass-1"})
check(Bo.get(B + "/api/me").ok, "#697: Bob logs in with the new password")
check(Bo.post(B + f"/api/users/1/invite", json={}).status_code == 403, "#697: only admins create links")
# expiry + the rate limit
r = A.post(B + "/api/users", json={"username": "philipp", "display_name": "Philipp", "invite": True})
t3 = r.json()["invitation"]["link"].split("#invite/")[1]
dbx("UPDATE user_invites SET expires_at='2020-01-01T00:00:00Z' WHERE user_id=?", (r.json()["id"],))
check(requests.post(B + "/api/auth/invite/check", headers=H, json={"token": t3}).status_code == 404
      and next(u for u in A.get(B + "/api/users").json()["users"] if u["username"] == "philipp")["invite"] == "expired", "#697: expired")
codes = [requests.post(B + "/api/auth/invite/check", headers=H, json={"token": "x" * 40}).status_code for _ in range(25)]
check(429 in codes, "#697: the page is rate limited " + str(codes[-3:]))
r = A.post(B + "/api/users", json={"username": "kidz", "display_name": "Kidz", "password": "password123", "kid": True, "parents": [1]})
check(r.ok and "agents" not in sess("kidz").get(B + "/api/state").json()["settings"]["features"].split(","), "#739: a child account without Agents")

# ================================================================== #740: shared lists in the same folder, "Share folder"
FL = A.post(B + "/api/lists", json={"name": "Taxes", "folder": "Private/Money"}).json()["id"]
A.put(B + f"/api/lists/{FL}/members", json={"user_id": BOB, "role": "edit"})
bl = next(l for l in Bo.get(B + "/api/state").json()["lists"] if l["id"] == FL)
fo = json.loads(Bo.get(B + "/api/state").json()["settings"]["folders"])
check(bl["folder"] == "Private/Money" and "Private" in fo and "Private/Money" in fo, "#740: the list lands with Bob in the same folder (created) " + str(fo))
Bo.patch(B + f"/api/lists/{FL}", json={"folder": "Mine"})
A.patch(B + f"/api/lists/{FL}", json={"folder": "Other"})
check(next(l for l in Bo.get(B + "/api/state").json()["lists"] if l["id"] == FL)["folder"] == "Mine", "#740: Bob's own placement stays")
L2 = A.post(B + "/api/lists", json={"name": "Garden", "folder": "Home"}).json()["id"]
r = A.put(B + "/api/folders/people", json={"folder": "Home", "user_id": BOB, "role": "view"})
check(r.ok and r.json()["shared"] == 1 and next(l for l in Bo.get(B + "/api/state").json()["lists"] if l["id"] == L2)["role"] == "view", "#740: share a folder: its lists")
L3 = A.post(B + "/api/lists", json={"name": "Kitchen", "folder": "Home"}).json()["id"]
L4 = A.post(B + "/api/lists", json={"name": "Moved in"}).json()["id"]
A.patch(B + f"/api/lists/{L4}", json={"folder": "Home"})
bl = {l["id"]: l for l in Bo.get(B + "/api/state").json()["lists"]}
check(L3 in bl and L4 in bl and bl[L3]["folder"] == "Home", "#740: new and moved-in lists are shared too, in the folder")
check(A.get(B + "/api/folders/people", params={"folder": "Home"}).json()["people"] == [{"user_id": BOB, "role": "view"}], "#740: who the folder is shared with")
A.post(B + "/api/folders/rename", json={"old": "Home", "new": "House"})
check(A.get(B + "/api/folders/people", params={"folder": "House"}).json()["people"], "#740: a renamed folder keeps its sharing")
A.delete(B + "/api/folders/people", json={"folder": "House", "user_id": BOB})
L5 = A.post(B + "/api/lists", json={"name": "Later", "folder": "House"}).json()["id"]
check(L5 not in {l["id"] for l in Bo.get(B + "/api/state").json()["lists"]} and L3 in {l["id"] for l in Bo.get(B + "/api/state").json()["lists"]},
      "#740: stopped: new lists no longer, the shared ones stay")
# older shares: sorted in once at the update (migration); a list the person already put into a folder stays there
dbx("UPDATE list_members SET folder='' WHERE list_id=? AND user_id=?", (L3, BOB))
dbx("DELETE FROM settings WHERE key='migr_folders2220'")
subprocess.run(["docker", "restart", CT], capture_output=True)
def _up():
    try:
        return requests.get(B + "/api/health", timeout=3).ok
    except requests.RequestException:
        return False


check(until(_up, 60), "#740: restarted")
Bo = sess(None); Bo.post(B + "/api/auth/login", json={"username": "bob", "password": "bob-new-pass-1"})
bl = {l["id"]: l for l in Bo.get(B + "/api/state").json()["lists"]}
check(bl[L3]["folder"] == "House" and bl[FL]["folder"] == "Mine", "#740: the update sorts older shares in (own placements stay)")
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])

# ================================================================== #741: the purpose "Home"
r = Bo.post(B + "/api/me/purpose", json={"purpose": "home", "examples": False})
fs = r.json()["features"].split(",")
check(r.ok and {"contracts", "home", "care", "health", "review", "travel", "reading", "habits", "events", "contacts"} <= set(fs) and "family" not in fs, "#741: Home " + str(fs))
fs = Bo.post(B + "/api/me/purpose", json={"purpose": "family", "examples": False}).json()["features"].split(",")
check({"contracts", "home", "travel", "family"} <= set(fs) and "health" not in fs and "review" not in fs, "#741: Family + contracts, home, travel " + str(fs))
fs = Bo.post(B + "/api/me/purpose", json={"purpose": "team", "examples": False}).json()["features"].split(",")
check(not {"contracts", "home", "travel", "health"} & set(fs), "#741: Team without Home & life")

# ================================================================== #752: organisations
j = A.get(B + "/api/admin/orgs").json()
check(len(j["orgs"]) == 1 and j["orgs"][0]["name"] == "Kalmido" and j["visibility"] == "org" and 1 in j["orgs"][0]["members"] and BOB in j["orgs"][0]["members"],
      "#752: one organisation from the start (named after the domain), everyone in it, visibility org " + json.dumps(j)[:200])
O1 = j["orgs"][0]["id"]
check(A.get(B + "/api/auth/info").json()["org"] == "Kalmido" and A.get(B + "/api/state").json()["me"]["orgs"] == ["Kalmido"], "#752: the name on the login page and in the state")
# 2.23.0 (#799): organisations are no longer created in the app: a second one is set up in the database (an instance that
# kept several from 2.22 = "multi", where members and visibility stay editable)
check(A.post(B + "/api/admin/orgs", json={"name": "Other Co", "icon": "🏭"}).status_code == 403, "#799: no new organisation in the app")
O2 = dbx("INSERT INTO orgs(name,icon,created_at) VALUES('Other Co','🏭','2026-10-05T00:00:00Z') RETURNING id")[0][0]
ZOE = A.post(B + "/api/users", json={"username": "zoe", "display_name": "Zoe", "password": "password123", "orgs": [O2], "email": "zoe@other.test"}).json()["id"]
Zo = sess("zoe")
check(set(next(u for u in A.get(B + "/api/users").json()["users"] if u["id"] == ZOE)["orgs"]) == {O2}, "#752: a new person in the chosen organisation")
seen_b = {u["id"] for u in Bo.get(B + "/api/users").json()["users"]}
seen_z = {u["id"] for u in Zo.get(B + "/api/users").json()["users"]}
check(ZOE not in seen_b and BOB not in seen_z and 1 not in seen_z and ZOE in seen_z, "#752: people see only their organisation " + str((seen_b, seen_z)))
check(len(A.get(B + "/api/users").json()["users"]) >= 5 and ZOE in {u["id"] for u in A.get(B + "/api/users").json()["users"]}, "#752: admins see everyone")
BL = Bo.post(B + "/api/lists", json={"name": "Bob's list"}).json()["id"]
check(Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": ZOE, "role": "edit"}).status_code == 404, "#752: sharing with someone outside: like an unknown user (404)")
check(Bo.put(B + "/api/folders/people", json={"folder": "X", "user_id": ZOE}).status_code in (400, 404), "#752: … also a folder")
check(Bo.post(B + "/api/events", json={"title": "Meet", "start": D(1) + "T10:00", "attendees": [{"user_id": ZOE}]}).status_code in (400, 409), "#752: … also as an attendee")
# own contacts
A.put(B + "/api/admin/orgs/visibility", json={"mode": "contacts"})
check(A.get(B + "/api/state").json()["people_visibility"] == "contacts", "#752: mode own contacts")
seen_b = {u["id"] for u in Bo.get(B + "/api/users").json()["users"]}
check(1 in seen_b and ZOE not in seen_b and EVE not in seen_b, "#752: contacts: only people one shares a list with " + str(seen_b))
r = Bo.put(B + f"/api/lists/{BL}/members", json={"email": "nobody@nowhere.test", "role": "edit"})
r2 = Bo.put(B + f"/api/lists/{BL}/members", json={"email": "ZOE@other.test", "role": "edit"})
check(r.ok and r2.ok and r.json() == r2.json() == {"ok": True, "by_email": True}, "#752: share by e-mail: the same answer whether or not the address has an account")
check(BL in {l["id"] for l in Zo.get(B + "/api/state").json()["lists"]} and BOB in {u["id"] for u in Zo.get(B + "/api/users").json()["users"]},
      "#752: … the list is shared, now they are connected")
A.put(B + "/api/admin/orgs/visibility", json={"mode": "org"})
check(A.patch(B + f"/api/admin/orgs/{O2}", json={"name": "Other Company", "members": [ZOE, BOB]}).ok and BOB in {u["id"] for u in Zo.get(B + "/api/users").json()["users"]},
      "#752: rename + members")
check(Bo.get(B + "/api/admin/orgs").status_code == 403, "#752: organisations are for admins")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
