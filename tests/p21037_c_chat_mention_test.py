#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1037.0 C API tests (#5800): an @mention in a team chat channel, group or project conversation is an entry "For you" and
counts at the bell. Own container (start.sh). Invented names only, addresses @example.com.
freelancer-matrix: team
 - a mention in a channel: one News item kind chatmention, to_me, with the room's name and the message's text; the bell's
   number (unread_me) and the app icon's number (badge_count) rise by one; who is not mentioned gets nothing, a plain message
   makes no entry; filter=mentions and filter=me show it
 - two mentions in the same room = one item with count 2 (both ids); read in the chat (POST read) = the item read, the bell back
 - a muted channel: a plain message makes nothing, a mention counts (only the mention: dm_unread stays)
 - a group: not muted, its mention stays out of the feed (the group's own unread messages count at the bell, no double count);
   muted, only the mention counts
 - a project's conversation: the item names the project; an encrypted message gives the item without words (sealed)
 - a thread answer: read in the main conversation leaves it, read in the thread reads it
 - a deleted message takes its item along; a person taken out of the project loses it
 - "All read" reads the mention items; the unread direct message stays (dm_unread)
 - a direct message makes no mention item (its own row counts)
 - a person without an organisation: a mention in the chat of her own project shared with another freelancer
usage: p21037_c_chat_mention_test.py <datadir>"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, sess, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

kt.fresh(prefix="P21037C")
kt.docker_logs_on_first_fail()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments", "collab"]})
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ALICE = kt.me_id(A)
uid = {}
for u in ("bob", "nora"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
BOB, NORA = uid["bob"], uid["nora"]
Bo, No = sess("bob"), sess("nora")
for s in (Bo, No):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})


def news(s, f=None):
    r = s.get(B + "/api/news" + (f"?filter={f}" if f else ""))
    check(r.ok, f"GET /api/news {r.status_code}")
    return r.json() if r.ok else {"items": [], "unread_me": 0, "unread": 0}


def cm(s, room=None, f=None):
    return [x for x in news(s, f)["items"] if x["kind"] == "chatmention" and (room is None or x["data"].get("room") == room)]


def team(s):
    return s.get(B + "/api/state").json()["team"]


def say(s, rid, text, **kw):
    r = s.post(B + f"/api/team/rooms/{rid}/messages", json={"body": text, **kw})
    check(r.status_code == 201, f"message in room {rid}: {r.status_code} {r.text[:160]}")
    return r.json().get("id") if r.ok else None


def badge(u):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        f"import app\nfrom kalmido.notify.push import badge_count\nprint('OUT', badge_count({u}))"],
                       capture_output=True, text=True, timeout=200)
    for line in r.stdout.splitlines():
        if line.startswith("OUT "):
            return int(line[4:])
    check(False, "badge_count ran in the app: " + r.stdout[-300:] + r.stderr[-800:])
    return -1


# ================================================================ a channel
r = A.post(B + "/api/team/channels", json={"name": "Studio", "org_id": ORG, "open": False, "members": [BOB, NORA]})
check(r.status_code == 201, "setup: alice's channel " + r.text[:200])
CH = r.json()["id"]
for s in (Bo, No):
    s.post(B + f"/api/team/rooms/{CH}/read", json={})
u0, b0 = news(Bo)["unread_me"], badge(BOB)
say(A, CH, "Shoot moves to Friday")
check(not cm(Bo) and news(Bo)["unread_me"] == u0, "#5800: a plain channel message makes no entry and does not count")
M1 = say(A, CH, f"<@{BOB}> can you bring the lights?")
items = cm(Bo, CH)
check(len(items) == 1 and items[0]["to_me"] and not items[0]["read"] and items[0]["actor_id"] == ALICE,
      f"#5800: the mention is one unread item 'For you' {items}")
it = items[0] if items else {"data": {}, "excerpt": ""}
check(it["data"].get("room_name") == "Studio" and it["data"].get("msg") == M1 and "lights" in it.get("excerpt", ""),
      f"#5800: the item names the room and carries the message's text {it}")
check(news(Bo)["unread_me"] == u0 + 1, f"#5800: the bell's number rises by one ({u0} -> {news(Bo)['unread_me']})")
check(badge(BOB) == b0 + 1, f"#5800: the app icon's number (badge_count) rises by one too ({b0} -> {badge(BOB)})")
check(not cm(No), "#5800: nora (not mentioned) gets no entry")
check(cm(Bo, CH, "mentions") and cm(Bo, CH, "me"), "#5800: the filters 'mentions' and 'me' show it")
M2 = say(No, CH, f"Also <@{BOB}>: the tripod")
items = cm(Bo, CH)
check(len(items) == 1 and items[0]["count"] == 2 and len(items[0]["ids"]) == 2, f"#5800: two mentions in one room = one item with 2 {items}")
check(items and items[0]["data"].get("msg") == M1 and set(items[0]["actors"]) == {ALICE, NORA},
      f"#5800: it opens at the first unread mention and names both people {items}")
sig0 = news(Bo)["sig"]
check(Bo.post(B + f"/api/team/rooms/{CH}/read", json={}).ok, "bob reads the channel in the chat")
items = cm(Bo, CH)
check(items and all(x["read"] for x in items), f"#5800: read in the chat = the item read (no second tick) {items}")
check(news(Bo)["unread_me"] == u0 and news(Bo)["sig"] != sig0, "#5800: the bell is back, the News marker moved (other devices reload)")

# ---- a muted channel: only the mention counts
check(Bo.post(B + f"/api/team/rooms/{CH}/read", json={"muted": True}).ok, "bob mutes the channel")
d0, u1 = team(Bo)["dm_unread"], news(Bo)["unread_me"]
say(A, CH, "Plain news in the muted channel")
check(news(Bo)["unread_me"] == u1 and team(Bo)["dm_unread"] == d0, "#5800: a plain message in a muted channel counts nothing")
say(A, CH, f"<@{BOB}> one thing")
check(news(Bo)["unread_me"] == u1 + 1 and team(Bo)["dm_unread"] == d0, "#5800: in a muted channel the mention counts, only it")
Bo.post(B + f"/api/team/rooms/{CH}/read", json={"muted": False})
Bo.post(B + f"/api/team/rooms/{CH}/read", json={})

# ================================================================ a group
L = A.post(B + "/api/lists", json={"name": "Spring campaign", "org_id": ORG, "kind": "project"}).json()["id"]
for x in (BOB, NORA):
    check(A.put(B + f"/api/lists/{L}/members", json={"user_id": x, "role": "edit"}).ok, f"setup: {x} in the project")
r = A.post(B + "/api/team/groups", json={"members": [BOB, NORA], "name": "Lunch"})
check(r.status_code == 201, "setup: a group " + r.text[:200])
GR = r.json().get("id")
r = A.post(B + "/api/team/dm", json={"user_id": BOB})  # opened while they share the project (used at the end)
check(r.ok, "setup: alice's direct conversation with bob " + r.text[:200])
DM = r.json().get("id") if r.ok else None
Bo.post(B + f"/api/team/rooms/{GR}/read", json={})
d0, u1 = team(Bo)["dm_unread"], news(Bo)["unread_me"]
say(A, GR, f"<@{BOB}> noon?")
check(team(Bo)["dm_unread"] == d0 + 1 and news(Bo)["unread_me"] == u1 and not cm(Bo, GR),
      "#5800: a group (not muted) counts its message once, the mention stays in the group's row (no double count)")
check(Bo.post(B + f"/api/team/rooms/{GR}/read", json={"muted": True}).ok, "bob mutes the group")
check(team(Bo)["dm_unread"] == d0 and news(Bo)["unread_me"] == u1 + 1 and len(cm(Bo, GR)) == 1,
      "#5800: a muted group: only the mention counts at the bell")
Bo.post(B + f"/api/team/rooms/{GR}/read", json={})
check(news(Bo)["unread_me"] == u1, "#5800: read in the group = the mention read")

# ================================================================ a project's conversation
rooms = Bo.get(B + "/api/team").json().get("rooms") or []
LR = next((x["id"] for x in rooms if x.get("list_id") == L), None)
check(LR, "setup: the project's conversation " + str(rooms)[:300])
Bo.post(B + f"/api/team/rooms/{LR}/read", json={})
M3 = say(A, LR, f"<@{BOB}> the brief is in")
items = cm(Bo, LR)
check(len(items) == 1 and items[0]["data"].get("room_name") == "Spring campaign" and items[0]["list_id"] == L,
      f"#5800: the item names the project {items}")
# an encrypted message (as the browser of a locked project stores it): the item has no words of it
kt.dbx("UPDATE tchat_msgs SET enc='msg', body='v2:c2VjcmV0' WHERE id=?", (M3,))
items = cm(Bo, LR)
check(len(items) == 1 and items[0].get("sealed") and not items[0].get("excerpt") and "c2VjcmV0" not in json.dumps(items[0]),
      f"#5800: an encrypted message: the item without its text {items}")

# ---- a thread answer
ROOT = say(A, CH, "Thread about the set")
Bo.post(B + f"/api/team/rooms/{CH}/read", json={})
say(A, CH, f"<@{BOB}> which wall?", thread_of=ROOT)
items = [x for x in cm(Bo, CH) if not x["read"]]
check(len(items) == 1 and items[0]["data"].get("thread") == ROOT, f"#5800: a mention in a thread names its thread {items}")
Bo.post(B + f"/api/team/rooms/{CH}/read", json={})
check([x for x in cm(Bo, CH) if not x["read"]], "#5800: reading the main conversation leaves the thread's mention")
Bo.post(B + f"/api/team/rooms/{CH}/read", json={"thread": ROOT})
check(not [x for x in cm(Bo, CH) if not x["read"]], "#5800: read in the thread = its mention read")

# ---- a deleted message, a person taken out
M4 = say(A, CH, f"<@{BOB}> typo here")
check(any(not x["read"] for x in cm(Bo, CH)), "setup: the mention is there")
check(A.delete(B + f"/api/team/messages/{M4}").ok, "alice deletes her message")
check(not any(not x["read"] for x in cm(Bo, CH)), "#5800: a deleted message takes its item along")
# review (job/4208): taking a mention out by an edit and putting it back makes no second entry for the same message
M5 = say(A, CH, f"<@{BOB}> the cables")
for body in ("the cables", f"<@{BOB}> the cables", "the cables", f"<@{BOB}> the cables!"):
    check(A.patch(B + f"/api/team/messages/{M5}", json={"body": body}).ok, "alice edits her message")
n5 = kt.dbx("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='chatmention' AND data->>'msg' = ?", (BOB, str(M5)))[0][0]
check(n5 == 1, f"#5800 review: edits do not multiply the entry of one message ({n5})")
Bo.post(B + f"/api/team/rooms/{CH}/read", json={})
check(cm(Bo, LR), "setup: bob has the project's mention")
check(A.delete(B + f"/api/lists/{L}/members/{BOB}").ok, "alice takes bob out of the project")
check(not cm(Bo, LR), "#5800: out of the project = the project's mention is gone (no names, no text)")

# ---- "All read" and a direct message
say(A, DM, f"<@{BOB}> quick question")
check(not cm(Bo, DM), "#5800: a direct message makes no mention item (its own row counts)")
say(A, CH, f"<@{BOB}> last one")
d0 = team(Bo)["dm_unread"]
check(d0 >= 1 and any(not x["read"] for x in cm(Bo, CH)), "setup: an unread direct message and an unread mention")
check(Bo.post(B + "/api/news/read", json={"all": True}).ok, "bob: All read")
check(not any(not x["read"] for x in cm(Bo)) and news(Bo)["unread_me"] == 0, "#5800: All read reads the mention items")
check(team(Bo)["dm_unread"] == d0, "#5800: the direct message stays until it is read in the chat")

# ================================================================ a person without an organisation (freelancer-matrix: team)
FID, Fr = freelancer(B, A)
FIO, Fi = freelancer(B, A, "fiona")
kt.dbx("INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES(?,?,?,?)", ("Freelance pool", "", "2026-11-12T08:00:00", ALICE))
GID = kt.dbx("SELECT id FROM groups WHERE name=?", ("Freelance pool",))[0][0]
for x in (FID, FIO):
    kt.dbx("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (GID, x, "2026-11-12T08:00:00"))
FL = Fr.post(B + "/api/lists", json={"name": "Own studio"}).json()["id"]
check(Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FIO, "role": "edit"}).ok, "freelancer: the own project shared")
FR = until(lambda: next((x["id"] for x in (Fi.get(B + "/api/team").json().get("rooms") or []) if x.get("list_id") == FL), None), 5)
check(FR, "freelancer: the project's conversation")
fu = news(Fi)["unread_me"]
say(Fr, FR, f"<@{FIO}> draft is ready")
items = cm(Fi, FR)
check(len(items) == 1 and items[0]["to_me"] and items[0]["data"].get("room_name") == "Own studio" and news(Fi)["unread_me"] == fu + 1,
      f"#5800 freelancer: fiona's entry 'For you', counted at the bell {items}")
Fi.post(B + f"/api/team/rooms/{FR}/read", json={})
check(news(Fi)["unread_me"] == fu, "#5800 freelancer: read in the chat = read")

sys.exit(kt.done("p21037_c_chat_mention"))
