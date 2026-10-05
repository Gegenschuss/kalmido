#!/usr/bin/env python3
"""2.0.6 API tests, fresh container: comments as personal notes (#315) and the roadmap's "No date" preference (#189).
 - comments no longer need collaboration: private lists, the user's own collab module off, the instance switch off
   (timeline without activity / people, no mentions, no News, no pushes, no agent events); edit + delete of own notes
 - the new module "comments": on for new users, writing refused with it off (409, reading stays), agents excepted,
   no comment News / pushes for a recipient who switched it off, /api/v1/me reports it
 - migration features_rev 9: existing users (and the setup's default modules) get "comments" once, after a restart
 - roadmap prefs accept {nd: bool}
Runs against a fresh test container (start.sh). usage: p206_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys
import time

import requests

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": "password123"})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def feats(s):
    return s.get(B + "/api/state").json()["settings"]["features"].split(",")


def news_kinds(s):
    return [x["kind"] for x in s.get(B + "/api/news").json().get("items", [])]


def ntfy_lines():
    p = os.path.join(DATA, "ntfy.log")
    return open(p).read().splitlines() if os.path.exists(p) else []


def restart():
    subprocess.run(["docker", "restart", CT], capture_output=True)
    for _ in range(60):
        try:
            if requests.get(B + "/api/health", timeout=2).ok:
                break
        except requests.RequestException:
            pass
        time.sleep(0.5)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_ntfy.py"], capture_output=True)
    time.sleep(0.7)


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
bob = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
Bo = sess("bob")
for s_ in (A, Bo):
    s_.patch(B + "/api/settings", json={"lang": "en", "news_kinds": "mention,assign,comment,unblock,share,status,complete"})

# ================================================================== the module: default on
check("comments" in feats(A) and "comments" in feats(Bo), "new users: comments module on")
tok = A.post(B + "/api/me/tokens", json={"name": "cli", "scopes": ["read", "write"]}).json()["token"]
a = requests.Session()
a.headers.update({"Authorization": "Bearer " + tok})
check(a.get(V + "/me").json()["features"].get("comments") is True, "/api/v1/me: comments true")

# ================================================================== private list: a personal note
P = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]
tp = A.post(B + "/api/tasks", json={"title": "Call the bank", "list_id": P}).json()["id"]
r = A.post(B + f"/api/tasks/{tp}/comments", json={"body": "Asked for the form"})
check(r.ok and r.json()["body"] == "Asked for the form", f"private list: comment works ({r.status_code})")
cid = r.json()["id"]
tl = A.get(B + f"/api/tasks/{tp}/timeline").json()
check(len(tl["comments"]) == 1 and tl["can_write"] is True, "private list: timeline with the note")
check(A.patch(B + f"/api/comments/{cid}", json={"body": "Asked for the IBAN form"}).ok, "own note: edit")
st = [t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == tp][0]
check(st.get("comment_count") == 1, f"comment_count in the state: {st.get('comment_count')}")

# ================================================================== collaboration off in my own settings: still notes
A.patch(B + "/api/settings", json={"features": ",".join(f for f in feats(A) if f != "collab")})
r = A.post(B + f"/api/tasks/{tp}/comments", json={"body": "second note"})
check(r.ok, f"collab module off: comment works ({r.status_code})")
A.patch(B + "/api/settings", json={"features": feats(A) and ",".join(feats(A) + ["collab"])})
check("collab" in feats(A), "collab back on")

# ================================================================== the Comments module off: writing refused, reading stays
A.patch(B + "/api/settings", json={"features": ",".join(f for f in feats(A) if f != "comments")})
r = A.post(B + f"/api/tasks/{tp}/comments", json={"body": "x"})
check(r.status_code == 409 and "Comments are turned off" in r.json().get("error", ""), f"comments off: create 409 ({r.status_code} {r.text[:80]})")
check(A.patch(B + f"/api/comments/{cid}", json={"body": "y"}).status_code == 409, "comments off: edit 409")
check(A.get(B + f"/api/tasks/{tp}/timeline").ok, "comments off: reading stays")
check(a.post(V + f"/tasks/{tp}/comments", json={"body": "x"}).status_code == 409 and a.get(V + f"/tasks/{tp}/comments").ok, "API v1: create 409, list works")
check(a.get(V + "/me").json()["features"]["comments"] is False, "/api/v1/me: comments false")
A.patch(B + "/api/settings", json={"features": ",".join(feats(A) + ["comments"])})

# ================================================================== shared list: recipients with comments off get nothing
S = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]
A.put(B + f"/api/lists/{S}/members", json={"user_id": bob, "role": "edit"})
ts = A.post(B + "/api/tasks", json={"title": "Plan", "list_id": S, "assignee_id": bob}).json()["id"]
Bo.post(B + "/api/news/read", json={"all": True})
r = A.post(B + f"/api/tasks/{ts}/comments", json={"body": "Ping <@%d>" % bob})
check(r.ok and r.json()["mentions"] == [bob], "shared list, collaboration on: mention kept")
time.sleep(0.5)
check("mention" in news_kinds(Bo), f"bob gets the mention in News: {news_kinds(Bo)}")
tl = Bo.get(B + f"/api/tasks/{ts}/timeline").json()
check(tl["activity"] and any(p["id"] == 1 for p in tl["people"]), "shared list: activity + people for the mention picker")
Bo.patch(B + "/api/settings", json={"features": ",".join(f for f in feats(Bo) if f != "comments")})
n0 = dbx("SELECT COUNT(*) FROM notifications WHERE user_id=?", (bob,))[0][0]
open(os.path.join(DATA, "ntfy.log"), "w").close()
time.sleep(3.2)  # past TASKS_PUSH_GAP of the test container
r = A.post(B + f"/api/tasks/{ts}/comments", json={"body": "Again <@%d>" % bob})
time.sleep(1.2)
check(r.ok and dbx("SELECT COUNT(*) FROM notifications WHERE user_id=?", (bob,))[0][0] == n0, "bob switched comments off: no comment / mention News")
check(not [x for x in ntfy_lines() if "Again" in x], "bob switched comments off: no push")
Bo.patch(B + "/api/settings", json={"features": ",".join(feats(Bo) + ["comments"])})

# ================================================================== the instance switch off: notes only
A.patch(B + "/api/admin/settings", json={"collab_all": False})
tl = A.get(B + f"/api/tasks/{ts}/timeline")
check(tl.ok and tl.json()["activity"] == [] and tl.json()["people"] == [], f"collab_all off: timeline without activity / people ({tl.status_code})")
n0 = dbx("SELECT COUNT(*) FROM notifications")[0][0]
r = A.post(B + f"/api/tasks/{ts}/comments", json={"body": "Note <@%d>" % bob})
check(r.ok and r.json()["mentions"] == [], f"collab_all off: comment works, no mention ({r.status_code})")
time.sleep(0.8)
check(dbx("SELECT COUNT(*) FROM notifications")[0][0] == n0, "collab_all off: no News")
check(A.delete(B + f"/api/comments/{r.json()['id']}").ok, "collab_all off: own note deleted")
check(A.post(B + f"/api/comments/{cid}/reactions", json={"emoji": "up"}).status_code == 403, "collab_all off: reactions still need collaboration")
A.patch(B + "/api/admin/settings", json={"collab_all": True})

# ================================================================== roadmap prefs: nd
r = A.patch(B + "/api/settings", json={"roadmap": '{"v":"timeline","nd":false}'})
check(r.ok and '"nd":false' in A.get(B + "/api/state").json()["settings"]["roadmap"], "roadmap prefs: nd stored")
check(A.patch(B + "/api/settings", json={"roadmap": '{"nd":"x"}'}).status_code == 400, "roadmap prefs: nd must be a boolean")

# ================================================================== migration features_rev 9 (after a restart)
dbx("UPDATE user_settings SET value='cal,collab,time' WHERE user_id=? AND key='features'", (bob,))
dbx("UPDATE user_settings SET value='8' WHERE user_id=? AND key='features_rev'", (bob,))
dbx("INSERT OR REPLACE INTO settings(key,value) VALUES('default_features','cal,kanban,collab,time')")
dbx("DELETE FROM settings WHERE key='migr_feat9'")
restart()
Bo = sess("bob")
check(feats(Bo) == ["cal", "collab", "time", "comments", "events", "contacts"], f"migration: comments added once (2.21: events + contacts too), the rest kept: {feats(Bo)}")
check(dbx("SELECT value FROM user_settings WHERE user_id=? AND key='features_rev'", (bob,))[0][0] == "10", "features_rev 10")
check(dbx("SELECT value FROM settings WHERE key='default_features'")[0][0] == "cal,kanban,collab,time,comments", "setup default modules get comments too")
Bo.patch(B + "/api/settings", json={"features": "cal,collab,time"})
restart()
check(sess("bob").get(B + "/api/state").json()["settings"]["features"] == "cal,collab,time", "migration runs once: switched off stays off")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
