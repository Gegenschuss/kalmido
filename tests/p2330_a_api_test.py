#!/usr/bin/env python3
"""2.33.0 API tests, part A: replies to one message (#1076) -- task comments, team chat, agent chat.
 - reply_to (app, multipart form, REST v1, agents): only a message of the SAME place (same task / conversation / person-agent
   chat); another place, a deleted original, an unknown id or a bad value -> 400; unknown fields stay refused
 - every message carries reply_to + reply (a short quote {id, user_id, name, text, deleted}); a deleted original -> deleted
 - the author of the original gets a push "replied to your message" (Web Push, fake push service); never the replier
 - agents get the reference in their events (comment.reply, team_message message.reply, chat message.reply)
 - OpenAPI: ReplyQuote, reply_to in the inputs; rollback safety: three nullable columns, nothing else changed
usage: p2330_a_api_test.py <datadir>"""
import base64
import json
import os
import sqlite3
import subprocess
import sys
import time

import http_ece
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
STUB = "http://127.0.0.1:9997"
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


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def wp_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "webpush.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


class Browser:
    def __init__(self, path):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.endpoint = STUB + path
        self.pub = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

    def sub(self, label):
        return {"endpoint": self.endpoint, "keys": {"p256dh": b64u(self.pub), "auth": b64u(self.auth)}, "label": label}

    def notes(self):
        out = []
        for rec in wp_log():
            if rec["path"] == self.endpoint[len(STUB):]:
                p = json.loads(http_ece.decrypt(base64.b64decode(rec["body"]), private_key=self.key, auth_secret=self.auth, version="aes128gcm"))
                if p.get("type") != "dismiss":
                    out.append(p)
        return out


def wait_note(br, pred, t=6.0):
    t0 = time.time()
    while time.time() - t0 < t:
        hit = [p for p in br.notes() if pred(p)]
        if hit:
            return hit
        time.sleep(0.3)
    return []


env = dict(os.environ, EXTRA="-e KALMIDO_WEBPUSH_HOSTS=" + STUB)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["cp", os.path.join(N, "stub_webpush.py"), DATA])
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webpush.py"])
time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
Bo, Ca = sess("bob"), sess("carol")
for x in (A, Bo, Ca):
    x.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
aphone, bphone = Browser("/push/alice"), Browser("/push/bob")
check(A.post(B + "/api/push/subs", json=aphone.sub("Phone")).ok and Bo.post(B + "/api/push/subs", json=bphone.sub("Phone")).ok, "subscribed")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
TEAM = A.post(B + "/api/lists", json={"name": "Team", "org_id": ORG}).json()["id"]
OTHER = A.post(B + "/api/lists", json={"name": "Other", "org_id": ORG}).json()["id"]
for uid in (BOB, CL):
    assert A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": uid, "role": "edit"}).ok
T1 = A.post(B + "/api/tasks", json={"title": "Write the release notes", "list_id": TEAM}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Second task", "list_id": TEAM}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"title": "Alice only", "list_id": OTHER}).json()["id"]


def events(since):
    return requests.get(V + f"/agent/events?since={since}&limit=200", headers=CLH).json()


def latest():
    return requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]


# ================================================================== rollback safety: three nullable columns
for t in ("comments", "tchat_msgs", "agent_chat"):
    col = [x for x in dbx(f"PRAGMA table_info({t})") if x[1] == "reply_to"]
    check(len(col) == 1 and col[0][3] == 0 and col[0][4] is None, f"#1076: {t}.reply_to is a nullable column without default " + str(col))

# ================================================================== task comments
c1 = Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "Should the notes mention the **new** search, <@%d>?" % ALICE}).json()
time.sleep(0.3)
n_before = len(bphone.notes())
r = A.post(B + f"/api/tasks/{T1}/comments", json={"body": "Yes, with a screenshot.", "reply_to": c1["id"]})
check(r.ok and r.json()["reply_to"] == c1["id"], "#1076: a reply to a comment of the same task " + r.text[:200])
q = r.json().get("reply") or {}
check(q.get("id") == c1["id"] and q.get("user_id") == BOB and q.get("name") == "Bob" and not q.get("deleted")
      and q.get("text", "").startswith("Should the notes mention the new search, @Alice"), "#1076: the reply carries a plain quote (Markdown out, @name) " + json.dumps(q))
R1 = r.json()["id"]
tl = A.get(B + f"/api/tasks/{T1}/timeline").json()
byid = {x["id"]: x for x in tl["comments"]}
check(byid[R1]["reply_to"] == c1["id"] and byid[R1]["reply"]["name"] == "Bob" and byid[c1["id"]]["reply_to"] is None and byid[c1["id"]]["reply"] is None,
      "#1076: the timeline carries reply_to + reply (null without)")
hit = wait_note(bphone, lambda p: "replied to your message" in p.get("body", ""))
check(len(hit) == 1 and hit[0]["body"].startswith("Alice replied to your message: Yes, with a screenshot."), "#1076: Bob gets 'Alice replied to your message' " + json.dumps([p.get("body") for p in bphone.notes()[n_before:]]))
check(not [p for p in aphone.notes() if "replied" in p.get("body", "")], "#1076: never a push to the one who replied")
nf = dbx("SELECT kind, data FROM notifications WHERE user_id=? AND comment_id=?", (BOB, R1))
check(len(nf) == 1 and json.loads(nf[0][1] or "{}").get("reply") == 1, "#1076: Bob's News entry is marked as a reply (For you) " + str(nf))
# refused: another task, unknown, bad values, a deleted original
c2 = A.post(B + f"/api/tasks/{T2}/comments", json={"body": "On the second task"}).json()
for v, what in ((c2["id"], "a comment of another task"), (999999, "an unknown id"), ("abc", "a string"), (True, "a bool"), (-3, "a negative id")):
    r = A.post(B + f"/api/tasks/{T1}/comments", json={"body": "x", "reply_to": v})
    check(r.status_code == 400, f"#1076: reply_to = {what} -> 400 " + str(r.status_code))
check(len(A.get(B + f"/api/tasks/{T1}/timeline").json()["comments"]) == 2, "#1076: ... and nothing was stored")
check(Ca.post(B + f"/api/tasks/{T1}/comments", json={"body": "x", "reply_to": c1["id"]}).status_code == 404, "#1076: a stranger still gets 404 for the task")
r = A.post(B + f"/api/tasks/{T1}/comments", data={"body": "With a file", "reply_to": str(c1["id"])}, files={"file": ("a.txt", b"hello", "text/plain")})
check(r.ok and r.json()["reply_to"] == c1["id"], "#1076: multipart form takes reply_to " + r.text[:160])
check(A.post(B + f"/api/tasks/{T1}/comments", data={"body": "x", "reply_to": str(c2["id"])}, files={"file": ("a.txt", b"x", "text/plain")}).status_code == 400,
      "#1076: ... and refuses another task's comment")
# a deleted original: shown as deleted, cannot be answered any more
assert Bo.delete(B + f"/api/comments/{c1['id']}").ok
tl = A.get(B + f"/api/tasks/{T1}/timeline").json()
q = {x["id"]: x for x in tl["comments"]}[R1]["reply"]
check(q["deleted"] is True and q["text"] == "" and q["user_id"] is None, "#1076: a deleted original shows as deleted, no text " + json.dumps(q))
check(A.post(B + f"/api/tasks/{T1}/comments", json={"body": "x", "reply_to": c1["id"]}).status_code == 400, "#1076: a deleted comment cannot be answered")
# REST v1: the agent answers a comment; the person's comment events carry the reference
cur = latest()
r = requests.post(V + f"/tasks/{T1}/comments", headers=CLH, json={"body": "I will add the screenshot.", "reply_to": R1})
check(r.status_code == 201 and r.json()["reply_to"] == R1 and r.json()["reply"]["name"] == "Alice", "#1076 v1: an agent replies to a comment " + r.text[:200])
CA = r.json()["id"]
check(requests.post(V + f"/tasks/{T1}/comments", headers=CLH, json={"body": "x", "reply_to": c2["id"]}).status_code == 400, "#1076 v1: another task's comment -> 400")
check(requests.post(V + f"/tasks/{T1}/comments", headers=CLH, json={"body": "x", "reply_too": R1}).status_code == 400, "#1076 v1: unknown fields stay refused")
j = requests.get(V + f"/tasks/{T1}/comments", headers=CLH).json()["data"]
check({x["id"]: x for x in j}[CA]["reply"]["id"] == R1, "#1076 v1: the comment list carries reply")
cur = latest()
r = A.post(B + f"/api/tasks/{T1}/comments", json={"body": "Thanks!", "reply_to": CA})
ev = [e for e in events(cur)["data"] if e["event"] in ("mention", "comment")]
check(len(ev) == 1 and ev[0]["event"] == "mention" and (ev[0]["data"].get("comment") or {}).get("reply_to") == CA
      and ev[0]["data"]["comment"]["reply"]["user_id"] == CL, "#1076: a reply to the agent's comment reaches it like a mention, with the quote " + json.dumps(ev)[:300])
oa = json.loads(A.get(V + "/openapi.json").text)
sc = oa["components"]["schemas"]
check("ReplyQuote" in sc and "reply_to" in sc["CommentInput"]["properties"] and "reply" in sc["Comment"]["properties"]
      and "reply" in sc.get("TeamMessage", {}).get("properties", {}) and "reply" in sc.get("ChatMessage", {}).get("properties", {}),
      "#1076: OpenAPI documents ReplyQuote and reply_to")

# ================================================================== team chat
rooms = A.get(B + "/api/team").json()["rooms"]
RID = next(x["id"] for x in rooms if x["kind"] == "list" and x["list_id"] == TEAM)
DM = A.post(B + "/api/team/dm", json={"user_id": BOB}).json()["id"]
m1 = Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Who takes the **release**?"}).json()
d1 = Bo.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "Private question"}).json()
time.sleep(0.5)
n_before = len(bphone.notes())
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "I do.", "reply_to": m1["id"]})
check(r.status_code == 201 and r.json()["reply_to"] == m1["id"] and r.json()["reply"]["text"] == "Who takes the release?", "#1076 team: a reply in the channel " + r.text[:200])
M2 = r.json()["id"]
hit = wait_note(bphone, lambda p: "replied to your message" in p.get("body", "") and "I do." in p.get("body", ""))
check(len(hit) == 1, "#1076 team: Bob gets 'replied to your message' without a bell / mention " + json.dumps([p.get("body") for p in bphone.notes()[n_before:]]))
pg = A.get(B + f"/api/team/rooms/{RID}/messages").json()["messages"]
check({x["id"]: x for x in pg}[M2]["reply"]["user_id"] == BOB, "#1076 team: the page carries the quote")
for v, what in ((d1["id"], "a message of another conversation"), (987654, "an unknown id"), ("x", "a string")):
    check(A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "x", "reply_to": v}).status_code == 400, f"#1076 team: reply_to = {what} -> 400")
r = A.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "Sure.", "reply_to": d1["id"]})
check(r.status_code == 201 and r.json()["reply"]["text"] == "Private question", "#1076 team: a reply in a direct conversation")
check(wait_note(bphone, lambda p: p.get("body", "").startswith("Replied to your message: Sure.")), "#1076 team: the DM push says it is a reply")
assert Bo.delete(B + f"/api/team/messages/{m1['id']}").ok
pg = {x["id"]: x for x in A.get(B + f"/api/team/rooms/{RID}/messages").json()["messages"]}
check(pg[M2]["reply"]["deleted"] is True and pg[M2]["reply"]["text"] == "", "#1076 team: a deleted original shows as deleted")
check(A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "x", "reply_to": m1["id"]}).status_code == 400, "#1076 team: a deleted message cannot be answered")
# the agent in the channel (v1) + its event
r = requests.post(V + f"/team/rooms/{RID}/messages", headers=CLH, json={"body": "Release notes are drafted.", "reply_to": M2})
check(r.status_code == 201 and r.json()["reply_to"] == M2, "#1076 v1 team: the agent replies " + r.text[:200])
MA = r.json()["id"]
cur = latest()
A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Great, thanks.", "reply_to": MA})
ev = [e for e in events(cur)["data"] if e["event"] == "team_message"]
check(len(ev) == 1 and ev[0]["data"]["message"].get("reply_to") == MA and ev[0]["data"]["message"]["reply"]["text"] == "Release notes are drafted.",
      "#1076 team: a reply to the agent's message reaches it (like a mention) with the quote " + json.dumps(ev)[:300])
check(Ca.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "x", "reply_to": M2}).status_code == 404, "#1076 team: a stranger gets 404")

# ================================================================== agent chat
r = requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": "Shall I also update the README?"})
q1 = r.json()
cur = latest()
r = A.post(B + f"/api/agents/{CL}/chat", json={"body": "Yes, please.", "reply_to": q1["id"]})
check(r.status_code == 201 and r.json()["reply_to"] == q1["id"] and r.json()["reply"]["from"] == "agent" and r.json()["reply"]["name"] == "Claude",
      "#1076 chat: the person answers one agent message " + r.text[:200])
P1 = r.json()["id"]
ev = [e for e in events(cur)["data"] if e["event"] == "chat"]
check(len(ev) == 1 and ev[0]["data"]["message"]["reply_to"] == q1["id"] and ev[0]["data"]["message"]["reply"]["text"] == "Shall I also update the README?",
      "#1076 chat: the agent's chat event carries the reference + quote " + json.dumps(ev)[:300])
r = requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": "Done.", "reply_to": P1})
check(r.status_code == 201 and r.json()["reply"]["from"] == "user" and r.json()["reply"]["user_id"] == ALICE, "#1076 chat v1: the agent answers one message " + r.text[:200])
j = requests.get(V + "/agent/chats?since=0", headers=CLH).json()["data"]
check({x["id"]: x for x in j}[P1]["reply"]["id"] == q1["id"], "#1076 chat v1: the agent's chat list carries reply")
ms = {x["id"]: x for x in A.get(B + f"/api/agents/{CL}/chat").json()["messages"]}
check(ms[P1]["reply"]["id"] == q1["id"] and ms[q1["id"]]["reply"] is None, "#1076 chat: the app's chat carries reply")
for v, what in ((q1["id"] + 5000, "an id beyond the conversation"), (123456, "an unknown id"), ("nope", "a string")):
    check(A.post(B + f"/api/agents/{CL}/chat", json={"body": "x", "reply_to": v}).status_code == 400, f"#1076 chat: reply_to = {what} -> 400")
    check(requests.post(V + f"/agent/chats/{ALICE}", headers=CLH, json={"body": "x", "reply_to": v}).status_code == 400, f"#1076 chat v1: reply_to = {what} -> 400")
r = A.post(B + f"/api/agents/{CL}/chat", data={"body": "A file", "reply_to": str(q1["id"])}, files={"file": ("n.txt", b"x", "text/plain")})
check(r.status_code == 201 and r.json()["reply_to"] == q1["id"], "#1076 chat: multipart form takes reply_to " + r.text[:160])

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
