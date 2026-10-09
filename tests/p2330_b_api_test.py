#!/usr/bin/env python3
"""2.33.0 API tests (agent B: #1080 search in conversations), own container (start.sh).
 - one FTS5 index over task comments, team chat (channels + direct messages) and agent chats: case, accents and ä / ae do
   not matter ("Ärger" = "arger" = "AERGER", "Straße" = "strasse", "Café" = "cafe"), words match their beginnings
 - kept current by triggers: new, edited and (soft) deleted messages; rows written straight into the tables (as an older
   server would after a rollback) are found too; a database without the index (a backup from before 2.33) gets it built at
   the start, a drifted index is rebuilt
 - visibility: comments only of tasks the person sees (list role; not another organisation's), team chat only rooms the
   person is in (channel: list members; DM: the two), agent chats only the person's own (with agents they reach); agents
   (token): comments + channel of the lists shared with them and their own chats, never DMs, never another agent's chats
 - filters art / sender / room / agent / task (a foreign id finds nothing), paging (limit + cursor / offset), the snippet is
   plain text with marks (mentions as @name; a mention's id is not a hit; HTML stays text), 400 on bad input
 - GET /api/v1/search?scope=messages (people + agents), GET /api/search/messages (web client), OpenAPI
usage: p2330_b_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys

import requests

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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def restart():
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
                   env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces"))


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL, DAVE = uid["bob"], uid["carol"], uid["dave"]
restart()
A, Bo, Ca, Da = sess("alice"), sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
BETA = r.json().get("id") if r.ok else None
dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG, CAROL), write=True)
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (ORG, ALICE), write=True)
check(BETA is not None, "setup: organisation Beta for carol " + r.text[:100])


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": name, "display_name": name.title()})
    aid = r.json()["id"]
    check(A.patch(B + f"/api/admin/agents/{aid}", json={"org_id": ORG}).ok, "setup: a team agent of the organisation")
    dbx("INSERT OR IGNORE INTO org_members(org_id,user_id,role) VALUES(?,?,'member')", (ORG, aid), write=True)
    return aid, {"Authorization": "Bearer " + r.json()["token"]}


CL, CLH = agent("claude")
OT, OTH = agent("otto")
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
for who in (CL, BOB):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": "edit"}).ok, f"setup: {who} in the list")
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": DAVE, "role": "participant"}).ok, "setup: dave a participant")
W2 = A.post(B + "/api/lists", json={"name": "Otto list", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{W2}/members", json={"user_id": OT, "role": "edit"})
PRIV = A.post(B + "/api/lists", json={"name": "Private", "org_id": ORG}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Shared task", "list_id": W}).json()["id"]
TD = A.post(B + "/api/tasks", json={"title": "Dave's task", "list_id": W, "assignee_id": DAVE}).json()["id"]
TP = A.post(B + "/api/tasks", json={"title": "Private task", "list_id": PRIV}).json()["id"]
LB = Ca.post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json().get("id")
TB = Ca.post(B + "/api/tasks", json={"title": "Beta task", "list_id": LB}).json().get("id")


def comment(s, tid, body):
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": body})
    check(r.status_code in (200, 201), "setup: comment " + r.text[:100])
    return r.json().get("id")


def find(s, q, **kw):
    r = s.get(B + "/api/search/messages", params={"q": q, **kw})
    return r.json().get("hits", []) if r.ok else r.status_code


def vfind(h, q, **kw):
    r = requests.get(V + "/search", headers=h, params={"scope": "messages", "q": q, **kw})
    return r.json().get("data", []) if r.ok else r.status_code


def keys(hits):
    return sorted(f"{h['art']}{h['id']}" for h in hits) if isinstance(hits, list) else hits


C1 = comment(A, T, f"Großer Ärger mit der Straße, frag <@{BOB}> nach Nummer 4711")
C2 = comment(A, TP, "Ärger im privaten Kreis")
C3 = comment(A, TD, "Ärger bei Dave")
C4 = comment(Ca, TB, "Ärger in Beta")
check(dbx("SELECT COUNT(*) FROM tasks WHERE id=? AND assignee_id=?", (TD, DAVE))[0][0] == 1, "setup: dave's task is assigned to him")
rooms = A.get(B + "/api/team").json()["rooms"]
RW = next(x["id"] for x in rooms if x["kind"] == "list" and x["list_id"] == W)
RDM = A.post(B + "/api/team/dm", json={"user_id": BOB}).json()["id"]
T1 = A.post(B + f"/api/team/rooms/{RW}/messages", json={"body": "Das **Ärgernis** im Café <b>fett</b>"}).json()["id"]
T2 = A.post(B + f"/api/team/rooms/{RDM}/messages", json={"body": "Ärger unter vier Augen"}).json()["id"]
r = A.post(B + f"/api/agents/{CL}/chat", json={"body": "Ärger mit dem Build"})
check(r.status_code == 201, "setup: alice writes to claude " + r.text[:100])
A1 = r.json().get("id")
r = requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": "Kein Ärger mehr, der Build ist grün"})
A2 = r.json().get("id") if r.ok else None
check(r.ok and A2, "setup: claude answers " + r.text[:100])

# ================================================================== matching
hits = find(A, "arger")
check(keys(hits) == sorted([f"c{C1}", f"c{C2}", f"c{C3}", f"t{T1}", f"t{T2}", f"a{A1}", f"a{A2}"]), "alice finds every place she reads " + str(keys(hits)))
for q in ("ÄRGER", "aerger", "Ärg", "ärger"):
    check(keys(find(A, q)) == keys(hits), f"case, accents and ä = ae do not matter: {q}")
check(keys(find(A, "strasse")) == [f"c{C1}"] and keys(find(A, "Straße")) == [f"c{C1}"], "ß = ss")
check(keys(find(A, "cafe")) == [f"t{T1}"], "é = e")
CUE = comment(A, T, "Die Spuelmaschine ist kaputt")
check(keys(find(A, "Spülmaschine")) == [f"c{CUE}"] and keys(find(A, "spulmaschine")) == [], "ü in the query also finds a text written with ue")
check(keys(find(A, "ärger build")) == sorted([f"a{A1}", f"a{A2}"]), "several words: all of them")
check(find(A, "rger") == [], "words match their beginnings only")
h = next(x for x in hits if x["art"] == "c" and x["id"] == C1)
sn, mk = h["snippet"], h["marks"]
check("@Bob" in sn and "<@" not in sn and [sn[s:e] for s, e in mk] == ["Ärger"], "snippet: plain text, mentions as @name, marks " + repr((sn, mk)))
check(h["chat_type"] == "task" and h["task_id"] == T and h["list_id"] == W and h["chat_name"] == "Shared task" and h["sender"]["id"] == ALICE
      and h["sender"]["name"] == "Alice" and h["created_at"], "comment hit: kind, task, list, sender " + str(h)[:200])
check(find(A, str(BOB)) == [], "the id inside a mention is not a hit")
check(keys(find(A, "4711")) == [f"c{C1}"], "numbers are words")
t = next(x for x in hits if x["art"] == "t" and x["id"] == T1)
check(t["chat_type"] == "list" and t["room_id"] == RW and "<b>fett</b>" in t["snippet"] and "**" not in t["snippet"],
      "team hit: channel, HTML stays text, Markdown markers out " + str(t)[:200])
d = next(x for x in hits if x["art"] == "t" and x["id"] == T2)
check(d["chat_type"] == "dm" and d["chat_name"] == "Bob", "DM hit: chat type dm, named after the other person " + str(d)[:160])
a = next(x for x in hits if x["art"] == "a" and x["id"] == A2)
check(a["chat_type"] == "agent" and a["agent_id"] == CL and a["sender"]["agent"] is True and a["chat_name"] == "Claude", "agent hit " + str(a)[:200])
check([x["created_at"] for x in hits] == sorted([x["created_at"] for x in hits], reverse=True), "newest first")
long = "Anfang " + "füll " * 80 + "Zielwort hier " + "füll " * 80
comment(A, T, long)
z = find(A, "zielwort")
check(len(z) == 1 and z[0]["snippet"].startswith("…") and z[0]["snippet"].endswith("…") and len(z[0]["snippet"]) < 200
      and [z[0]["snippet"][s:e] for s, e in z[0]["marks"]] == ["Zielwort"], "a long message: a cut snippet around the hit " + repr(z[0]["snippet"] if z else z))

# ================================================================== visibility
check(keys(find(Bo, "arger")) == sorted([f"c{C1}", f"c{C3}", f"t{T1}", f"t{T2}"]), "bob: the shared list's comments, its channel, his DM; no private list, no agent chat of alice " + str(keys(find(Bo, "arger"))))
check(keys(find(Ca, "arger")) == [f"c{C4}"], "carol (other organisation): only her own " + str(keys(find(Ca, "arger"))))
check(keys(find(Da, "arger")) == [f"c{C3}"], "dave (participant): only the comments of his own task, no channel " + str(keys(find(Da, "arger"))))
check(keys(vfind(CLH, "arger")) == sorted([f"c{C1}", f"c{C3}", f"t{T1}", f"a{A1}", f"a{A2}"]), "claude: shared list + its channel + its own chat, no DM, no private list " + str(keys(vfind(CLH, "arger"))))
check(vfind(OTH, "arger") == [], "otto (another agent): nothing of claude's or the list it is not in " + str(vfind(OTH, "arger")))
r = Bo.get(B + f"/api/agents/{CL}/chat")
if r.status_code == 200:
    Bo.post(B + f"/api/agents/{CL}/chat", json={"body": "Bobs Ärger"})
    check(not any(x["art"] == "a" and x["user_id"] == ALICE for x in find(Bo, "arger")), "bob never sees alice's agent chat")
# filters with foreign ids find nothing
check(find(Ca, "arger", room=RW) == [] and find(Ca, "arger", task=T) == [] and find(Ca, "arger", agent=CL) == [], "foreign room / task / agent: nothing")
check(find(Bo, "arger", task=TP) == [], "bob: the private task's comments stay hidden with task=")

# ================================================================== filters + paging
check(keys(find(A, "arger", art="c")) == sorted([f"c{C1}", f"c{C2}", f"c{C3}"]), "art=c")
check(keys(find(A, "arger", art="t,a")) == sorted([f"t{T1}", f"t{T2}", f"a{A1}", f"a{A2}"]), "art=t,a")
check(keys(find(A, "arger", room=RDM)) == [f"t{T2}"], "room=")
check(keys(find(A, "arger", agent=CL)) == sorted([f"a{A1}", f"a{A2}"]), "agent=")
check(keys(find(A, "arger", sender=CL)) == [f"a{A2}"], "sender= (an agent's answers)")
check(keys(find(A, "arger", task=TD)) == [f"c{C3}"], "task=")
check(keys(vfind(CLH, "arger", agent=ALICE)) == sorted([f"a{A1}", f"a{A2}"]), "an agent: agent= names the person")
r = A.get(B + "/api/search/messages", params={"q": "arger", "limit": 3})
j = r.json()
check(len(j["hits"]) == 3 and j["total"] == 7 and j["next_offset"] == 3, "web paging " + str({k: j[k] for k in ("total", "next_offset")}))
r = requests.get(V + "/search", headers=CLH, params={"scope": "messages", "q": "arger", "limit": 2})
seen, pages = [], 0
while True:
    pages += 1
    j = r.json()
    seen += keys(j["data"])
    if not j.get("next_cursor") or pages > 5:
        break
    r = requests.get(V + "/search", headers=CLH, params={"scope": "messages", "q": "arger", "limit": 2, "cursor": j["next_cursor"]})
check(sorted(seen) == keys(vfind(CLH, "arger")) and pages == 3, f"v1 cursor pages ({pages}) " + str(seen))
for bad in ({"q": ""}, {"q": "x" * 201}, {"q": "%%%"}, {"q": "a", "art": "x"}, {"q": "a", "room": "abc"}):
    check(A.get(B + "/api/search/messages", params=bad).status_code == 400, "400: " + str(bad)[:40])
check(requests.get(V + "/search", headers=CLH, params={"scope": "messages", "q": "a", "foo": 1}).status_code == 400, "v1: unknown parameter 400")
check(requests.get(V + "/search", headers=CLH, params={"scope": "nope", "q": "a"}).status_code == 400, "v1: unknown scope 400")
r = requests.get(V + "/search", headers=CLH, params={"q": "Shared"})
check(r.ok and any(x["id"] == T for x in r.json()["data"]), "v1: the task search is unchanged")
spec = requests.get(V + "/openapi.json", headers=CLH).json()
ps = [p["name"] for p in spec["paths"]["/search"]["get"]["parameters"]]
check("MessageHit" in spec["components"]["schemas"] and "scope" in ps and "art" in ps, "OpenAPI: scope + MessageHit " + str(ps))

# ================================================================== upkeep: edit, delete, raw rows, rebuild
r = A.patch(B + f"/api/team/messages/{T1}", json={"body": "Jetzt nur noch Freude"})
check(r.ok and keys(find(A, "Ärgernis")) == [] and keys(find(A, "freude")) == [f"t{T1}"], "an edited message: old words gone, new ones found")
A.delete(B + f"/api/comments/{C2}")
check(f"c{C2}" not in keys(find(A, "arger")), "a deleted comment is gone")
A.delete(B + f"/api/team/messages/{T2}")
check(f"t{T2}" not in keys(find(A, "arger")), "a deleted team message is gone")
# an older server (rollback) writes the tables directly: the triggers keep the index right, nothing fails
dbx("INSERT INTO comments(task_id,user_id,body,created_at) VALUES(?,?,?,?)", (T, ALICE, "Rückweg ohne Ärger", "2026-10-09T08:00:00Z"), write=True)
dbx("INSERT INTO tchat_msgs(room_id,user_id,body,created_at) VALUES(?,?,?,?)", (RW, BOB, "Rückweg im Kanal", "2026-10-09T08:00:01Z"), write=True)
check(len(find(A, "ruckweg")) == 2 and len(find(Bo, "rueckweg")) == 2, "rows written straight into the tables are found")
dbx("DELETE FROM comments WHERE body='Rückweg ohne Ärger'", write=True)
check(len(find(A, "ruckweg")) == 1, "rows deleted straight from the tables are gone")
dbx("DELETE FROM agent_chat WHERE id=?", (A1,), write=True)
check(f"a{A1}" not in keys(find(A, "arger")), "a trimmed agent chat message is gone")
before = keys(find(A, "arger"))
# a database without the index (a backup from before 2.33): built at the start
c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
for (n,) in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'msg_fts_%'").fetchall():
    c.execute(f"DROP TRIGGER {n}")
c.execute("DROP TABLE msg_fts")
c.commit()
c.execute("INSERT INTO comments(task_id,user_id,body,created_at) VALUES(?,?,?,?)", (T, ALICE, "Altbestand Ärger", "2026-10-09T08:00:02Z"))
c.commit()
c.close()
restart()
A = sess("alice")
after = keys(find(A, "arger"))
check(len(after) == len(before) + 1 and set(before) <= set(after), "a database without the index gets it built at the start " + str((before, after)))
# a drifted index (e.g. a row lost) is rebuilt at the start
dbx("DELETE FROM msg_fts WHERE rowid=?", (C1 * 4 + 1,), write=True)
check(f"c{C1}" not in keys(find(A, "arger")), "setup: a lost index row")
restart()
A = sess("alice")
check(keys(find(A, "arger")) == after, "a drifted index is rebuilt at the start")
check(len(dbx("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'msg_fts_%'")) == 9, "nine triggers (three tables x insert / update / delete)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
