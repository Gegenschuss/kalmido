#!/usr/bin/env python3
"""2.37.0 API tests (agent C: #1150 the message search on Postgres), own container (start.sh).
 - kalmido_fold() + trigram indexes instead of the SQLite FTS5 table: "Ärger", "arger", "aerger", "ÄRGER" all find a text
   written "Ärger"; a query "Ärger" also finds texts written "arger" and "aerger"; case does not matter; a word matches its
   beginning only ("Ärg" yes, "rger" no); several words: all of them; characters that mean something in a pattern stay text
 - edit / delete of a comment and of a team chat message update the hits at once; rows written straight into the tables
 - visibility: another person's private comments and a DM between two others are never found
 - the three indexes exist, kalmido_fold() folds as described
usage: p2370_c_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

import dbx as dbxm

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


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def q(sql, args=()):
    return dbxm.connect(os.path.join(DATA, "tasks.db")).execute(sql, args).fetchall()


def comment(s, tid, body):
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": body})
    check(r.status_code in (200, 201), "setup: comment " + r.text[:100])
    return r.json().get("id")


def find(s, text, **kw):
    r = s.get(B + "/api/search/messages", params={"q": text, **kw})
    return sorted(f"{h['art']}{h['id']}" for h in r.json().get("hits", [])) if r.ok else r.status_code


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
Bo, Ca = sess("bob"), sess("carol")
W = A.post(B + "/api/lists", json={"name": "Work"}).json()["id"]
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: bob in the list")
T = A.post(B + "/api/tasks", json={"title": "Shared", "list_id": W}).json()["id"]
P = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]
TP = A.post(B + "/api/tasks", json={"title": "Mine", "list_id": P}).json()["id"]
LC = Ca.post(B + "/api/lists", json={"name": "Carol"}).json()["id"]
TC = Ca.post(B + "/api/tasks", json={"title": "Carols", "list_id": LC}).json()["id"]

C1 = comment(A, T, "Großer Ärger heute")
C2 = comment(A, T, "nur arger ohne Punkte")
C3 = comment(A, T, "aerger ausgeschrieben")
C4 = comment(A, TP, "Privater Ärger von Alice")
C5 = comment(Ca, TC, "Carols Ärger bleibt bei Carol")
C6 = comment(A, T, "Preis 100% (netto) a+b [x] und Teilwortsuche")
RDM = A.post(B + "/api/team/dm", json={"user_id": BOB}).json().get("id")
r = A.post(B + f"/api/team/rooms/{RDM}/messages", json={"body": "Ärger im Zweiergespräch"})
check(r.ok, "setup: a DM " + r.text[:100])
D1 = r.json().get("id")

# ================================================================== umlauts, case, word beginnings
ALL = sorted([f"c{C1}", f"c{C2}", f"c{C3}", f"c{C4}", f"t{D1}"])
check(find(A, "Ärger") == ALL, "Ärger finds Ärger, arger and aerger " + str(find(A, "Ärger")))
check(find(A, "aerger") == ALL, "aerger finds Ärger, arger and aerger " + str(find(A, "aerger")))
check(find(A, "arger") == sorted([f"c{C1}", f"c{C2}", f"c{C4}", f"t{D1}"]), "arger finds Ärger and arger (not aerger, as in 2.36) " + str(find(A, "arger")))
for x in ("ÄRGER", "ärger", "AERGER", "ArGeR"):
    check(find(A, x) == find(A, x.lower().replace("ä", "ae")) and find(A, x), "case does not matter: " + x)
check(find(A, "Ärg") == ALL and find(A, "aerg") == ALL, "a word matches its beginning")
check(find(A, "rger") == [] and find(A, "erger") == [], "not the middle of a word")
check(find(A, "Teilwort") == [f"c{C6}"] and find(A, "wortsuche") == [], "Teilwort: the beginning of a longer word")
check(find(A, "ärger heute") == [f"c{C1}"] and find(A, "ärger morgen") == [], "several words: all of them")
check(find(A, "100") == [f"c{C6}"] and find(A, "netto") == [f"c{C6}"], "numbers and words next to pattern characters")
for bad in ("a+b", "(netto", "[x]", "100%"):
    r = A.get(B + "/api/search/messages", params={"q": bad})
    check(r.status_code == 200, "pattern characters are no error: " + bad + " " + str(r.status_code))
check(find(A, "grosser") == [f"c{C1}"] and find(A, "Großer") == [f"c{C1}"], "ß = ss")
h = A.get(B + "/api/search/messages", params={"q": "aerger"}).json()["hits"]
x = next(i for i in h if i["id"] == C1 and i["art"] == "c")
check([x["snippet"][s:e] for s, e in x["marks"]] == ["Ärger"], "the mark covers the word as written " + str(x))

# ================================================================== visibility
check(f"c{C5}" not in find(A, "Ärger"), "alice never finds carol's comment")
check(find(Ca, "Ärger") == [f"c{C5}"], "carol: only her own, no foreign comment, no foreign DM " + str(find(Ca, "Ärger")))
check(find(Bo, "Ärger") == sorted([f"c{C1}", f"c{C2}", f"c{C3}", f"t{D1}"]), "bob: the shared list + his DM, not alice's private list " + str(find(Bo, "Ärger")))

# ================================================================== upkeep
r = A.patch(B + f"/api/comments/{C1}", json={"body": "Jetzt herrscht Ruhe"})
check(r.ok, "edit a comment " + r.text[:100])
check(f"c{C1}" not in find(A, "Ärger") and find(A, "ruhe") == [f"c{C1}"], "an edited comment: old words gone, new ones found")
r = A.patch(B + f"/api/team/messages/{D1}", json={"body": "Alles wieder gut"})
check(r.ok and f"t{D1}" not in find(A, "Ärger") and find(A, "wieder") == [f"t{D1}"], "an edited team message")
A.delete(B + f"/api/comments/{C2}")
check(f"c{C2}" not in find(A, "arger"), "a deleted comment is gone")
A.delete(B + f"/api/team/messages/{D1}")
check(find(A, "wieder") == [], "a deleted team message is gone")
q("INSERT INTO comments(task_id,user_id,body,created_at) VALUES(?,?,?,?)", (T, ALICE, "Direkt Übermut", "2026-10-11T08:00:00Z"))
check(len(find(A, "ubermut")) == 1 and len(find(A, "uebermut")) == 1, "a row written straight into the table is found")
q("UPDATE comments SET body='Direkt Gelassenheit' WHERE body='Direkt Übermut'")
check(find(A, "ubermut") == [] and len(find(A, "gelassen")) == 1, "a row changed straight in the table follows")

# ================================================================== the index
idx = sorted(r[0] for r in q("SELECT indexname FROM pg_indexes WHERE indexname LIKE 'msg_trgm_%'"))
check(idx == ["msg_trgm_agent_chat", "msg_trgm_comments", "msg_trgm_tchat_msgs"], "three trigram indexes " + str(idx))
f = q("SELECT kalmido_fold('Großer Ärger Café')")[0][0]
check(f.split("\n") == ["grosser arger cafe", "grosser aerger cafe"], "kalmido_fold: unaccent + lower, umlauts also as ae " + repr(f))

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
