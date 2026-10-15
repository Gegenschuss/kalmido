#!/usr/bin/env python3
"""2.46.1 API tests (part D), own container (start.sh).

 - #1639: a list shared only with an agent has a channel; an agent that listens in gets every channel message of a person as
   team_message (mentioned false, listening true), an agent that does not listen in gets nothing without an @mention, an
   agent's own message triggers nothing (no loop), a health list never; the agent may write in the channel of a list shared
   with it and not in the channel of a list it does not see
 - #1361 (favourites 4-7): GET /api/v1/lists(/{id}) carries "favorite" = a star of the agent's person (personal agent),
   only lists the agent sees, a team agent false; fav_quiet: a list without a star pushes no comment, an @mention still
   comes, a starred list pushes as before, the News stay complete; POST /api/favorites/suggestion offers a busy list once,
   never a starred / quiet list, fav_suggest 0 = none, agents 403; Ctrl+K order is client-side (p2461_d_ui.js)
 - #1422: the folder default hide_done goes through folder_apply: "all" drops the owner's own choice of the lists and
   counts the lists that change, an own choice against the folder marks the list (folder_own, "This list differs"), "Back
   to the folder" drops it, "Only new lists" and "Not set" keep what each list shows, dry_run changes nothing, a shared list
   of someone else keeps its setting
usage: p2461_d_api_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
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


if os.environ.get("P2461_D_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
BOB = r.json()["id"]
Bo = sess("bob")
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
AG = {}
for n in ("claude", "otto"):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": n, "display_name": n.title()})
    assert r.ok, r.text
    AG[n] = (r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]})
CL, CLH = AG["claude"]
OT, OTH = AG["otto"]


def latest(h):
    return requests.get(V + "/agent/events?since=latest", headers=h).json()["cursor"]


def events(h, since, kind=None):
    d = requests.get(V + f"/agent/events?since={since}&limit=200", headers=h).json()["data"]
    return [e for e in d if kind is None or e["event"] == kind]


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def room_of(s, lid):
    return next((x for x in s.get(B + "/api/team").json().get("rooms", []) if x["kind"] == "list" and x["list_id"] == lid), None)


# ================================================================== #1639 list channel for agents that listen in
# a software list shared with nobody but the agent claude: claude listens in (the default of software lists)
SW = A.post(B + "/api/lists", json={"name": "Build", "org_id": ORG, "ptype": "software"}).json()["id"]
check(A.put(B + f"/api/lists/{SW}/members", json={"user_id": CL, "role": "edit"}).ok, "setup: claude in the software list")
st = next(l for l in A.get(B + "/api/state").json()["lists"] if l["id"] == SW)
check(st.get("listen_agent_ids") == [CL], "setup: claude listens in " + str(st.get("listen_agent_ids")))
room = room_of(A, SW)
check(room is not None, "a list shared only with an agent has a channel")
# a plain list shared with otto, who does not listen in (not a software list)
PL = A.post(B + "/api/lists", json={"name": "Plain", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{PL}/members", json={"user_id": OT, "role": "edit"}).ok, "setup: otto in the plain list")
proom = room_of(A, PL)
check(proom is not None, "setup: the plain list's channel")
if room and proom:
    c1, o1 = latest(CLH), latest(OTH)
    r = A.post(B + f"/api/team/rooms/{room['id']}/messages", json={"body": "What is still open here?"})
    check(r.status_code == 201, "alice writes in the channel " + r.text[:100])
    ev = events(CLH, c1)
    check([e["event"] for e in ev] == ["team_message"], "claude listens in: team_message without an @mention " + str(ev)[:200])
    if ev:
        d = ev[0]["data"]
        check(d.get("mentioned") is False and d.get("listening") is True and d["room"]["id"] == room["id"]
              and d["room"]["list_id"] == SW and d["message"]["text"] == "What is still open here?" and d["user"]["id"] == ALICE,
              "team_message: mentioned false, listening true, room, text, user " + str(d)[:300])
    check(events(OTH, o1) == [], "otto (not in the list): nothing")
    # the agent answers in the channel: allowed, and it triggers nothing (no loop)
    c2 = latest(CLH)
    r = requests.post(V + f"/team/rooms/{room['id']}/messages", headers=CLH, json={"body": "Two tasks are open.", "reply_to": r.json()["id"]})
    check(r.status_code == 201, "claude answers in the channel of a list shared only with it " + r.text[:100])
    check(events(CLH, c2) == [], "the agent's own answer: no event (no loop)")
    msgs = A.get(B + f"/api/team/rooms/{room['id']}/messages").json()["messages"]
    check([m["user_id"] for m in msgs] == [ALICE, CL], "alice sees the agent's answer in the channel")
    # otto does not listen in on the plain list: nothing without an @mention, the @mention still comes
    o3 = latest(OTH)
    A.post(B + f"/api/team/rooms/{proom['id']}/messages", json={"body": "Any news?"})
    check(events(OTH, o3) == [], "otto does not listen in: no team_message without an @mention")
    A.post(B + f"/api/team/rooms/{proom['id']}/messages", json={"body": f"<@{OT}> any news?"})
    ev = events(OTH, o3)
    check([e["event"] for e in ev] == ["team_message"] and ev[0]["data"].get("mentioned") is True
          and ev[0]["data"].get("listening") is False, "otto @mentioned: team_message, mentioned true " + str(ev)[:200])
    # an agent cannot read or write the channel of a list it does not see
    r = requests.post(V + f"/team/rooms/{proom['id']}/messages", headers=CLH, json={"body": "hello"})
    check(r.status_code == 404, "claude: no post in the channel of a list not shared with it " + str(r.status_code))
    r = requests.get(V + f"/team/rooms/{proom['id']}/messages", headers=CLH)
    check(r.status_code == 404, "claude: the channel of a list not shared with it does not exist " + str(r.status_code))
    rooms = requests.get(V + "/team/rooms", headers=CLH).json()["data"]
    check([x.get("list_id") for x in rooms] == [SW], "claude sees only the channel of its own list " + str(rooms)[:200])
    # otto listens in on the plain list: a member's message reaches it (the list lets members use the agent)
    check(A.patch(B + f"/api/lists/{PL}", json={"listen_agent_ids": [OT]}).ok, "setup: otto listens in on the plain list")
    check(A.put(B + f"/api/lists/{PL}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: bob in the plain list")
    A.patch(B + f"/api/lists/{PL}", json={"agent_members": True})
    o4 = latest(OTH)
    r = Bo.post(B + f"/api/team/rooms/{proom['id']}/messages", json={"body": "Who takes the second one?"})
    check(r.status_code == 201, "bob writes in the channel " + r.text[:120])
    ev = events(OTH, o4)
    check([e["event"] for e in ev] == ["team_message"] and ev[0]["data"]["user"]["id"] == BOB,
          "a member's message reaches the listening agent " + str(ev)[:200])
    # the agent's own message in a channel where it listens in: nothing (no loop)
    o5 = latest(OTH)
    check(requests.post(V + f"/team/rooms/{proom['id']}/messages", headers=OTH, json={"body": "I take it."}).status_code == 201,
          "otto writes in the channel")
    check(events(OTH, o5) == [], "otto's own message: no event")
    # a health list: never
    dbx("UPDATE lists SET life='health' WHERE id=?", (PL,), write=True)
    o6 = latest(OTH)
    A.post(B + f"/api/team/rooms/{proom['id']}/messages", json={"body": "Appointment on Monday"})
    check(events(OTH, o6) == [], "a health list: no team_message")
    dbx("UPDATE lists SET life='' WHERE id=?", (PL,), write=True)
    # listening switched off: only @mentions again
    check(A.patch(B + f"/api/lists/{SW}", json={"listen_agent_ids": []}).ok, "setup: claude stops listening in")
    c6 = latest(CLH)
    A.post(B + f"/api/team/rooms/{room['id']}/messages", json={"body": "Anything else?"})
    check(events(CLH, c6) == [], "listening off: no team_message without an @mention")

# ================================================================== #1361 favourites, points 4-7
# 7: the agent API marks the favourites of the agent's person
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "pia", "display_name": "Pia",
                                          "owner_id": ALICE})
check(r.ok, "setup: alice's personal agent " + r.text[:120])
PIA, PIAH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
F1 = A.post(B + "/api/lists", json={"name": "Starred", "org_id": ORG}).json()["id"]
F2 = A.post(B + "/api/lists", json={"name": "Plain two", "org_id": ORG}).json()["id"]
F3 = A.post(B + "/api/lists", json={"name": "Starred, not for pia", "org_id": ORG}).json()["id"]
for lid in (F1, F2):
    A.put(B + f"/api/lists/{lid}/members", json={"user_id": PIA, "role": "edit"})
for lid in (F1, F3):
    check(A.put(B + f"/api/lists/{lid}/favorite", json={}).ok, f"setup: star {lid}")
lv = {l["id"]: l for l in requests.get(V + "/lists", headers=PIAH).json()["data"]}
check(lv.get(F1, {}).get("favorite") is True and lv.get(F2, {}).get("favorite") is False and F3 not in lv,
      "pia: favorite true for the starred list, false for the other, the starred list it does not see is not there")
check(requests.get(V + f"/lists/{F1}", headers=PIAH).json().get("favorite") is True, "pia: GET /lists/{id} favorite")
check(requests.get(V + f"/lists/{F3}", headers=PIAH).status_code == 404, "pia: the starred list not shared with it: 404")
check(A.put(B + f"/api/lists/{SW}/favorite", json={}).ok, "setup: star the software list")
lc = {l["id"]: l for l in requests.get(V + "/lists", headers=CLH).json()["data"]}
check(lc.get(SW, {}).get("favorite") is False, "a team agent (no owner): favorite false")
check(requests.put(B + f"/api/lists/{F2}/favorite", headers={**PIAH, **H}, json={}).status_code in (401, 403, 404), "an agent sets no star")

# 4: quieter pushes from lists without a star (bob has a push topic; he follows his own tasks)
A.patch(B + f"/api/users/{BOB}", json={"ntfy_topic": "t-bob"})
Q1 = A.post(B + "/api/lists", json={"name": "Quiet", "org_id": ORG}).json()["id"]
Q2 = A.post(B + "/api/lists", json={"name": "Loud", "org_id": ORG}).json()["id"]
for lid in (Q1, Q2):
    A.put(B + f"/api/lists/{lid}/members", json={"user_id": BOB, "role": "edit"})
TQ1 = Bo.post(B + "/api/tasks", json={"title": "Quiet task", "list_id": Q1}).json()["id"]
TQ2 = Bo.post(B + "/api/tasks", json={"title": "Loud task", "list_id": Q2}).json()["id"]
check(Bo.put(B + f"/api/lists/{Q2}/favorite", json={}).ok, "setup: bob stars Loud")
check(Bo.patch(B + "/api/settings", json={"fav_quiet": "1"}).ok, "bob: fav_quiet on")
check(Bo.patch(B + "/api/settings", json={"fav_quiet": "2"}).status_code == 400, "fav_quiet is a switch")


def bob_push(fn):
    time.sleep(3.5)  # the push gap of the test container
    n = len(pushes())
    fn()
    time.sleep(1.5)
    return [p for p in pushes()[n:] if p.get("topic") == "t-bob"]


got = bob_push(lambda: A.post(B + f"/api/tasks/{TQ1}/comments", json={"body": "Looks good"}))
check(got == [], "fav_quiet: a comment in a list without a star: no push " + str(got)[:200])
news_q = Bo.get(B + "/api/news").json()["items"]
check(any((x.get("data") or {}).get("task_id") == TQ1 or x.get("task_id") == TQ1 for x in news_q), "fav_quiet: the News keep the comment")
got = bob_push(lambda: A.post(B + f"/api/tasks/{TQ2}/comments", json={"body": "Looks good too"}))
check(len(got) == 1, "fav_quiet: a comment in a starred list still pushes " + str(got)[:200])
got = bob_push(lambda: A.post(B + f"/api/tasks/{TQ1}/comments", json={"body": f"<@{BOB}> please check"}))
check(len(got) == 1, "fav_quiet: an @mention in a list without a star still pushes " + str(got)[:200])
Bo.patch(B + "/api/settings", json={"fav_quiet": "0"})
got = bob_push(lambda: A.post(B + f"/api/tasks/{TQ1}/comments", json={"body": "One more"}))
check(len(got) == 1, "fav_quiet off: the comment pushes again " + str(got)[:200])

# 6: a suggestion once, never automatic
st0 = Bo.get(B + "/api/state").json()["settings"]
check(st0.get("fav_suggest") == "1" and st0.get("fav_quiet") == "0", "defaults: fav_suggest 1, fav_quiet 0")
r = Bo.post(B + "/api/favorites/suggestion", json={})
check(r.ok and r.json().get("list_id") is None, "no busy list yet: no suggestion " + r.text[:120])
Q3 = A.post(B + "/api/lists", json={"name": "Busy", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{Q3}/members", json={"user_id": BOB, "role": "edit"})
TQ3 = Bo.post(B + "/api/tasks", json={"title": "Busy task", "list_id": Q3}).json()["id"]
now = time.time()
for i in range(24):  # bob's own changes on 6 different days of the last two weeks; the starred list gets the same
    at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now - (i % 6 + 1) * 86400))
    for t in (TQ3, TQ2):
        dbx("INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)", (t, BOB, "edit", "{}", at), write=True)
r = Bo.post(B + "/api/favorites/suggestion", json={})
check(r.ok and r.json().get("list_id") == Q3 and r.json().get("name") == "Busy", "a busy list without a star is offered " + r.text[:120])
check(Q3 not in [int(x) for x in (Bo.get(B + "/api/state").json()["settings"].get("fav_lists") or "").split(",") if x], "the star is not set by itself")
r = Bo.post(B + "/api/favorites/suggestion", json={})
check(r.ok and r.json().get("list_id") is None, "each list is offered only once " + r.text[:120])
check(requests.post(B + "/api/favorites/suggestion", headers={**PIAH, **H}, json={}).status_code in (401, 403, 404), "agents: no suggestion")
check(Bo.patch(B + "/api/settings", json={"fav_asked": ""}).status_code in (200, 400) and
      Bo.post(B + "/api/favorites/suggestion", json={}).json().get("list_id") is None, "fav_asked cannot be reset from the app")
Bo.patch(B + "/api/settings", json={"fav_suggest": "0"})
dbx("UPDATE user_settings SET value='' WHERE user_id=? AND key='fav_asked'", (BOB,), write=True)
check(Bo.post(B + "/api/favorites/suggestion", json={}).json().get("list_id") is None, "fav_suggest 0: no suggestion")

# ================================================================== #1422 folder default "Hide completed"
def views(s):
    return json.loads(s.get(B + "/api/state").json()["settings"].get("show_done_views") or "{}")


def own_of(s, lid):
    return json.loads(next(l for l in s.get(B + "/api/state").json()["lists"] if l["id"] == lid).get("folder_own") or "[]")


def shown(s, lid):
    """What the web app shows (showDone / lmDoneDefault): the own choice, else the folder default, else the person's default."""
    st = s.get(B + "/api/state").json()
    v = json.loads(st["settings"].get("show_done_views") or "{}").get(f"l:{lid}")
    if v is not None:
        return bool(v)
    lst = next(l for l in st["lists"] if l["id"] == lid)
    eff, parts = {}, (lst.get("folder") or "").split("/")
    for i in range(1, len(parts) + 1):
        eff.update((st.get("folder_props") or {}).get("/".join(parts[:i])) or {})
    if "hide_done" in eff:
        return not eff["hide_done"]
    return st["settings"].get("show_done_default") != "0"


P1 = A.post(B + "/api/lists", json={"name": "Shoot", "folder": "Jobs", "org_id": ORG}).json()["id"]
P2 = A.post(B + "/api/lists", json={"name": "Edit", "folder": "Jobs", "org_id": ORG}).json()["id"]
BL = Bo.post(B + "/api/lists", json={"name": "Bob's job"}).json()["id"]
Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": ALICE, "role": "edit"})
A.patch(B + f"/api/lists/{BL}", json={"folder": "Jobs"})  # bob's list sits in alice's folder (her own place for it)
check(A.patch(B + "/api/settings", json={"show_done_views": json.dumps({f"l:{P2}": 1, f"l:{BL}": 1})}).ok, "setup: own choices")
check(own_of(A, P2) == [], "an own choice without a folder default: nothing differs")
r = A.put(B + "/api/folders/props", json={"folder": "Jobs", "props": {"hide_done": True}, "apply": "all", "dry_run": True})
check(r.ok and r.json().get("changed") == 2 and views(A).get(f"l:{P2}") == 1 and shown(A, P1),
      "dry_run: counts the 2 lists that would change, changes nothing " + r.text[:200])
r = A.put(B + "/api/folders/props", json={"folder": "Jobs", "props": {"hide_done": True}, "apply": "all"})
check(r.ok and r.json().get("changed") == 2, "all: the counter names the 2 lists that changed " + r.text[:200])
check(not shown(A, P1) and not shown(A, P2) and f"l:{P2}" not in views(A), "all: both own lists hide completed, the own choice is gone")
check(views(A).get(f"l:{BL}") == 1 and shown(A, BL), "a shared list of someone else keeps its setting")
# an own choice against the folder: visible as "differs", until "Back to the folder"
check(A.patch(B + "/api/settings", json={"show_done_views": json.dumps({**views(A), f"l:{P2}": 1})}).ok, "alice shows completed in Edit")
check(own_of(A, P2) == ["hide_done"], "the own choice marks the list as differing " + str(own_of(A, P2)))
fi = A.get(B + "/api/folders/props", params={"folder": "Jobs"}).json()
check(any(x["id"] == P2 and x["own"] == ["hide_done"] for x in fi["lists"]), "the folder dialog knows the differing list")
r = A.put(B + "/api/folders/props", json={"folder": "Jobs", "props": {"hide_done": True}, "apply": "all"})
check(r.ok and any(x["id"] == P2 and x["own"] == ["hide_done"] for x in r.json()["lists"]) and shown(A, P2),
      "all without force: the differing list keeps its choice and is named " + r.text[:200])
check(A.patch(B + "/api/settings", json={"show_done_views": json.dumps({**views(A), f"l:{P2}": 0})}).ok and own_of(A, P2) == [],
      "a choice equal to the folder: no longer differs")
A.patch(B + "/api/settings", json={"show_done_views": json.dumps({**views(A), f"l:{P2}": 1})})
r = A.post(B + f"/api/lists/{P2}/folder-reset", json={})
check(r.ok and own_of(A, P2) == [] and f"l:{P2}" not in views(A) and not shown(A, P2), "Back to the folder: the folder hides completed again")
# "Only new lists": the existing lists keep what they show, a new list follows the folder
r = A.put(B + "/api/folders/props", json={"folder": "Jobs", "props": {"hide_done": False}, "apply": "new"})
check(r.ok and not shown(A, P1) and not shown(A, P2), "Only new lists: the existing lists still hide completed")
check(own_of(A, P1) == ["hide_done"], "Only new lists: an existing list now differs from the folder " + str(own_of(A, P1)))
P3 = A.post(B + "/api/lists", json={"name": "Grade", "folder": "Jobs", "org_id": ORG}).json()["id"]
check(shown(A, P3) and own_of(A, P3) == [], "a new list follows the folder (shows completed)")
r = A.put(B + "/api/folders/props", json={"folder": "Jobs", "props": {"hide_done": False}, "apply": "all", "force": True})
check(r.ok and r.json().get("changed") == 2 and shown(A, P1) and shown(A, P2) and own_of(A, P1) == [],
      "all + force: the differing lists follow too " + r.text[:200])
# "Not set" again: every list keeps what it shows
A.patch(B + "/api/settings", json={"show_done_default": "0"})
r = A.put(B + "/api/folders/props", json={"folder": "Jobs", "props": {"hide_done": None}, "apply": "all"})
check(r.ok and shown(A, P1) and shown(A, P3), "Not set again: the lists keep showing completed (the person's default hides)")
A.patch(B + "/api/settings", json={"show_done_default": "1"})
check(json.loads(Bo.get(B + "/api/state").json()["settings"].get("show_done_views") or "{}") == {}, "bob's own settings are untouched")

print(f"p2461_d_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
time.sleep(0.1)
sys.exit(1 if FAILS else 0)
