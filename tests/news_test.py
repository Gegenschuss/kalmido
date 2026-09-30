#!/usr/bin/env python3
"""News feed API tests against the TEST container (:3048, fresh DB in DATA)."""
import json, os, sys, time, sqlite3, subprocess
import requests
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048"); DATA = sys.argv[1]; H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
def check(c, what):
    if c: OKS[0] += 1
    else: FAILS.append(what); print("FAIL:", what)
def sess(u=None):
    s = requests.Session(); s.headers.update(H)
    if u: assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok
    return s
def pushes():
    try: return [json.loads(l) for l in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if l.strip()]
    except FileNotFoundError: return []
def clear(): open(os.path.join(DATA, "ntfy.log"), "w").close()
def news(s, f=None): return s.get(B + "/api/news", params={"filter": f} if f else None).json()
def kinds(s): return [(x["kind"], x["count"]) for x in news(s)["items"]]
def db(): return sqlite3.connect(os.path.join(DATA, "tasks.db"))

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice"); A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
ids = {"alice": 1}
for u, n, topic in (("bob", "Bob", "t-bob"), ("carol", "Carol", "t-carol"), ("dave", "Dave", "t-dave"), ("eve", "Eve", "t-eve"), ("frank", "Frank", "")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "ntfy_topic": topic}); assert r.ok, r.text
    ids[u] = r.json()["id"]
A.patch(B + f"/api/users/{ids['frank']}", json={"ntfy_topic": ""})
# 1.9.0: "completed by others" is off by default (setting news_kinds); this suite checks those items too
A.patch(B + "/api/settings", json={"news_kinds": "mention,assign,comment,unblock,share,status,complete"})
Bb, C, D, E, F = (sess(u) for u in ("bob", "carol", "dave", "eve", "frank"))
st = E.get(B + "/api/state").json()
E.patch(B + "/api/settings", json={"features": ",".join(x for x in st["settings"]["features"].split(",") if x != "collab")})
L = A.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
for u, role in (("bob", "edit"), ("carol", "view"), ("eve", "edit"), ("frank", "edit")):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ids[u], "role": role}).ok
check(kinds(Bb) == [("share", 1)] and news(Bb)["items"][0]["data"]["role"] == "edit", f"share item for bob: {kinds(Bb)}")
check(kinds(C) == [("share", 1)] and news(C)["items"][0]["data"]["role"] == "view", "share item for carol (view)")
check(kinds(F) == [("share", 1)], "frank (no ntfy topic) still gets feed items")
check(kinds(E) == [] and news(E)["enabled"] is False, "eve (collab off): no items, enabled false")
check(kinds(A) == [], "alice: nothing for own actions")
clear()
# assign on create
ST = A.post(B + "/api/tasks", json={"title": "Shared task", "list_id": L, "assignee_id": ids["bob"]}).json()["id"]
it = news(Bb)["items"][0]
check(it["kind"] == "assign" and it["task_id"] == ST and it["task_title"] == "Shared task" and it["list_id"] == L and it["actor_id"] == 1 and not it["read"], f"assign item: {it}")
check(news(Bb)["users"].get("1") == "Alice", "users map carries the actor name")
time.sleep(0.5); check([p["topic"] for p in pushes()] == ["t-bob"], "assign push to bob only (same recipients)")
time.sleep(3.2); clear()
# comment by bob -> alice (creator)
Bb.post(B + f"/api/tasks/{ST}/comments", json={"body": "First from Bob"})
check(kinds(A) == [("comment", 1)] and news(A)["items"][0]["excerpt"] == "First from Bob", f"alice: comment item {kinds(A)}")
check(kinds(Bb)[0] == ("assign", 1), "bob: no item for his own comment")
# mentions: carol (view member), frank (no topic), dave (not a member -> cleaned), eve (collab off)
A.post(B + f"/api/tasks/{ST}/comments", json={"body": f"<@{ids['carol']}> <@{ids['frank']}> <@{ids['dave']}> <@{ids['eve']}> please look"})
check(kinds(C)[0] == ("mention", 1), f"carol: mention {kinds(C)}")
fi = news(F)["items"][0]
check(fi["kind"] == "mention" and f"<@{ids['frank']}>" in fi["excerpt"] and news(F)["users"].get(str(ids["frank"])) == "Frank", "frank: mention with tokens + names for highlighting")
check(kinds(D) == [], "dave (no access) gets nothing")
check(kinds(E) == [], "eve (collab off) gets nothing")
check(kinds(Bb)[0] == ("comment", 1), "bob (assignee + previous commenter): comment item")
time.sleep(0.6)
tops = sorted(p["topic"] for p in pushes())
check("t-carol" in tops and all(t.startswith("t-") for t in tops) and "t-eve" not in tops and "t-dave" not in tops, f"pushes follow the same recipients: {tops}")
check(sorted(r[0] for r in db().execute("SELECT DISTINCT user_id FROM notifications")) == sorted([1, ids["bob"], ids["carol"], ids["frank"]]), "no rows at all for eve / dave")
# burst: second + third comment right away -> push held back, feed keeps every item (grouped)
clear()
A.post(B + f"/api/tasks/{ST}/comments", json={"body": "two"})
F.post(B + f"/api/tasks/{ST}/comments", json={"body": "three"})
time.sleep(0.6)
check(not [p for p in pushes() if p["topic"] == "t-bob"], "burst: bob's pushes held back")
bi = news(Bb)["items"][0]
check(bi["kind"] == "comment" and bi["count"] == 3 and len(bi["ids"]) == 3 and set(bi["actors"]) == {1, ids["frank"]} and bi["excerpt"] == "three", f"grouping: 3 consecutive comments in one row: {bi['count']} {bi['actors']}")
# mentions break a group; mention filter
A.post(B + f"/api/tasks/{ST}/comments", json={"body": f"<@{ids['bob']}> ping"})
A.post(B + f"/api/tasks/{ST}/comments", json={"body": "after"})
kb = kinds(Bb)
check(kb[:3] == [("comment", 1), ("mention", 1), ("comment", 3)], f"mention splits the group: {kb}")
mf = news(Bb, "mentions")["items"]
check([x["kind"] for x in mf] == ["mention"], "filter=mentions")
# unread + version signature
n0 = Bb.get(B + "/api/state").json()["news"]
check(n0["unread"] == len([x for x in news(Bb)["items"] if not x["read"]]) == 5, f"state unread = unread rows: {n0}")
v0 = Bb.get(B + "/api/version").json()
check(v0["n"] == n0["sig"], "version carries the signature")
na = A.get(B + "/api/state").json()["news"]["unread"]
# IDOR: bob marks alice's ids
aids = [i for x in news(A)["items"] for i in x["ids"]]
r = Bb.post(B + "/api/news/read", json={"ids": aids})
check(r.ok and A.get(B + "/api/state").json()["news"]["unread"] == na, "IDOR: bob cannot mark alice's items read")
check(not (set(aids) & {i for x in news(Bb)["items"] for i in x["ids"]}), "bob never sees alice's rows")
check(Bb.post(B + "/api/news/read", json={"ids": ["x"]}).status_code == 400, "invalid ids -> 400")
check(sess().get(B + "/api/news").status_code == 401 and sess().post(B + "/api/news/read", json={"all": True}).status_code == 401, "anonymous: 401")
# mark one group read
g = news(Bb)["items"][2]
j = Bb.post(B + "/api/news/read", json={"ids": g["ids"]}).json()
check(j["unread"] == 4 and news(Bb)["items"][2]["read"], "marking a group reads all its rows")
check(Bb.get(B + "/api/version").json()["n"] != v0["n"], "signature moves after reading")
# opening the task (seen) marks its items read
Bb.post(B + f"/api/tasks/{ST}/seen")
check(all(x["read"] for x in news(Bb)["items"] if x["task_id"] == ST), "task seen -> its News read")
# complete by another user -> creator + assigner (alice); not self
time.sleep(4.5); clear()
Bb.post(B + f"/api/tasks/{ST}/complete", json={})
check(kinds(A)[0] == ("complete", 1), f"alice: complete item {kinds(A)[:2]}")
check(all(k != "complete" for k, _ in kinds(Bb)), "bob: no complete item for his own action")
check(kinds(C)[0] != ("complete", 1), "carol (not creator/assigner): no complete item")
time.sleep(4.5); check({p["topic"] for p in pushes()} == {"t-alice"}, f"complete push (or its burst summary) only to alice {pushes()}")
# a completed task is still visible in the feed + GET single task
check(Bb.get(B + f"/api/tasks/{ST}").json()["status"] == 2 and D.get(B + f"/api/tasks/{ST}").status_code == 404, "GET /api/tasks/<id>: visible for bob, 404 for dave")
# unassign / reassign
T2 = A.post(B + "/api/tasks", json={"title": "Second", "list_id": L, "assignee_id": ids["bob"]}).json()["id"]
A.patch(B + f"/api/tasks/{T2}", json={"assignee_id": ids["frank"]})
check(kinds(Bb)[:2] == [("unassign", 1), ("assign", 1)], f"bob: assign then unassign {kinds(Bb)[:2]}")
check(kinds(F)[0] == ("assign", 1), "frank: assign")
# frank unassigns himself: no self item; alice not the assignee -> nothing
F.patch(B + f"/api/tasks/{T2}", json={"assignee_id": None})
check(kinds(F)[0] == ("assign", 1), "self-unassign: no item")
# deleted comment disappears
cid = F.post(B + f"/api/tasks/{T2}/comments", json={"body": f"secret remark <@{ids['bob']}>"}).json()["id"]
check(kinds(Bb)[0] == ("mention", 1), "bob mentioned on T2")
F.delete(B + f"/api/comments/{cid}")
check(kinds(Bb)[0] == ("unassign", 1) and "secret remark" not in json.dumps(news(Bb)), "deleted comment: item gone")
# task in trash disappears
A.delete(B + f"/api/tasks/{T2}")
check(all(x["task_id"] != T2 for x in news(Bb)["items"]), "task in trash: items hidden")
A.post(B + f"/api/tasks/{T2}/restore")
check(any(x["task_id"] == T2 for x in news(Bb)["items"]), "restored: items back")
# roles: dave shared view -> edit -> removed
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["dave"], "role": "view"})
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["dave"], "role": "view"})  # unchanged: no item
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["dave"], "role": "edit"})
dk = news(D)["items"]
check([x["kind"] for x in dk] == ["role", "share"] and dk[0]["data"] == {"role": "edit", "old": "view", "name": "Shared"}, f"dave: share + role {[x['kind'] for x in dk]}")
A.delete(B + f"/api/lists/{L}/members/{ids['dave']}")
dk = news(D)["items"]
check([x["kind"] for x in dk] == ["unshare"] and dk[0]["data"]["name"] == "Shared" and dk[0]["task_id"] is None, f"dave after removal: only unshare {dk}")
# leaving on your own: no item for the leaver; owner gets nothing either
na = len(news(A)["items"])
C.delete(B + f"/api/lists/{L}/members/{ids['carol']}")
check(("unshare", 1) not in kinds(C) and len(news(A)["items"]) == na, "leaving: no items")
check(all(x["kind"] == "unshare" for x in news(C)["items"]) and not any(x.get("task_title") for x in news(C)["items"]), "carol after leaving: no task titles leak")
# visibility: bob loses access to L2 -> the T3 title never shows up
L2 = A.post(B + "/api/lists", json={"name": "Private project"}).json()["id"]
A.put(B + f"/api/lists/{L2}/members", json={"user_id": ids["bob"], "role": "edit"})
T3 = A.post(B + "/api/tasks", json={"title": "Very private title", "list_id": L2, "assignee_id": ids["bob"]}).json()["id"]
check(any(x["task_id"] == T3 for x in news(Bb)["items"]), "bob sees T3 while member")
A.delete(B + f"/api/lists/{L2}/members/{ids['bob']}")
raw = Bb.get(B + "/api/news").text
check("Very private title" not in raw and '"kind":"unshare"' in raw.replace(" ", ""), "lost access: T3 title gone from the feed, unshare shown")
# task moved to a list bob cannot see
T4 = A.post(B + "/api/tasks", json={"title": "Moved away", "list_id": L, "assignee_id": ids["bob"]}).json()["id"]
A.patch(B + f"/api/tasks/{T4}", json={"list_id": L2})
check("Moved away" not in Bb.get(B + "/api/news").text, "task moved to an invisible list: hidden")
# mark all
Bb.post(B + "/api/news/read", json={"all": True})
check(Bb.get(B + "/api/state").json()["news"]["unread"] == 0 and A.get(B + "/api/state").json()["news"]["unread"] > 0, "mark all: only mine")
# collab switched off later: feed hidden, badge 0; back on: items back
feats = Bb.get(B + "/api/state").json()["settings"]["features"]
A.post(B + f"/api/tasks/{ST}/comments", json={"body": f"<@{ids['bob']}> x"})
Bb.patch(B + "/api/settings", json={"features": ",".join(x for x in feats.split(",") if x != "collab")})
check(news(Bb)["items"] == [] and Bb.get(B + "/api/state").json()["news"]["unread"] == 0, "collab off: feed + badge hidden")
n_rows = db().execute("SELECT COUNT(*) FROM notifications WHERE user_id=?", (ids["bob"],)).fetchone()[0]
A.post(B + f"/api/tasks/{ST}/comments", json={"body": f"<@{ids['bob']}> y"})
check(db().execute("SELECT COUNT(*) FROM notifications WHERE user_id=?", (ids["bob"],)).fetchone()[0] == n_rows, "collab off: no new rows written")
Bb.patch(B + "/api/settings", json={"features": feats})
check(news(Bb)["items"][0]["kind"] == "mention" and news(Bb)["items"][0]["excerpt"] == f"<@{ids['bob']}> x", "collab on again: older items back")
# edit adds a mention -> mention item for the new person only
cid = A.post(B + f"/api/tasks/{ST}/comments", json={"body": "plain"}).json()["id"]
nf = len(news(F)["items"])
A.patch(B + f"/api/comments/{cid}", json={"body": f"plain <@{ids['frank']}>"})
check(len(news(F)["items"]) == nf + 1 and news(F)["items"][0]["kind"] == "mention", "edit adds a mention -> item")
# long excerpt cut without a broken token
A.post(B + f"/api/tasks/{ST}/comments", json={"body": "x" * 297 + f"<@{ids['frank']}> tail"})
ex = news(F)["items"][0]["excerpt"]
check(ex.endswith("…") and "<@" not in ex and len(ex) <= 301, f"excerpt cut cleanly ({len(ex)})")
print(json.dumps({"ids": ids, "L": L, "ST": ST}), file=open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_ids.json"), "w"))
print(f"\n{OKS[0]} ok, {len(FAILS)} failed"); sys.exit(1 if FAILS else 0)
