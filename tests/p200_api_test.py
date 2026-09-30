#!/usr/bin/env python3
"""2.0.0: agents, events (webhooks + polling + long-polling), wake, reactions + approvals, agent status, jobs, chat,
shared list tags, the tidy setting, and the permission rules around them.
Agents are users of kind 'agent': created by an admin (token + webhook secret shown once) or converted from a user; never
admin, no Paperless, no web login; they see only lists shared with them (participant role included); the kill switch stops
their tokens, events and webhook. Events go to the polling queue and (signed) to the webhook; never for the agent's own
actions. Reactions ❤️ 👍 👎 for everyone who sees the comments; 👍 / 👎 on an agent's comment by an approver (list owner / list
admin / assignee / instance admin) is an approval. List tags are shared by the list members; personal tags stay personal.
Starts its OWN test container (start.sh) with the webhook stub inside.
usage: p200_api_test.py <datadir>"""
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
PB = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PROXY_PORT", "3041")
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


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def get(self, p, **k):
        return requests.get(V + p, headers=self.h, timeout=90, **k)

    def post(self, p, **k):
        return requests.post(V + p, headers=self.h, timeout=30, **k)

    def put(self, p, **k):
        return requests.put(V + p, headers=self.h, timeout=30, **k)

    def patch(self, p, **k):
        return requests.patch(V + p, headers=self.h, timeout=30, **k)

    def delete(self, p, **k):
        return requests.delete(V + p, headers=self.h, timeout=30, **k)


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def hooks_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "wh.log")) if x.strip()]
    except FileNotFoundError:
        return []


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def wait_for(pred, timeout=12):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(0.3)
    return pred()


subprocess.run(["rm", "-rf", DATA])
os.makedirs(DATA)
subprocess.run(["cp", os.path.join(N, "stub_webhook.py"), DATA])
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA],
                   env=dict(os.environ, KEEP="1", EXTRA="-e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_WEBHOOK_TICK=1"),
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webhook.py"])
time.sleep(0.8)

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
ids = {"alice": 1}
for u in ("bob", "pete", "vic", "dave", "conv", "carl"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, P, Vi, D = (sess(u) for u in ("bob", "pete", "vic", "dave"))
for s_ in (A, Bo, P, Vi, D):
    s_.patch(B + "/api/settings", json={"lang": "en"})

# ================================================================== agents: create, flags, rules
r = A.post(B + "/api/admin/agents", json={"username": "claude", "display_name": "Claude", "note": "Dev helper",
                                          "webhook_url": "http://127.0.0.1:8097/agent"})
check(r.status_code == 201, "admin creates an agent: " + r.text[:200])
ag = r.json()
CL, TOK, SECRET = ag["id"], ag["token"], ag["webhook_secret"]
check(TOK.startswith("abk_") and SECRET.startswith("whsec_") and ag["enabled"] and ag["webhook"]["url"].endswith("/agent"),
      "token + webhook secret shown once")
r = A.post(B + "/api/admin/agents", json={"username": "robo", "display_name": "Robo"})
RO, RTOK = r.json()["id"], r.json()["token"]
check(r.json()["webhook"] is None and r.json()["webhook_secret"] is None, "agent without webhook (polling only)")
check(Bo.post(B + "/api/admin/agents", json={"username": "x1"}).status_code == 403, "only admins create agents")
check(A.post(B + "/api/admin/agents", json={"username": "claude"}).status_code == 409, "username taken")
cl, ro = Api(TOK), Api(RTOK)
me_ = cl.get("/me").json()
check(me_["kind"] == "agent" and not me_["is_admin"], "v1 me: kind agent, not admin")
u = dbx("SELECT kind, is_admin, paperless_access, password_hash FROM users WHERE id=?", (CL,))[0]
check(u == ("agent", 0, 0, None), f"db row {u}")
users = {x["id"]: x for x in A.get(B + "/api/users").json()["users"]}
check(users[CL]["kind"] == "agent" and users[CL].get("agent") is True and users[ids["bob"]]["kind"] == "user", "users list: kind")
check(any(x["id"] == CL and x.get("agent") for x in Bo.get(B + "/api/users").json()["users"]), "share picker marks agents")
r = A.patch(B + f"/api/users/{CL}", json={"is_admin": True})
check(r.status_code == 400 and dbx("SELECT is_admin FROM users WHERE id=?", (CL,))[0][0] == 0, "agent never admin")
r = A.patch(B + f"/api/users/{CL}", json={"paperless_access": True})
check(r.status_code == 400 and dbx("SELECT paperless_access FROM users WHERE id=?", (CL,))[0][0] == 0, "agent never Paperless")
check(cl.get("/admin/users").status_code == 403 and cl.get("/admin/status").status_code == 403, "agent: no admin API")
check(Bo.get(V + "/agent").status_code in (401, 404) and Api(Bo.post(B + "/api/me/tokens", json={"name": "b", "scopes": ["read", "write"]})
                                                            .json()["token"]).get("/agent").status_code == 403, "agent endpoints: agents only")

# convert an existing user (with password, token, own list) into an agent and back
Cv = sess("conv")
ctok = Cv.post(B + "/api/me/tokens", json={"name": "c", "scopes": ["read", "write"]}).json()["token"]
CVL = Cv.post(B + "/api/lists", json={"name": "Conv list"}).json()["id"]
Cv.put(B + f"/api/lists/{CVL}/members", json={"user_id": ids["alice"], "role": "edit"})
check(A.patch(B + f"/api/users/{ids['conv']}", json={"kind": "agent"}).ok, "convert user -> agent")
check(Cv.get(B + "/api/state").status_code == 401, "converted: web session ended")
check(sess().post(B + "/api/auth/login", json={"username": "conv", "password": "password123"}).status_code == 401, "agent: no password login")
cva = Api(ctok)
check(cva.get("/me").json()["kind"] == "agent" and any(x["id"] == CVL for x in cva.get("/lists").json()["data"]), "token + own lists kept")
check(any(x["id"] == CVL for x in A.get(B + "/api/state").json()["lists"]), "the list stays shared with alice")
A.patch(B + f"/api/users/{ids['conv']}", json={"proxy_login": "convproxy"})
r = requests.get(PB + "/api/state", headers={"Remote-User": "convproxy"})
check(r.status_code in (401, 403), f"agent: no proxy login ({r.status_code})")
check(A.patch(B + "/api/users/1", json={"kind": "agent"}).status_code == 400, "cannot turn myself into an agent")
A.post(B + "/api/users", json={"username": "adm2", "password": "password123", "is_admin": True})
adm2 = [x["id"] for x in A.get(B + "/api/users").json()["users"] if x["username"] == "adm2"][0]
check(A.patch(B + f"/api/users/{adm2}", json={"kind": "agent"}).status_code == 400, "an admin must lose admin rights first")
check(A.patch(B + f"/api/users/{ids['conv']}", json={"kind": "user"}).ok and dbx("SELECT kind FROM users WHERE id=?", (ids["conv"],))[0][0] == "user",
      "agent -> user again")
check(sess("conv").get(B + "/api/state").ok, "person again: login works")
A.patch(B + f"/api/users/{ids['conv']}", json={"kind": "agent"})
check(any(a["id"] == ids["conv"] for a in A.get(B + "/api/admin/agents").json()["agents"]), "converted agent in the admin list")

# ================================================================== a shared project list
L = A.post(B + "/api/lists", json={"name": "Film", "kind": "project"}).json()["id"]
PRIV = A.post(B + "/api/lists", json={"name": "Alice private"}).json()["id"]
sec = {n: A.post(B + "/api/sections", json={"list_id": L, "name": n}).json()["id"] for n in ("Inbox", "Ideas")}
for u_, role in (("bob", "edit"), ("pete", "participant"), ("vic", "view")):
    check(A.put(B + f"/api/lists/{L}/members", json={"user_id": ids[u_], "role": role}).ok, f"share {u_}")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": CL, "role": "admin"}).status_code == 400, "agent cannot be list admin")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": CL, "role": "edit"}).ok, "share with agent (member)")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": RO, "role": "participant"}).ok, "share with agent 2 (participant)")
st = A.get(B + "/api/state").json()
lm = next(x for x in st["lists"] if x["id"] == L)["members"]
check(any(m["user_id"] == CL and m.get("agent") for m in lm), "members: agent flag")
check({x["id"] for x in cl.get("/lists").json()["data"]} == {L, dbx("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (CL,))[0][0]},
      "agent sees only the shared list (+ its inbox)")
check(cl.get(f"/lists/{PRIV}").status_code == 404, "private list: 404 for the agent")


def mk(s, **kw):
    r = s.post(B + "/api/tasks", json=kw)
    assert r.ok, (kw, r.text)
    return r.json()["id"]


T1 = mk(A, title="Write treatment", list_id=L, section_id=sec["Inbox"])
T2 = mk(A, title="Cut trailer", list_id=L, content="rough cut first")
T3 = mk(A, title="Hidden budget", list_id=L, content="SECRET")
TP = mk(A, title="Private thing", list_id=PRIV)


def events(api, since=0, **k):
    r = api.get("/agent/events", params={"since": since, **k})
    assert r.ok, r.text
    return r.json()


cur0 = cl.get("/agent").json()["cursor"]

# ---- events: mention in a comment (queue + signed webhook)
c1 = A.post(B + f"/api/tasks/{T1}/comments", json={"body": f"<@{CL}> can you draft this?"}).json()["id"]
ev = events(cl, cur0)
m = [e for e in ev["data"] if e["event"] == "mention"]
check(len(m) == 1 and m[0]["data"]["task"]["id"] == T1 and m[0]["data"]["comment"]["id"] == c1 and m[0]["data"]["where"] == "comment"
      and m[0]["actor"]["id"] == 1 and m[0]["seq"] == ev["cursor"], "mention event in the queue")
hk = wait_for(lambda: [h for h in hooks_log() if h["path"] == "/agent" and json.loads(h["body"])["event"] == "mention"])
check(bool(hk), "mention delivered to the agent's webhook")
if hk:
    h = hk[0]
    t_, sig = [x.split("=", 1)[1] for x in h["headers"]["X-Kalmido-Signature"].split(",")]
    want = hmac.new(SECRET.encode(), t_.encode() + b"." + h["body"].encode(), hashlib.sha256).hexdigest()
    body = json.loads(h["body"])
    check(hmac.compare_digest(sig, want), "webhook HMAC valid")
    check(body["id"] == m[0]["id"] and body["seq"] == m[0]["seq"] and h["headers"]["X-Kalmido-Event"] == "mention"
          and h["headers"]["X-Kalmido-Delivery"] == m[0]["id"], "webhook body = queue envelope")
check(not [e for e in events(ro, 0)["data"] if e["event"] == "mention"], "other agent: nothing")
check(not dbx("SELECT 1 FROM notifications WHERE user_id=?", (CL,)), "agents get no News rows")

# ---- assignment, follow-up comments, own actions, task text mention
cur = events(cl, 0)["cursor"]
A.patch(B + f"/api/tasks/{T2}", json={"assignee_id": CL})
e = events(cl, cur)["data"]
check([x["event"] for x in e] == ["assigned"] and e[0]["data"]["task"]["assignee_id"] == CL, f"assigned event {[x['event'] for x in e]}")
cur = e[-1]["seq"] if e else cur
Bo.post(B + f"/api/tasks/{T2}/comments", json={"body": "go ahead"})
e = events(cl, cur)["data"]
check([x["event"] for x in e] == ["comment"] and e[0]["data"]["comment"]["text"] == "go ahead", "comment on a task it follows")
cur = e[-1]["seq"] if e else cur
cc = cl.post(f"/tasks/{T2}/comments", json={"body": "Plan: 1. rough cut 2. music"}).json()
check(not events(cl, cur)["data"], "own comment: no event")
T4 = mk(Bo, title="Ask @Claude about the score", list_id=L)
e = events(cl, cur)["data"]
check([x["event"] for x in e] == ["mention"] and e[0]["data"]["where"] == "task" and e[0]["data"]["task"]["id"] == T4, "@name in a task title")
cur = e[-1]["seq"] if e else cur
Bo.patch(B + f"/api/tasks/{T4}", json={"content": "also @claude please"})
check(not events(cl, cur)["data"], "same agent named again: no second event")
A.patch(B + f"/api/tasks/{T2}", json={"assignee_id": None})
e = events(cl, cur)["data"]
check([x["event"] for x in e] == ["unassigned"], "unassigned event")
A.patch(B + f"/api/tasks/{T2}", json={"assignee_id": CL})
cur = events(cl, 0)["cursor"]
check(cl.patch(f"/tasks/{T2}", json={"assignee_id": None}).ok and not events(cl, cur)["data"], "agent unassigns itself: no event")
A.patch(B + f"/api/tasks/{T2}", json={"assignee_id": CL})
cur = events(cl, 0)["cursor"]

# ---- participant agent: only its tasks
A.post(B + f"/api/tasks/{T3}/comments", json={"body": f"<@{RO}> <@{CL}> budget?"})
check(not [x for x in events(ro, 0)["data"] if x["event"] == "mention"], "participant agent: no event for a task it cannot see")
check(T3 not in {t["id"] for t in ro.get("/tasks", params={"list_id": L}).json()["data"]}, "participant agent: hidden task not listed")
check(ro.get(f"/tasks/{T3}").status_code == 404 and ro.get(f"/tasks/{T3}/comments").status_code == 404, "participant agent: 404")
T5 = mk(A, title="Robo job", list_id=L, assignee_id=RO)
check([x["event"] for x in events(ro, 0)["data"]] == ["assigned"] and ro.get(f"/tasks/{T5}").ok, "participant agent: its own task")
check(ro.post(f"/tasks/{T3}/comments", json={"body": "x"}).status_code == 404, "participant agent: no comment on hidden")
cur = events(cl, 0)["cursor"]

# ================================================================== reactions + approvals
ccid = cc["id"]
r = Bo.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": "heart"})
check(r.ok and r.json()["reactions"] == [{"emoji": "heart", "count": 1, "users": [{"id": ids["bob"], "name": "Bob"}]}] and r.json()["approval"] is None,
      "heart by bob " + r.text[:200])
e = events(cl, cur)["data"]
check([x["event"] for x in e] == ["reaction"] and e[0]["data"]["reaction"]["emoji"] == "heart" and e[0]["data"]["approval"] is None,
      "reaction event to the agent author")
cur = e[-1]["seq"] if e else cur
r = Bo.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": "heart"})
check(r.ok and r.json()["reactions"] == [], "toggle off")
r = Bo.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["approval"] is None, "bob (member, not assignee) 👍: no approval")
e = events(cl, cur)["data"]
check(e and e[-1]["data"]["approval"] is None, "event says: no approval")
cur = e[-1]["seq"] if e else cur
r = A.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": "👍"})
check(r.ok and r.json()["approval"] == "approved", "owner 👍 (emoji literal) = approved")
e = events(cl, cur)["data"]
check(e and e[-1]["data"]["approval"] == "approved" and e[-1]["data"]["reaction"]["user"]["id"] == 1, "approval event")
cur = e[-1]["seq"] if e else cur
tl = A.get(B + f"/api/tasks/{T2}/timeline").json()
check(any(a["kind"] == "approval" and a["data"]["ok"] and a["data"]["agent"] == CL for a in tl["activity"]), "approval in the history")
rc = next(x for x in tl["comments"] if x["id"] == ccid)["reactions"]
check({x["emoji"]: x["count"] for x in rc} == {"up": 2} and CL in tl["agents"], "timeline: reactions with names, agent ids")
r = Vi.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": "down"})
check(r.ok and r.json()["approval"] is None, "viewer may react, no approval")
check(Vi.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": "rocket"}).status_code == 400, "a word is no emoji: 400")
for bad in ("🙏🔥", "ab", "", "x🙏"):
    check(Vi.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": bad}).status_code == 400, f"not a single emoji: {bad!r}")
r = Vi.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": "🙏"})
check(r.ok and any(x["emoji"] == "🙏" for x in r.json()["reactions"]) and r.json()["approval"] is None, "custom emoji stored as itself")
r = Vi.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": "👨‍👩‍👧"})
check(r.ok and any(x["emoji"] == "👨‍👩‍👧" for x in r.json()["reactions"]), "ZWJ emoji ok")
r = Vi.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": "😂"})
check(r.ok and any(x["emoji"] == "😂" for x in r.json()["reactions"]), "😂 is a custom emoji (fixed set: up, down, heart)")
check([x["emoji"] for x in r.json()["reactions"]][:2] == ["up", "down"] and r.json()["reactions"][-1]["emoji"] == "😂", "fixed set first, others by first use " + str([x["emoji"] for x in r.json()["reactions"]]))
r = requests.delete(V + f"/comments/{ccid}/reactions/" + requests.utils.quote("🙏"), headers=cl.h)
check(r.ok, "v1 delete with an emoji in the path (agent had none: still ok)")
check(P.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": "up"}).status_code == 404, "participant cannot react on a hidden task")
check(D.post(B + f"/api/comments/{ccid}/reactions", json={"emoji": "up"}).status_code == 404, "outsider: 404")
# agent reacts via the API; reacting to a comment of a person
r = cl.post(f"/comments/{c1}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["reactions"][0]["users"][0]["id"] == CL, "agent reacts (v1)")
r = cl.delete(f"/comments/{c1}/reactions/up")
check(r.ok and r.json()["reactions"] == [], "agent removes its reaction")
vc = cl.get(f"/tasks/{T2}/comments").json()["data"]
x = next(c for c in vc if c["id"] == ccid)
check(x["author"]["agent"] and {"up", "down", "🙏", "😂"} <= {y["emoji"] for y in x["reactions"]}, "v1 comments: reactions + author.agent")
# assignee as approver
cur = events(cl, 0)["cursor"]
T6 = mk(A, title="Bob's task", list_id=L, assignee_id=ids["bob"])
k6 = cl.post(f"/tasks/{T6}/comments", json={"body": "Shall I?"}).json()["id"]
check(Bo.post(B + f"/api/comments/{k6}/reactions", json={"emoji": "down"}).json()["approval"] == "rejected", "assignee 👎 = rejected")
cur = events(cl, 0)["cursor"]

# ================================================================== status, jobs
r = cl.put("/agent/status", json={"status": "working", "text": "Cutting the trailer"})
check(r.ok and r.json()["status"] == "working", "status reported")
check(cl.put("/agent/status", json={"status": "sleeping"}).status_code == 400, "bad status: 400")
r = cl.post("/agent/jobs", json={"title": "Rough cut", "task_id": T2, "state": "waiting", "log": "plan ready"})
check(r.status_code == 201, "job created " + r.text[:200])
J = r.json()["id"]
check(cl.post("/agent/jobs", json={"title": "x", "task_id": TP}).status_code == 404, "job on a task the agent cannot see: 404")
check(cl.post("/agent/jobs", json={"title": "x", "user_id": ids["dave"]}).status_code == 400, "job for someone without a shared list: 400")
ags = {a["id"]: a for a in A.get(B + "/api/state").json()["agents"]}
check(ags[CL]["status"] == "working" and ags[CL]["waiting"] == 1 and ags[CL]["status_text"] == "Cutting the trailer", "state.agents: status + counts")
check(not D.get(B + "/api/state").json()["agents"] and not D.get(B + "/api/agents").json()["agents"], "outsider does not see the agent")
jobs = A.get(B + "/api/agents/jobs").json()["jobs"]
check([j["id"] for j in jobs] == [J] and jobs[0]["can_act"] and jobs[0]["task_title"] == "Cut trailer", "alice sees the job")
check(not P.get(B + "/api/agents/jobs").json()["jobs"], "participant: job on a hidden task invisible")
check(Vi.get(B + "/api/agents/jobs").json()["jobs"][0]["can_act"] is False, "viewer sees it, cannot act")
check(Vi.post(B + f"/api/agents/jobs/{J}/action", json={"action": "approve"}).status_code == 403, "viewer cannot approve")
r = A.post(B + f"/api/agents/jobs/{J}/action", json={"action": "approve"})
check(r.ok and r.json()["state"] == "running" and r.json()["action"] == "approve", "approve: waiting -> running")
e = events(cl, cur)["data"]
check(e and e[-1]["event"] == "job" and e[-1]["data"]["action"] == "approve" and e[-1]["data"]["job"]["id"] == J
      and e[-1]["data"]["task"]["id"] == T2, "job event")
cur = e[-1]["seq"] if e else cur
check(any(a["kind"] == "agent_job" for a in A.get(B + f"/api/tasks/{T2}/timeline").json()["activity"]), "job action in the history")
r = cl.patch(f"/agent/jobs/{J}", json={"append_log": "cut 1 done", "state": "waiting"})
check(r.ok and r.json()["log"] == "plan ready\ncut 1 done" and r.json()["state"] == "waiting", "agent updates the job")
check(wait_for(lambda: any("waiting for your approval" in (p.get("title") or "") for p in pushes()), 6), "push: waiting for approval")
r = Bo.post(B + f"/api/agents/jobs/{J}/action", json={"action": "stop"})
check(r.ok and r.json()["state"] == "stopped", "a member may stop")
check(A.post(B + f"/api/agents/jobs/{J}/action", json={"action": "approve"}).status_code == 409, "ended job: 409")
check(cl.get("/agent/jobs", params={"state": "stopped"}).json()["data"][0]["id"] == J, "agent lists its jobs")
check(ro.patch(f"/agent/jobs/{J}", json={"state": "done"}).status_code == 404, "other agent cannot touch it")
cur = events(cl, 0)["cursor"]

# ================================================================== chat
r = A.post(B + f"/api/agents/{CL}/chat", json={"body": "Hi Claude, status?"})
check(r.status_code == 201, "chat message " + r.text[:200])
e = events(cl, cur)["data"]
check(e and e[-1]["event"] == "chat" and e[-1]["data"]["message"]["body"] == "Hi Claude, status?" and e[-1]["data"]["user"]["id"] == 1, "chat event")
cur = e[-1]["seq"] if e else cur
ch = cl.get("/agent/chats").json()
check(len(ch["data"]) == 1 and ch["data"][0]["from"] == "user" and ch["cursor"] == ch["data"][0]["id"], "agent reads the chats")
r = cl.post("/agent/chats/1", json={"body": "Working on the trailer.", "task_id": T2})
check(r.status_code == 201 and r.json()["from"] == "agent", "agent answers")
check(next(a for a in A.get(B + "/api/state").json()["agents"] if a["id"] == CL)["chat_unread"] == 1, "unread answer")
msgs = A.get(B + f"/api/agents/{CL}/chat").json()["messages"]
check([m_["from"] for m_ in msgs] == ["user", "agent"] and msgs[1]["task_id"] == T2, "conversation")
check(next(a for a in A.get(B + "/api/state").json()["agents"] if a["id"] == CL)["chat_unread"] == 0, "read after opening")
check(wait_for(lambda: any(p.get("title") == "Claude" and "trailer" in (p.get("msg") or "") for p in pushes()), 6), "push for the answer")
check(D.post(B + f"/api/agents/{CL}/chat", json={"body": "hi"}).status_code == 404, "outsider cannot chat")
check(cl.post(f"/agent/chats/{ids['dave']}", json={"body": "hi"}).status_code == 404, "agent cannot write to an outsider")
check(cl.post("/agent/chats/1", json={"body": "x", "task_id": TP}).status_code == 400, "chat task the agent cannot see: 400")
check(not Bo.get(B + f"/api/agents/{CL}/chat").json()["messages"], "conversations are per person")
cur = events(cl, 0)["cursor"]

# ================================================================== wake
r = A.post(B + f"/api/tasks/{T2}/wake", json={})
check(r.ok and r.json()["agent_id"] == CL, "wake: the assignee agent")
e = events(cl, cur)["data"]
check(e and e[-1]["event"] == "wake" and e[-1]["data"]["task"]["id"] == T2 and e[-1]["data"]["source"] == "task", "wake event")
cur = e[-1]["seq"] if e else cur
check(A.post(B + f"/api/tasks/{T1}/wake", json={}).json().get("agent_id") == CL, "only agent that sees the task (robo is a participant)")
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["conv"], "role": "edit"})
check(A.post(B + f"/api/tasks/{T1}/wake", json={}).status_code == 409, "two agents see it, none assigned: choose")
A.delete(B + f"/api/lists/{L}/members/{ids['conv']}")
check(A.post(B + f"/api/tasks/{T1}/wake", json={"agent_id": CL}).ok, "wake with agent_id")
check(A.post(B + f"/api/tasks/{T1}/wake", json={"agent_id": RO}).status_code == 404, "agent that cannot see the task: 404")
check(A.post(B + f"/api/tasks/{TP}/wake", json={}).status_code == 409, "private list: no agent")
check(D.post(B + f"/api/tasks/{T2}/wake", json={}).status_code == 404, "outsider: 404")
r = A.post(B + f"/api/agents/{CL}/wake", json={"task_id": T1})
check(r.ok and events(cl, 0)["data"][-1]["data"]["source"] == "chat", "wake from the Agents tab")
codes = [Vi.post(B + f"/api/tasks/{T2}/wake", json={}).status_code for _ in range(21)]
check(codes[:20] == [200] * 20 and codes[20] == 429, f"wake rate limit {codes[-3:]}")
cur = events(cl, 0)["cursor"]

# ================================================================== long-polling
t0 = time.time()
r = cl.get("/agent/events", params={"since": cur, "wait": 2})
check(r.ok and r.json()["data"] == [] and 1.8 <= time.time() - t0 < 5 and r.json()["cursor"] == cur, "long-poll: empty after the wait")
res = {}


def poll(key, api=cl, wait=15):
    t = time.time()
    rr = api.get("/agent/events", params={"since": cur, "wait": wait})
    res[key] = (rr, time.time() - t)


th = threading.Thread(target=poll, args=("a",))
th.start()
time.sleep(1.5)
A.post(B + f"/api/tasks/{T1}/comments", json={"body": f"<@{CL}> ping"})
th.join(20)
rr, dt = res["a"]
check(rr.ok and rr.json()["data"] and rr.json()["data"][0]["event"] == "mention" and dt < 4, f"long-poll wakes up at once ({dt:.1f}s)")
cur = rr.json()["cursor"]
ths = [threading.Thread(target=poll, args=(k,), kwargs={"wait": 6}) for k in ("w1", "w2")]
for t_ in ths:
    t_.start()
time.sleep(1)
t0 = time.time()
r3 = cl.get("/agent/events", params={"since": cur, "wait": 6})
check(r3.ok and r3.json()["busy"] is True and time.time() - t0 < 2 and r3.headers.get("Retry-After"), "third waiter of one agent: busy at once")
check(A.get(B + "/api/state").ok and A.get(B + "/api/health").ok, "app still answers while agents wait")
for t_ in ths:
    t_.join(15)
check(all(res[k][0].ok and res[k][0].json()["data"] == [] for k in ("w1", "w2")), "waiters end empty")
check(cl.get("/agent/events", params={"wait": 61}).status_code == 400, "wait > 60: 400")

# ================================================================== kill switch + token rotation
cur = events(cl, 0)["cursor"]
n_hooks = len(hooks_log())
check(A.patch(B + f"/api/admin/agents/{CL}", json={"enabled": False}).ok, "pause the agent")
r = cl.get("/me")
check(r.status_code == 403 and "paused" in r.text, "paused: token refused")
A.post(B + f"/api/tasks/{T1}/comments", json={"body": f"<@{CL}> are you there?"})
check(dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=? AND id>?", (CL, cur))[0][0] == 0, "paused: no events recorded")
time.sleep(2)
check(len(hooks_log()) == n_hooks and dbx("SELECT enabled FROM webhooks WHERE agent=1 AND user_id=?", (CL,))[0][0] == 0, "paused: webhook off")
check(A.post(B + f"/api/agents/{CL}/chat", json={"body": "x"}).status_code == 409, "paused: no chat")
check(next(a for a in A.get(B + "/api/state").json()["agents"] if a["id"] == CL)["enabled"] is False, "state: paused")
check(A.patch(B + f"/api/admin/agents/{CL}", json={"enabled": True}).ok and cl.get("/me").ok, "resume")
r = A.post(B + f"/api/admin/agents/{CL}/token")
check(r.ok and cl.get("/me").status_code == 401, "new token: the old one stops")
cl = Api(r.json()["token"])
check(cl.get("/agent").json()["cursor"] == cur, "cursor survives")
r = A.post(B + f"/api/admin/agents/{CL}/test")
check(r.ok and r.json()["webhook"]["ok"] and events(cl, cur)["data"][-1]["event"] == "ping", "test: ping to queue + webhook")
r = A.post(B + f"/api/admin/agents/{CL}/secret")
check(r.ok and r.json()["secret"].startswith("whsec_") and r.json()["secret"] != SECRET, "new webhook secret")
check(not any(w["url"].endswith("/agent") for w in A.get(B + "/api/me/webhooks").json()["hooks"]), "agent hook not in user webhooks")
# a user webhook for comment.created is not delivered to the agent's hook as a second payload
check(A.patch(B + f"/api/admin/agents/{CL}", json={"webhook_url": ""}).ok and
      not next(a for a in A.get(B + "/api/admin/agents").json()["agents"] if a["id"] == CL)["webhook"], "remove the webhook (polling only)")
check(A.patch(B + f"/api/admin/agents/{CL}", json={"webhook_url": "ftp://x"}).status_code == 400, "bad webhook URL")
cur = events(cl, 0)["cursor"]

# ================================================================== shared list tags
r = A.post(B + f"/api/lists/{L}/tags", json={"name": "bug", "color": "#ff0000"})
check(r.status_code == 201 and r.json()["color"] == "#ff0000", "create list tag")
BUG = r.json()["id"]
check(A.post(B + f"/api/lists/{L}/tags", json={"name": "BUG"}).status_code == 409, "duplicate (case-insensitive): 409")
check(Vi.post(B + f"/api/lists/{L}/tags", json={"name": "v"}).status_code == 403, "viewer cannot create")
T7 = mk(Bo, title="Crash on export", list_id=L, ltags=["bug", "feature"], tags=["mine"])
st_b = Bo.get(B + "/api/state").json()
t7 = next(t for t in st_b["tasks"] if t["id"] == T7)
check(sorted(t7["ltags"]) == ["bug", "feature"] and t7["tags"] == ["mine"], "task: list tags + personal tags")
t7a = next(t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == T7)
check(sorted(t7a["ltags"]) == ["bug", "feature"] and t7a["tags"] == [], "alice sees the list tags, not bob's personal tag")
check([x["name"] for x in next(x for x in st_b["lists"] if x["id"] == L)["tags"]] == ["bug", "feature"], "state: list tags per list")
check(P.post(B + "/api/tasks", json={"title": "p", "list_id": L, "ltags": ["brandnew"]}).status_code == 400, "participant: no new list tag")
TPp = mk(P, title="pete's", list_id=L, ltags=["bug"])
check(next(t for t in P.get(B + "/api/state").json()["tasks"] if t["id"] == TPp)["ltags"] == ["bug"], "participant: existing list tag")
check(any(a["kind"] == "ltags" for a in A.get(B + f"/api/tasks/{T7}/timeline").json()["activity"]) is False, "created with tags: no extra history line")
A.patch(B + f"/api/tasks/{T7}", json={"ltags": ["bug"]})
check(any(a["kind"] == "ltags" and a["data"]["tags"] == ["bug"] for a in A.get(B + f"/api/tasks/{T7}/timeline").json()["activity"]), "change is in the history")
v7 = cl.get(f"/tasks/{T7}").json()
check(v7["list_tags"] == ["bug"] and v7["tags"] == [], "v1: list_tags")
r = cl.patch(f"/tasks/{T7}", json={"list_tags": ["bug", "agent-set"]})
check(r.ok and r.json()["list_tags"] == ["agent-set", "bug"] or sorted(r.json()["list_tags"]) == ["agent-set", "bug"], "agent sets list tags")
check({t["id"] for t in cl.get("/tasks", params={"list_id": L, "tag": "bug"}).json()["data"]} == {T7, TPp}, "v1 ?tag= matches list tags")
check({t["id"] for t in Bo.get(V + "/tasks", headers={"Authorization": "Bearer " + Bo.post(B + "/api/me/tokens", json={"name": "t"}).json()["token"]},
                                params={"tag": "mine"}).json()["data"]} == {T7}, "v1 ?tag= still matches personal tags")
check({t["id"] for t in cl.get("/tasks", params={"list_tag": "agent-set"}).json()["data"]} == {T7}, "v1 ?list_tag=")
lt = cl.get(f"/lists/{L}/tags").json()["data"]
check({x["name"]: x["tasks"] for x in lt}.get("bug") == 2, f"v1 list tags with counts {lt}")
tg = cl.get("/tags").json()["data"]
check(any(x["kind"] == "list" and x["name"] == "bug" and x["list_id"] == L for x in tg), "v1 tags: kind list")
r = cl.post(f"/lists/{L}/tags", json={"name": "from-agent", "color": "#00ff00"})
check(r.status_code == 201, "v1 create list tag")
check(cl.patch(f"/lists/{L}/tags/{r.json()['id']}", json={"color": "#0000ff"}).json()["color"] == "#0000ff", "v1 recolour")
check(cl.delete(f"/lists/{L}/tags/{r.json()['id']}").status_code == 204, "v1 delete")
check(ro.post(f"/lists/{L}/tags", json={"name": "nope"}).status_code == 403, "participant agent cannot create list tags")
check(cl.get(f"/lists/{PRIV}/tags").status_code == 404, "tags of an invisible list: 404")
# promote a personal tag
T8 = mk(Bo, title="Needs review", list_id=L, tags=["urgent"])
r = Bo.post(B + f"/api/lists/{L}/tags/promote", json={"tag": "urgent"})
check(r.ok and r.json()["count"] == 1, "promote personal -> list tag")
t8 = next(t for t in Bo.get(B + "/api/state").json()["tasks"] if t["id"] == T8)
check(t8["ltags"] == ["urgent"] and t8["tags"] == [], "now a list tag, the personal one is gone")
check(next(t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == T8)["ltags"] == ["urgent"], "everyone sees it")
check(Vi.post(B + f"/api/lists/{L}/tags/promote", json={"tag": "x"}).status_code == 403, "viewer cannot promote")
# rename, recolour, delete
check(A.patch(B + f"/api/list-tags/{BUG}", json={"name": "defect", "color": "#aa0000"}).ok, "rename list tag")
check(next(t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == T7)["ltags"][0] in ("agent-set", "defect"), "renamed on tasks")
check(Vi.patch(B + f"/api/list-tags/{BUG}", json={"name": "v"}).status_code == 403, "viewer cannot rename")
# move to another list: tags follow by name
L2 = A.post(B + "/api/lists", json={"name": "Film 2"}).json()["id"]
A.patch(B + f"/api/tasks/{T8}", json={"list_id": L2})
check(next(t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == T8)["ltags"] == ["urgent"], "moved: tag follows")
check(any(x["name"] == "urgent" for x in next(x for x in A.get(B + "/api/state").json()["lists"] if x["id"] == L2)["tags"]), "created in the target list")
r = A.delete(B + f"/api/list-tags/{BUG}")
check(r.ok and T7 in r.json()["ids"] and "defect" not in next(t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == T7)["ltags"], "delete list tag")

# ================================================================== tidy setting
check(Bo.patch(B + f"/api/lists/{L}", json={"agent_tidy": "suggest"}).status_code == 403, "member cannot set tidy")
check(A.patch(B + f"/api/lists/{PRIV}", json={"agent_tidy": "suggest"}).status_code == 409, "list without agent: 409")
check(A.patch(B + f"/api/lists/{L}", json={"agent_tidy": "sometimes"}).status_code == 400, "bad mode: 400")
check(A.patch(B + f"/api/lists/{L}", json={"agent_tidy": "suggest"}).ok, "owner sets suggest")
check(next(x for x in cl.get("/lists").json()["data"] if x["id"] == L)["agent_tidy"] == "suggest", "agent reads the setting (v1 lists)")
check(cl.patch(f"/lists/{L}", json={"agent_tidy": "auto"}).status_code in (403, 404, 405), "no v1 route to change it")
cur = events(cl, 0)["cursor"]
raw = "so we need to fix the export thing that crashes when the file is big and also check the codec"
T9 = mk(Bo, title=raw, list_id=L)
e = events(cl, cur)["data"]
check([x["event"] for x in e] == ["tidy"] and e[0]["data"]["mode"] == "suggest" and e[0]["data"]["task"]["id"] == T9, "tidy event")
check(not [x for x in events(ro, 0)["data"] if x["event"] == "tidy"], "participant agent (cannot change it): no tidy event")
cur = e[-1]["seq"] if e else cur
mk(A, title="sub", parent_id=T9)
check(not events(cl, cur)["data"], "subtasks: no tidy event")
T10 = cl.post("/tasks", json={"title": "agent's own", "list_id": L}).json()["id"]
check(not events(cl, cur)["data"], "the agent's own task: no tidy event")
sug = {"title": "Fix export crash on large files", "notes": "- check codec", "list_tags": ["export"], "priority": "high",
       "section_id": sec["Ideas"]}
r = cl.post(f"/tasks/{T9}/comments", json={"body": "Suggestion: shorter title", "suggestion": sug})
check(r.status_code == 201 and r.json()["suggestion"]["state"] == "open", "agent posts a suggestion " + r.text[:200])
K9 = r.json()["id"]
check(Bo.post(B + f"/api/tasks/{T9}/comments", json={"body": "x", "suggestion": sug}).status_code == 403, "people cannot post suggestions")
check(cl.post(f"/tasks/{T9}/comments", json={"body": "x", "suggestion": {"color": "red"}}).status_code == 400, "unknown suggestion field")
check(Vi.post(B + f"/api/comments/{K9}/reactions", json={"emoji": "up"}).json()["applied"] is False, "viewer 👍 does not apply")
r = Bo.post(B + f"/api/comments/{K9}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["applied"] and r.json()["suggestion"]["state"] == "applied", "member 👍 applies the suggestion")
t9 = next(t for t in Bo.get(B + "/api/state").json()["tasks"] if t["id"] == T9)
check(t9["title"] == sug["title"] and t9["content"].startswith(f"**Original (Bob):** {raw}") and "- check codec" in t9["content"]
      and t9["priority"] == 5 and t9["ltags"] == ["export"] and t9["section_id"] == sec["Ideas"], f"applied: {t9['content'][:120]!r}")
check(any(a["kind"] == "tidy" for a in Bo.get(B + f"/api/tasks/{T9}/timeline").json()["activity"]), "tidy in the history")
e = events(cl, cur)["data"]
check(e and e[-1]["event"] == "reaction" and e[-1]["data"]["applied"] is True, "agent learns it was applied")
check(Bo.post(B + f"/api/comments/{K9}/apply").status_code == 409, "applied once only")
# the Apply button + second tidy keeps the original only once
K9b = cl.post(f"/tasks/{T9}/comments", json={"body": "again", "suggestion": {"title": "Fix export crash", "notes": "more"}}).json()["id"]
check(Vi.post(B + f"/api/comments/{K9b}/apply").status_code == 403, "viewer cannot apply")
r = Bo.post(B + f"/api/comments/{K9b}/apply")
check(r.ok and r.json()["task"]["title"] == "Fix export crash" and r.json()["task"]["content"].count("**Original (") == 1, "Apply keeps one original")
K9c = cl.post(f"/tasks/{T9}/comments", json={"body": "nope", "suggestion": {"title": "Something else"}}).json()["id"]
r = Bo.post(B + f"/api/comments/{K9c}/reactions", json={"emoji": "down"})
check(r.json()["suggestion"]["state"] == "rejected" and next(t for t in Bo.get(B + "/api/state").json()["tasks"] if t["id"] == T9)["title"] == "Fix export crash",
      "👎 rejects the suggestion")
# auto
check(cl.post(f"/tasks/{T9}/tidy", json={"title": "x"}).status_code == 409, "tidy endpoint needs auto")
A.patch(B + f"/api/lists/{L}", json={"agent_tidy": "auto"})
T11 = mk(Bo, title="remember to call the composer about the temp music license soon", list_id=L)
r = cl.post(f"/tasks/{T11}/tidy", json={"title": "Call composer about temp music license", "list_tags": ["music"]})
check(r.ok and r.json()["title"].startswith("Call composer") and r.json()["notes"].startswith("**Original (Bob):** remember to call")
      and r.json()["list_tags"] == ["music"], "auto tidy by the agent")
check(Api(Bo.post(B + "/api/me/tokens", json={"name": "t2", "scopes": ["read", "write"]}).json()["token"]).post(f"/tasks/{T11}/tidy", json={"title": "x"}).status_code == 403,
      "people cannot use the tidy endpoint")
check(ro.post(f"/tasks/{T11}/tidy", json={"title": "x"}).status_code == 404, "participant agent: not its task")
A.patch(B + f"/api/lists/{L}", json={"agent_tidy": "off"})
check(cl.post(f"/tasks/{T9}/comments", json={"body": "x", "suggestion": {"title": "y"}}).status_code == 409, "tidy off: no suggestions")

# ================================================================== spec + misc
spec = requests.get(V + "/openapi.json").json()
for p_ in ("/agent", "/agent/status", "/agent/events", "/agent/jobs", "/agent/jobs/{id}", "/agent/chats", "/agent/chats/{id}", "/agents",
           "/tasks/{id}/tidy", "/comments/{id}/reactions", "/comments/{id}/reactions/{emoji}", "/lists/{id}/tags", "/lists/{id}/tags/{tag_id}"):
    check(p_ in spec["paths"], "spec documents " + p_)
check(spec["info"]["license"]["identifier"] == "AGPL-3.0-only", "spec license AGPL")
# deleting an agent user: its events, jobs, chat go with it
check(A.delete(B + f"/api/users/{RO}").ok, "delete agent without own lists")
check(not dbx("SELECT 1 FROM agents WHERE user_id=?", (RO,)) and not dbx("SELECT 1 FROM agent_events WHERE agent_id=?", (RO,)), "agent rows gone")

print(f"p200_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
