#!/usr/bin/env python3
"""2.98.0 API tests, part A (#1953): scheduling polls, own container (start.sh). Invented names only, addresses @example.com.
 - module "events" needed (409 without); people only: an agent token and a personal API token are refused (403)
 - creating: 2-20 times (1 or 21: 400), a link, the poll in the private space; changing the times keeps the votes of a time
 - the public page /s/v/<token> without an account: the times, a name + yes / maybe / no, the signed page stamp (too quick or
   used twice: sent again), the honeypot (pretends, nothing stored), the own vote changed through the cookie and through the
   edit link; the names of the voters with their answers, never an address; show_votes off: no names
 - wrong / regenerated (old) / revoked / expired / deleted token: the same 404 page; an agent never votes through the link
 - the result: counts per time, the best time (most yes, then maybe); the addresses only for who may change the poll
 - another person / another organisation: 404; an organisation's poll: every member reads it (no addresses), only the owner or
   an admin of the organisation changes it (403) (tenant-matrix: poll)
 - "Choose this time": exactly one event in the chosen calendar (title, place, time, the voters in the description), the poll
   closed, the link shows only the chosen time and takes no votes (409), a second choice 409, a calendar of another person 404;
   reopen (the undo): the event goes to the trash, the poll is open again
 - delete + restore (undo); moving private <-> organisation: dry run, move, the link to a task of the old workspace taken off,
   the move back; a plain member may not move someone else's (403), a foreign organisation 409, agents 403
 - a person without an organisation (freelancer-matrix: polls): creating, voting, choosing; there is no other workspace (409)
 - the limit per address (429) and the nightly boundary check with polls
usage: p298_a_api_test.py <datadir>      (a fresh container; P298A_NOSTART=1 = the server already runs)"""
import json
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def py_in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app, json\n" + code],
                       capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-400:]


TIMES = [{"start": "2031-03-10T10:00"}, {"start": "2031-03-11T14:30"}, {"start": "2031-03-12T09:00", "end": "2031-03-12T09:45"}]


def mk(s, **kw):
    b = {"title": "Team lunch", "description": "Somewhere nice", "duration": 60, "location": "Room 2", "tz": "Europe/Berlin",
         "options": TIMES}
    b.update(kw)
    return s.post(B + "/api/polls", json=b)


def path(url):
    return "/s/v/" + url.rsplit("/s/v/", 1)[1]


def page(v, p):
    """A visitor's page (requests.Session v) -> (status, html, stamp)."""
    r = v.get(B + p, headers={"Accept-Language": "en"})
    m = re.search(r'name="stamp" value="([^"]+)"', r.text)
    return r.status_code, r.text, (m.group(1) if m else "")


def vote(v, p, stamp, name, answers, email="", **extra):
    d = {"name": name, "email": email, "stamp": stamp, **{f"a{k}": x for k, x in answers.items()}, **extra}
    return v.post(B + p, data=d, headers={"Accept-Language": "en"})


def visitor():
    v = requests.Session()
    return v


# 2.149.0 (#2513): the minute of the rate limits shortened to RATE_S (test containers only, KALMIDO_TEST_RATE_WINDOW_S)
RATE_S = 60 if os.environ.get("P298A_NOSTART") else 20
if not os.environ.get("P298A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True,
                       env=dict(os.environ, EXTRA=(os.environ.get("EXTRA", "") + f" -e KALMIDO_TEST_RATE_WINDOW_S={RATE_S}").strip()))
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
for u in ("bob", "carol", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "frank" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
Bo, Ca, Fr = sess("bob"), sess("carol"), sess("frank")
for s in (A, Bo, Ca, Fr):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "comments,events,cal"}).ok

# ================================================================ the module, people only
Fr.patch(B + "/api/settings", json={"features": "comments"})
check(mk(Fr).status_code == 409 and Fr.get(B + "/api/polls").status_code == 409, "module events off: 409")
Fr.patch(B + "/api/settings", json={"features": "comments,events,cal"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
r = A.post(B + "/api/me/tokens", json={"name": "t1", "scopes": ["read", "write", "private"]})
PTH = {"Authorization": "Bearer " + r.json()["token"], **H}
for who, hd in (("agent", AGH), ("API token", PTH)):
    check(requests.get(B + "/api/polls", headers=hd).status_code in (401, 403), f"{who}: no list")
    check(requests.post(B + "/api/polls", headers=hd, json={"title": "x", "options": TIMES}).status_code in (401, 403), f"{who}: no creating")

# ================================================================ creating
check(mk(Bo, options=TIMES[:1]).status_code == 400, "one time only: 400")
check(mk(Bo, options=[{"start": f"2031-04-{d:02d}T10:00"} for d in range(1, 22)]).status_code == 400, "21 times: 400")
check(mk(Bo, options=[{"start": "2031-04-01T10:00"}, {"start": "nonsense"}]).status_code == 400, "an invalid time: 400")
check(mk(Bo, title="  ").status_code == 400 and mk(Bo, tz="Mars/Base").status_code == 400, "no title / an unknown zone: 400")
r = mk(Bo)
check(r.status_code == 201, "created: 201 " + r.text[:200])
P = r.json()["poll"]
PID, URL = P["id"], P["url"]
check(P["space"] == "private" and len(P["options"]) == 3 and P["options"][0]["start"] == "2031-03-10T10:00"
      and P["options"][0]["end"] == "2031-03-10T11:00" and P["options"][2]["end"] == "2031-03-12T09:45" and P["closed_at"] is None,
      "private, three times, the end from the duration or given " + json.dumps(P)[:300])
check(URL and "/s/v/" in URL and P["live"] is True, "a link, live")
PP = path(URL)
check([x["id"] for x in Bo.get(B + "/api/polls").json()["items"]] == [PID], "listed for the owner")

# ================================================================ the public page, voting
V1, V2, V3, V4 = visitor(), visitor(), visitor(), visitor()
st, txt, s1 = page(V1, PP)
check(st == 200 and "Team lunch" in txt and "Room 2" in txt and "Europe/Berlin" in txt and s1, "the page: title, place, the zone, a stamp "
      + str(st) + " " + txt[:300])
if st != 200:
    print(subprocess.run(["docker", "logs", "--tail", "60", CT], capture_output=True, text=True).stderr[-4000:], flush=True)
check("bob@example.com" not in txt and "Alice" not in txt, "the page names nothing of others (no addresses)")
check("script-src 'self'" in V1.get(B + PP).headers.get("Content-Security-Policy", "") and "Intl.DateTimeFormat" in V1.get(B + "/s/v/time.js").text, "own small script only")
_, _, s2 = page(V2, PP)
_, _, s3 = page(V3, PP)
_, _, s4 = page(V4, PP)
_, _, s5 = page(V4, PP)
o1, o2, o3 = (o["id"] for o in P["options"])
r = vote(V1, PP, s1, "Anna", {o1: "y", o2: "m", o3: "n"}, email="anna@example.com")
check(r.status_code == 400 and "sent very quickly" in r.text, "sent within 3 s: asked to send again")
time.sleep(3.3)
_, _, s1 = page(V1, PP)
time.sleep(3.3)
r = vote(V1, PP, s1, "Anna", {o1: "y", o2: "m", o3: "n"}, email="anna@example.com")
check(r.status_code == 200 and "Your vote has been saved" in r.text and "?e=" in r.text, "Anna voted, the edit link shown " + r.text[:200])
EDIT_A = re.search(r'\?e=([^"&]+)', r.text).group(1) if "?e=" in r.text else ""
check(vote(V2, PP, s1, "Copycat", {o1: "y"}).status_code == 400, "a stamp counts once")
r = vote(V2, PP, s2, "Ben", {o1: "m", o2: "y"})
check(r.status_code == 200 and "saved" in r.text, "Ben voted (no address)")
r = vote(V3, PP, s3, "Bot", {o1: "y"}, website="http://spam.example.com")
check(r.status_code == 200 and "Thank you" in r.text, "honeypot: pretends")
r = vote(V4, PP, s4, "", {o1: "y"})
check(r.status_code == 400 and "enter your name" in r.text, "no name: 400")
r = vote(V4, PP, s5, "Cleo", {})
check(r.status_code == 400 and "at least one" in r.text, "no answer: 400")
d = Bo.get(B + f"/api/polls/{PID}").json()["poll"]
check(d["votes_n"] == 2 and [v["name"] for v in d["votes"]] == ["Anna", "Ben"], "two votes stored (not the bot) " + json.dumps(d.get("votes"))[:300])
check([(o["y"], o["m"], o["n"]) for o in d["options"]] == [(1, 1, 0), (1, 1, 0), (0, 0, 1)] and d["best_id"] == o1,
      "counts per time, the best = the earliest of equals " + json.dumps(d["options"])[:300])
check(d["votes"][0].get("email") == "anna@example.com", "the owner sees the address")
# the own vote through the cookie (same visitor) and through the edit link (another device)
st, txt, s6 = page(V1, PP)
check('value="Anna"' in txt and "Change my vote" in txt and "anna@example.com" in txt, "the cookie: the own vote prefilled")
check("Ben" in txt and "anna@example.com" in txt, "names of the voters shown")
_, txt2, _ = page(V2, PP)
check("anna@example.com" not in txt2 and "Anna" in txt2, "another visitor: Anna's name, never her address")
time.sleep(3.3)
r = vote(V1, PP, s6, "Anna B.", {o1: "n", o2: "y", o3: "y"}, email="anna@example.com", edit=EDIT_A)
check(r.status_code == 200, "Anna changed her vote")
V9 = visitor()
st, txt, s9 = page(V9, PP + "?e=" + EDIT_A)
check('value="Anna B."' in txt and "Change my vote" in txt, "the edit link on another device")
check('value="Anna B."' not in page(visitor(), PP + "?e=" + EDIT_A[:-3] + "xyz")[1], "a wrong edit key opens an empty form")
d = Bo.get(B + f"/api/polls/{PID}").json()["poll"]
check(d["votes_n"] == 2 and d["votes"][0]["name"] == "Anna B." and d["votes"][0]["answers"] == {str(o1): "n", str(o2): "y", str(o3): "y"},
      "the change replaced the vote (no second row)")
check(d["best_id"] == o2, "best time now the second (2 yes)")
# show_votes off: no names on the page
check(Bo.patch(B + f"/api/polls/{PID}", json={"show_votes": False}).ok, "names hidden")
_, txt, _ = page(visitor(), PP)
check("Ben" not in txt and "Anna" not in txt, "show_votes off: no names on the page")
Bo.patch(B + f"/api/polls/{PID}", json={"show_votes": True})
# changing the times keeps the votes of the times that stay
r = Bo.patch(B + f"/api/polls/{PID}", json={"options": [{"id": o1, "start": "2031-03-10T10:00"}, {"id": o2, "start": "2031-03-11T15:00"},
                                                         {"start": "2031-03-13T08:00"}]})
check(r.ok, "times changed " + r.text[:200])
d = r.json()["poll"]
check(len(d["options"]) == 3 and d["options"][1]["id"] == o2 and d["options"][1]["start"] == "2031-03-11T15:00" and d["options"][1]["y"] == 2
      and all(o["id"] != o3 for o in d["options"]), "a kept time keeps its votes, a dropped one goes")

# ================================================================ links that do not open
check(page(visitor(), "/s/v/" + "x" * 24)[0] == 404 and page(visitor(), "/s/v/short")[0] == 404, "unknown token: 404")
r = Bo.patch(B + f"/api/polls/{PID}", json={"regenerate": True})
NEWP = path(r.json()["poll"]["url"])
check(NEWP != PP and page(visitor(), PP)[0] == 404 and page(visitor(), NEWP)[0] == 200, "regenerated: the old link 404, the new one opens")
PP = NEWP
check(Bo.patch(B + f"/api/polls/{PID}", json={"link_on": False}).ok and page(visitor(), PP)[0] == 404, "revoked: 404")
check(Bo.get(B + f"/api/polls/{PID}").json()["poll"]["live"] is False, "revoked: not live")
Bo.patch(B + f"/api/polls/{PID}", json={"link_on": True})
check(Bo.patch(B + f"/api/polls/{PID}", json={"expires_at": "2020-01-01"}).ok and page(visitor(), PP)[0] == 404, "expired: 404")
check(Bo.patch(B + f"/api/polls/{PID}", json={"expires_at": None}).ok and page(visitor(), PP)[0] == 200, "no end: opens again")
st, txt, _ = page(visitor(), PP)
gone_txt = requests.get(B + "/s/v/" + "y" * 24).text
check("Team lunch" not in gone_txt, "the 404 page names nothing")
check(requests.get(B + PP, headers=AGH).status_code == 404, "an agent never opens / votes through the link")

# ================================================================ other people, organisations (tenant-matrix: poll)
for who, s in (("another member", Ca), ("another organisation", Fr), ("the admin", A)):
    check(s.get(B + f"/api/polls/{PID}").status_code == 404 and s.patch(B + f"/api/polls/{PID}", json={"title": "x"}).status_code == 404
          and s.delete(B + f"/api/polls/{PID}").status_code == 404 and s.post(B + f"/api/polls/{PID}/decide", json={"option_id": o1}).status_code == 404
          and s.post(B + f"/api/polls/{PID}/move-space", json={"to": SP}).status_code == 404 and PID not in [x["id"] for x in s.get(B + "/api/polls").json()["items"]],
          f"{who}: a private poll is 404 (read, change, delete, choose, move, list)")
time.sleep(RATE_S + 1)  # 2.149.0 (#2513): the per-address minute of the votes above passes (TPO_VOTE_RATE)
r = mk(Bo, title="Org planning", space=SP)
check(r.status_code == 201 and r.json()["poll"]["space"] == SP, "an organisation's poll")
OP = r.json()["poll"]
OPP = path(OP["url"])
_, _, so = page(V1, OPP)
time.sleep(3.3)
check(vote(V1, OPP, so, "Dora", {OP["options"][0]["id"]: "y"}, email="dora@example.com").status_code == 200, "a vote in the organisation's poll")
d = Ca.get(B + f"/api/polls/{OP['id']}")
check(d.status_code == 200 and d.json()["poll"]["can_edit"] is False and "email" not in d.json()["poll"]["votes"][0] and d.json()["poll"]["url"] is None,
      "a member reads it: no addresses, no link " + d.text[:200])
check(Ca.patch(B + f"/api/polls/{OP['id']}", json={"title": "x"}).status_code == 403 and Ca.delete(B + f"/api/polls/{OP['id']}").status_code == 403
      and Ca.post(B + f"/api/polls/{OP['id']}/decide", json={"option_id": OP["options"][0]["id"]}).status_code == 403, "a member may not change it (403)")
check(Fr.get(B + f"/api/polls/{OP['id']}").status_code == 404 and OP["id"] not in [x["id"] for x in Fr.get(B + "/api/polls").json()["items"]],
      "another organisation: 404")
check(A.patch(B + f"/api/polls/{OP['id']}", json={"description": "checked"}).ok, "the organisation's admin may change it")
check(Bo.post(B + f"/api/polls/{OP['id']}/move-space", json={"to": "private", "dry": 1}).ok
      and A.post(B + f"/api/polls/{OP['id']}/move-space", json={"to": "private"}).status_code == 403, "only the owner moves it (admin 403)")
check(mk(Bo, space=f"org:{OP['org_id'] + 999}").status_code == 404, "creating in a foreign organisation: 404")

# ================================================================ choosing the time
r = Bo.post(B + f"/api/polls/{PID}/decide", json={"option_id": o2, "mail": True})
check(r.status_code == 200 and r.json()["event_id"], "chosen: an event " + r.text[:300])
EID = r.json().get("event_id")
d = r.json()["poll"]
check(d["closed_at"] and d["chosen_id"] == o2 and d["event_id"] == EID and isinstance(r.json()["mailed"], int), "the poll closed")
ev = Bo.get(B + f"/api/events/{EID}").json()
check(ev.get("title") == "Team lunch" and ev.get("location") == "Room 2" and str(ev.get("start", "")).startswith("2031-03-11T15:00")
      and "Anna B." in ev.get("description", "") and "Ben" in ev.get("description", ""), "the event: title, place, time, voters " + json.dumps(ev)[:300])
n = py_in_app("from kalmido.core.db import connect\nc = connect(); print(c.execute(\"SELECT COUNT(*) FROM events WHERE title='Team lunch' AND deleted_at IS NULL\").fetchone()[0])")
check(n == "1", "exactly one event " + n)
check(Bo.post(B + f"/api/polls/{PID}/decide", json={"option_id": o1}).status_code == 409, "a second choice: 409")
st, txt, _ = page(visitor(), PP)
check(st == 200 and "The time has been chosen" in txt and 'name="stamp"' not in txt, "the link shows only the result")
r = V2.post(B + PP, data={"name": "Late", "a%d" % o1: "y", "stamp": "1.aaaaaaaaaaaa.x"}, headers={"Accept-Language": "en"})
check(r.status_code == 409, "closed: no more votes (409)")
check(Bo.patch(B + f"/api/polls/{PID}", json={"options": TIMES}).status_code == 409, "closed: the times stay")
r = Bo.post(B + f"/api/polls/{PID}/reopen")
check(r.ok and r.json()["poll"]["closed_at"] is None and r.json()["poll"]["event_id"] is None, "reopened (the undo)")
check(Bo.get(B + f"/api/events/{EID}").status_code == 404, "the event went to the trash")
check(Bo.post(B + f"/api/events/{EID}/restore").ok, "the event can be restored from the trash")
Bo.delete(B + f"/api/events/{EID}")
# a calendar of another person
fcal = py_in_app("from kalmido.core.db import connect\nfrom kalmido.events.model import default_cal\nc = connect(); i = default_cal(c, %d); c.commit(); print(i)" % uid["carol"])
check(Bo.post(B + f"/api/polls/{PID}/decide", json={"option_id": o1, "cal_id": int(fcal)}).status_code == 404, "a calendar of another person: 404 " + fcal)
check(Bo.get(B + f"/api/polls/{PID}").json()["poll"]["closed_at"] is None, "still open after the refused choice")

# ================================================================ delete + restore
check(Bo.delete(B + f"/api/polls/{PID}").ok and page(visitor(), PP)[0] == 404 and Bo.get(B + f"/api/polls/{PID}").status_code == 404, "deleted: link 404")
check(PID in [x["id"] for x in Bo.get(B + "/api/polls?deleted=1").json()["items"]], "in the trash")
check(Bo.post(B + f"/api/polls/{PID}/restore").ok and page(visitor(), PP)[0] == 200, "restored: link opens again")

# ================================================================ moving between workspaces (P4)
tl = Bo.post(B + "/api/lists", json={"name": "Private things", "org_id": None}).json()
tid = Bo.post(B + "/api/tasks", json={"list_id": tl["id"], "title": "Plan lunch"}).json()["id"]
r = mk(Bo, title="With a task", task_id=tid)
check(r.status_code == 201 and r.json()["poll"]["task_id"] == tid, "bound to a private task " + r.text[:200])
TP = r.json()["poll"]["id"]
check(mk(Bo, title="x", space=SP, task_id=tid).status_code == 400, "a task of another workspace cannot be chosen")
check(mk(Ca, title="x", task_id=tid).status_code == 400, "a task the person does not see cannot be chosen")
r = Bo.post(B + f"/api/polls/{TP}/move-space", json={"to": SP, "dry": 1})
check(r.ok and any("task" in n for n in r.json()["notes"]), "dry run names the task link " + r.text[:300])
r = Bo.post(B + f"/api/polls/{TP}/move-space", json={"to": SP})
check(r.ok and r.json()["space"] == SP and r.json()["poll"]["task_id"] is None, "moved into the organisation, the task link off")
check(Ca.get(B + f"/api/polls/{TP}").status_code == 200, "now every member reads it")
check(Bo.post(B + f"/api/polls/{TP}/move-space", json={"to": SP}).status_code == 409, "same workspace: 409")
check(Bo.post(B + f"/api/polls/{TP}/move-space", json={"to": f"org:{OP['org_id'] + 999}"}).status_code == 409, "a foreign organisation: 409")
check(requests.post(B + f"/api/polls/{TP}/move-space", headers=AGH, json={"to": "private"}).status_code in (401, 403), "agents: 403")
r = Bo.post(B + f"/api/polls/{TP}/move-space", json={"to": "private"})
check(r.ok and r.json()["space"] == "private" and Ca.get(B + f"/api/polls/{TP}").status_code == 404, "moved back: private again")

# ================================================================ a person without an organisation (freelancer-matrix: polls)
FID, Fl = freelancer(B, A)
r = mk(Fl, title="Freelance kickoff")
check(r.status_code == 201 and r.json()["poll"]["space"] == "private", "freelancer: created in the private space")
FP = r.json()["poll"]
FPP = path(FP["url"])
_, _, sf = page(V3, FPP)
time.sleep(3.3)
check(vote(V3, FPP, sf, "Client", {FP["options"][0]["id"]: "y"}, email="client@example.com").status_code == 200, "freelancer's poll: a vote")
r = Fl.post(B + f"/api/polls/{FP['id']}/decide", json={"option_id": FP["options"][0]["id"]})
check(r.ok and r.json()["event_id"], "freelancer: chosen, an event")
check(Fl.post(B + f"/api/polls/{FP['id']}/move-space", json={"to": SP}).status_code == 409, "freelancer: no other workspace (409)")
check(Fl.get(B + f"/api/polls/{PID}").status_code == 404 and Bo.get(B + f"/api/polls/{FP['id']}").status_code == 404, "freelancer and others: 404 both ways")
check(Fl.get(B + "/api/polls").ok and Fl.get(B + "/api/polls?space=private").ok, "freelancer: every GET of the area works")

# ================================================================ the limit per address, the boundary check
codes = []
for i in range(10):
    codes.append(V4.post(B + PP, data={"name": f"N{i}", "stamp": "1.aaaaaaaaaaaa.x"}, headers={"Accept-Language": "en"}).status_code)
check(429 in codes, "votes per address and minute are limited " + str(codes))
dbx = py_in_app("""from kalmido.core.db import connect
from kalmido.accounts.tenancy import boundary_check
c = connect(); c.execute("DELETE FROM org_members WHERE org_id=? AND user_id=?", (%d, %d)); r = boundary_check(c); c.rollback(); c.close()
print(json.dumps(r["kinds"].get("sched_poll", 0)))""" % (ORG, uid["bob"]))
check(dbx.strip() not in ("", "0") and not dbx.startswith("ERR"), "the boundary check counts an organisation's poll of someone who left " + dbx[:300])

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
