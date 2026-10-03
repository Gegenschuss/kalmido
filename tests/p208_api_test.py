#!/usr/bin/env python3
"""2.0.8 API tests.
 - #331 push buttons: a comment / mention push carries Reply + Done (Reply first, /#reply/<id>, the task id for the
   background Done), German titles for a German user, a completed task only Reply, the burst summary of a comment too;
   the reminder keeps Done + Snooze (webpush_test.py)
 - #333 agent API speedups: task events (mention, comment, assigned, tidy, reaction, wake) carry the task's newest 20
   comments (oldest first, comments_total, long texts cut + truncated) and the list's sections + agent_tidy; unassigned
   from a task the agent can no longer see carries neither; GET /api/v1/lists has every list's sections (a participant
   only the sections with its tasks); GET /api/v1/tasks?fields=compact (exact keys, 400 for another value, full default)
Starts its OWN container (start.sh) with the fake push service (stub_webpush.py on 127.0.0.1:9997) inside it.
usage: p208_api_test.py <datadir>"""
import base64
import json
import os
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


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def wp_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "webpush.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def clear():
    try:
        os.remove(os.path.join(DATA, "webpush.log"))
    except FileNotFoundError:
        pass


def wait_for(fn, n=1, t=10.0):
    t0 = time.time()
    while time.time() - t0 < t:
        x = fn()
        if len(x) >= n:
            time.sleep(0.3)
            return fn()
        time.sleep(0.2)
    return fn()


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


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def get(self, p, **k):
        return requests.get(V + p, headers=self.h, timeout=60, **k)


env = dict(os.environ, EXTRA=" ".join(["-e KALMIDO_WEBPUSH_HOSTS=" + STUB]))
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["cp", os.path.join(N, "stub_webpush.py"), DATA])
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webpush.py"])
time.sleep(0.7)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ids = {"alice": 1}
for u in ("bob", "gert"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ge = sess("bob"), sess("gert")
A.patch(B + "/api/settings", json={"lang": "en"})
Bo.patch(B + "/api/settings", json={"lang": "en"})
Ge.patch(B + "/api/settings", json={"lang": "de"})

# ================================================================== #331 Reply + Done on comment pushes
phone = Browser("/push/alice")
gphone = Browser("/push/gert")
check(A.post(B + "/api/push/subs", json=phone.sub("Chrome on Android")).ok, "alice subscribes")
check(Ge.post(B + "/api/push/subs", json=gphone.sub("Chrome on Android")).ok, "gert subscribes")
TEAM = A.post(B + "/api/lists", json={"name": "Team", "kind": "project"}).json()["id"]
for u in ("bob", "gert"):
    assert A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": ids[u], "role": "edit"}).ok
X = A.post(B + "/api/tasks", json={"title": "Task X", "list_id": TEAM}).json()["id"]
Y = Ge.post(B + "/api/tasks", json={"title": "Aufgabe Y", "list_id": TEAM}).json()["id"]
DONE = A.post(B + "/api/tasks", json={"title": "Old task", "list_id": TEAM}).json()["id"]
A.post(B + f"/api/tasks/{DONE}/complete")
time.sleep(3.5)
clear()
Bo.post(B + f"/api/tasks/{X}/comments", json={"body": "look at X"})
n = wait_for(phone.notes, 1)
p = n[0] if n else {}
acts = p.get("actions") or []
check([a["action"] for a in acts] == ["reply", "done"], f"comment push: Reply + Done, Reply first: {acts}")
check(acts and acts[0]["url"] == f"/#reply/{X}" and acts[0]["title"] == "Reply" and acts[1]["url"] == f"/#done/{X}" and acts[1]["title"] == "Done",
      f"urls + titles: {acts}")
check(p.get("task") == X and "due" not in p, f"the task id for the background Done (no expect_due): {p.get('task')}")
# mention of a German user -> Antworten / Erledigt
clear()
Bo.post(B + f"/api/tasks/{Y}/comments", json={"body": f"<@{ids['gert']}> bitte schauen"})
n = wait_for(gphone.notes, 1)
acts = (n[0].get("actions") if n else None) or []
check([a["action"] for a in acts] == ["reply", "done"] and acts[0]["title"] == "Antworten", f"mention push, German: {acts}")
# a completed task: Reply only
clear()
Bo.post(B + f"/api/tasks/{DONE}/comments", json={"body": "one more thing"})
n = wait_for(phone.notes, 1)
acts = (n[0].get("actions") if n else None) or []
check([a["action"] for a in acts] == ["reply"], f"completed task: Reply only: {acts}")
# the burst summary (a second comment inside the push gap) gets the buttons too
time.sleep(3.5)
clear()
Bo.post(B + f"/api/tasks/{X}/comments", json={"body": "first"})
wait_for(phone.notes, 1)
Bo.post(B + f"/api/tasks/{X}/comments", json={"body": "second, inside the gap"})
n = wait_for(phone.notes, 2, t=15)
check(len(n) >= 2 and [a["action"] for a in n[-1].get("actions") or []] == ["reply", "done"] and "more comment" in n[-1]["body"],
      f"burst summary with Reply + Done: {n[-1] if n else None}")
# an assignment push stays without buttons (only comments / mentions and reminders have them)
clear()
Bo.patch(B + f"/api/tasks/{X}", json={"assignee_id": ids["alice"]})
n = wait_for(phone.notes, 1)
check(n and not n[0].get("actions"), f"assignment push: no buttons: {n[0] if n else None}")

# ================================================================== #333 agent: events with comments, sections, tidy
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
assert r.status_code == 201, r.text
CL, TOK = r.json()["id"], r.json()["token"]
cl = Api(TOK)
PROJ = A.post(B + "/api/lists", json={"name": "Website", "kind": "project"}).json()["id"]
S1 = A.post(B + "/api/sections", json={"list_id": PROJ, "name": "Ideas"}).json()["id"]
S2 = A.post(B + "/api/sections", json={"list_id": PROJ, "name": "Doing"}).json()["id"]
assert A.put(B + f"/api/lists/{PROJ}/members", json={"user_id": CL, "role": "edit"}).ok
T = A.post(B + "/api/tasks", json={"title": "Fix login", "list_id": PROJ, "section_id": S1}).json()["id"]
for i in range(22):
    A.post(B + f"/api/tasks/{T}/comments", json={"body": f"note {i}"})
A.post(B + f"/api/tasks/{T}/comments", json={"body": "x" * 2500})
cur = cl.get("/agent").json()["cursor"]
A.post(B + f"/api/tasks/{T}/comments", json={"body": f"<@{CL}> please have a look"})


def events(since, want, t=8.0):
    t0, out = time.time(), []
    while time.time() - t0 < t:
        j = cl.get("/agent/events", params={"since": since}).json()
        out = [e for e in j.get("data", []) if e["event"] in want]
        if out:
            return out, j.get("cursor", since)
        time.sleep(0.3)
    return out, since


ev, cur2 = events(cur, {"mention"})
d = ev[0]["data"] if ev else {}
cm = d.get("task", {}).get("comments") or []
check(len(cm) == 20 and d["task"].get("comments_total") == 24, f"mention: the newest 20 of 24 comments: {len(cm)}, {d.get('task', {}).get('comments_total')}")
check(cm and cm[-1]["text"].startswith("@Claude") and cm[0]["text"] == "note 4" and cm[-1]["id"] > cm[0]["id"], "oldest first, the new comment last: "
      + (cm[0]["text"] if cm else ""))
long_ = [c for c in cm if c.get("truncated")]
check(len(long_) == 1 and len(long_[0]["text"]) == 2000, "a text over 2,000 characters is cut and marked")
check(cm and set(cm[0]) >= {"id", "author", "text", "created_at", "edited_at", "attachments"} and cm[0]["author"] == {"id": 1, "name": "Alice", "agent": False},
      f"comment shape: {cm[0] if cm else None}")
check(d.get("list", {}).get("sections") == [{"id": S1, "name": "Ideas"}, {"id": S2, "name": "Doing"}] and d["list"].get("agent_tidy") == "off",
      f"list with sections + agent_tidy: {d.get('list')}")
check(d.get("comment", {}).get("text", "").startswith("@Claude"), "the triggering comment stays in data.comment")
# assigned
A.patch(B + f"/api/tasks/{T}", json={"assignee_id": CL})
ev, cur3 = events(cur2, {"assigned"})
check(ev and len(ev[0]["data"]["task"].get("comments") or []) == 20 and ev[0]["data"]["list"].get("sections"), "assigned: comments + sections")
# tidy: mode suggest, a new entry by a person
assert A.patch(B + f"/api/lists/{PROJ}", json={"agent_tidy": "suggest"}).ok
A.post(B + "/api/tasks", json={"title": "please also check the password reset mail it looks broken on mobile", "list_id": PROJ})
ev, cur4 = events(cur3, {"tidy"})
check(ev and ev[0]["data"]["mode"] == "suggest" and ev[0]["data"]["list"]["agent_tidy"] == "suggest" and len(ev[0]["data"]["list"]["sections"]) == 2
      and ev[0]["data"]["task"]["comments"] == [] and ev[0]["data"]["task"]["comments_total"] == 0, f"tidy: mode, sections, no comments yet: {ev[0]['data'] if ev else None}")
# wake from the task panel
r = A.post(B + f"/api/tasks/{T}/wake", json={})
ev, cur5 = events(cur4, {"wake"})
check(r.ok and ev and len(ev[0]["data"]["task"]["comments"]) == 20 and ev[0]["data"]["list"]["sections"], f"wake with a task: comments + sections ({r.status_code})")
# reaction on the agent's comment
aco = requests.post(V + f"/tasks/{T}/comments", headers=cl.h, json={"body": "Plan: do it. Shall I?"}).json()["id"]
A.post(B + f"/api/comments/{aco}/reactions", json={"emoji": "up"})
ev, cur6 = events(cur5, {"reaction"})
check(ev and ev[0]["data"]["task"]["comments"][-1]["id"] == aco and ev[0]["data"]["task"]["comments"][-1]["author"]["agent"] is True
      and ev[0]["data"]["comment"]["id"] == aco, "reaction: the agent's own comment is last, marked as agent")
# participant agent: unassigned from a task it can no longer see -> no comments, no sections
PART = A.post(B + "/api/lists", json={"name": "Private-ish"}).json()["id"]
P1 = A.post(B + "/api/sections", json={"list_id": PART, "name": "Mine"}).json()["id"]
P2 = A.post(B + "/api/sections", json={"list_id": PART, "name": "Others"}).json()["id"]
assert A.put(B + f"/api/lists/{PART}/members", json={"user_id": CL, "role": "participant"}).ok
Q = A.post(B + "/api/tasks", json={"title": "For the agent", "list_id": PART, "section_id": P1, "assignee_id": CL}).json()["id"]
A.post(B + "/api/tasks", json={"title": "Not for it", "list_id": PART, "section_id": P2})
A.post(B + f"/api/tasks/{Q}/comments", json={"body": "context"})
ev, cur7 = events(cur6, {"assigned"})
check(ev and ev[-1]["data"]["list"]["sections"] == [{"id": P1, "name": "Mine"}] and ev[-1]["data"]["task"]["comments"] == [],
      f"participant: only the section with its task: {ev[-1]['data']['list'] if ev else None}")
A.patch(B + f"/api/tasks/{Q}", json={"assignee_id": None})
ev, _ = events(cur7, {"unassigned"})
check(ev and "comments" not in ev[0]["data"]["task"] and "sections" not in ev[0]["data"]["list"], f"unassigned without sight: no comments / sections: {ev[0]['data'] if ev else None}")

# ================================================================== #333 GET /api/v1/lists with sections, compact tasks
ls = {x["id"]: x for x in cl.get("/lists").json()["data"]}
check(ls[PROJ]["sections"] == [{"id": S1, "name": "Ideas"}, {"id": S2, "name": "Doing"}] and ls[PROJ]["agent_tidy"] == "suggest", "list_lists: sections + tidy")
check(ls[PART]["sections"] == [], f"participant list without its task: no sections: {ls[PART]['sections']}")
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read"]}).json()["token"]
me = Api(tok)
ul = me.get("/lists").json()["data"]
check(all(isinstance(x.get("sections"), list) for x in ul) and next(x for x in ul if x["id"] == PART)["sections"] == [{"id": P1, "name": "Mine"}, {"id": P2, "name": "Others"}],
      "a person's lists: every list with its sections")
full = me.get("/tasks", params={"list_id": PROJ}).json()["data"]
comp = me.get("/tasks", params={"list_id": PROJ, "fields": "compact"}).json()["data"]
check(full and "notes" in full[0] and "created_at" in full[0], "default: full tasks")
KEYS = {"id", "title", "list_id", "section_id", "parent_id", "status", "due", "due_time", "priority", "tags", "list_tags", "assignee_id"}
check(comp and all(set(x) == KEYS for x in comp) and [x["id"] for x in comp] == [x["id"] for x in full], f"compact: exactly the short keys: {sorted(comp[0]) if comp else None}")
check(me.get("/tasks", params={"fields": "full"}).ok and me.get("/tasks", params={"fields": "all"}).status_code == 400, "fields=full ok, another value 400")
spec = requests.get(V + "/openapi.json").json()
check(any(p_.get("name") == "fields" for p_ in spec["paths"]["/tasks"]["get"]["parameters"]), "OpenAPI documents fields")

print(f"p208_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
