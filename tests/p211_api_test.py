#!/usr/bin/env python3
"""2.1.1 API tests (#326): model usage of agents + limits.
 - POST /api/v1/agent/usage: agent tokens only (a person's token 403), validation (model, numbers, cost, unknown fields, note
   at most 200 characters, a task / list the agent does not see, a task in another list, someone else's job), list_id taken
   from the task, only numbers + ids stored (no other column)
 - GET /api/v1/agent/usage: group day / task / list / model, totals, from / to validation, the limit state
 - GET /api/agents/usage (the dashboard): admins every agent, others only the agents they share a list with and only usage
   in lists they see; a participant only their tasks; lists / tasks the viewer cannot see counted without a name;
   today / 7 d / 30 d totals, the days, top tasks, lists, models; agents get 403
 - "ai_usage" on tasks in /api/state only for who sees the task
 - limits (admins): validation, soft limit -> News + push to the admins at 80 % and 100 % (once per period, not to others),
   hard limit -> 429 with a clear message + Retry-After for every call except usage / status / GET /agent, "limit reached"
   in the agent's status (for people too), raising it lets calls through again, cost metric, month period, the
   notification setting "usage", removing the limits
 - the OpenAPI spec documents /agent/usage; deleting the agent removes its rows
Starts its OWN container (start.sh) with the fake push service (stub_webpush.py, 127.0.0.1:9997) inside.
usage: p211_api_test.py <datadir>"""
import base64
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date, timedelta

import http_ece
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]


def legacy_agent(lid, aid, role):  # 2.26.0: one agent per list -- a second agent as in a list from before the update
    c_ = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c_.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')", (lid, aid, role, role))
    c_.commit()
    c_.close()


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


def settle(fn, t=5.0):
    t0, last = time.time(), None
    while time.time() - t0 < t:
        x = fn()
        if x == last and time.time() - t0 > 1.2:
            return x
        last = x
        time.sleep(0.3)
    return fn()


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=30, **k)

    def get(self, p, **k):
        return self.req("GET", p, **k)

    def post(self, p, **k):
        return self.req("POST", p, **k)


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
ids = {"alice": 1}
for u in ("bob", "gert"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ge = sess("bob"), sess("gert")
for x in (A, Bo, Ge):
    x.patch(B + "/api/settings", json={"lang": "en"})
aphone, bphone = Browser("/push/alice"), Browser("/push/bob")
check(A.post(B + "/api/push/subs", json=aphone.sub("Phone")).ok and Bo.post(B + "/api/push/subs", json=bphone.sub("Phone")).ok, "subscribed")

r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
AG, AGTOK = r.json()["id"], r.json()["token"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "codex", "display_name": "Codex"})
AG2, AG2TOK = r.json()["id"], r.json()["token"]
cl, cx = Api(AGTOK), Api(AG2TOK)

TEAM = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]
SECRET = A.post(B + "/api/lists", json={"name": "Secret"}).json()["id"]
BOBL = Bo.post(B + "/api/lists", json={"name": "Bobs"}).json()["id"]
for lid, s, who, role in ((TEAM, A, "bob", "edit"), (TEAM, A, "gert", "participant")):
    assert s.put(B + f"/api/lists/{lid}/members", json={"user_id": ids[who], "role": role}).ok
for lid, s in ((TEAM, A), (SECRET, A), (BOBL, Bo)):
    assert s.put(B + f"/api/lists/{lid}/members", json={"user_id": AG, "role": "edit"}).ok
legacy_agent(TEAM, AG2, "edit")
for lid, s in ((TEAM, A), (SECRET, A), (BOBL, Bo)):  # 2.26.0: members may use the agents (list switch, default off)
    assert s.patch(B + f"/api/lists/{lid}", json={"agent_members": True, "agent_peers": True}).ok
T1 = A.post(B + "/api/tasks", json={"title": "Write the release notes", "list_id": TEAM}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Gert's task", "list_id": TEAM, "assignee_id": ids["gert"]}).json()["id"]
TS = A.post(B + "/api/tasks", json={"title": "Secret plan", "list_id": SECRET}).json()["id"]
TB = Bo.post(B + "/api/tasks", json={"title": "Bobs private thing", "list_id": BOBL}).json()["id"]
PRIV = A.post(B + "/api/tasks", json={"title": "Alice only", "list_id": A.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]}).json()["id"]

# ================================================================== reporting
ok = {"model": "claude-test-1", "input_tokens": 100, "output_tokens": 50}
BAD = [({}, "empty"), ({"model": "x"}, "tokens missing"), ({**ok, "model": ""}, "empty model"), ({**ok, "model": "m" * 101}, "model too long"),
       ({**ok, "model": "a\nb"}, "control character"), ({**ok, "input_tokens": -1}, "negative"), ({**ok, "output_tokens": True}, "bool"),
       ({**ok, "input_tokens": 1.5}, "float tokens"), ({**ok, "input_tokens": "10"}, "string tokens"), ({**ok, "cache_read_tokens": 10 ** 11}, "too big"),
       ({**ok, "cost_usd": "1"}, "string cost"), ({**ok, "cost_usd": -0.1}, "negative cost"), ({**ok, "prompt": "hello"}, "unknown field (no prompt text)"),
       ({**ok, "note": "n" * 201}, "note > 200"), ({**ok, "task_id": PRIV}, "a task it does not see"), ({**ok, "task_id": 99999}, "missing task"),
       ({**ok, "task_id": T1, "list_id": SECRET}, "task in another list"), ({**ok, "list_id": ids["alice"] + 900}, "unknown list"),
       ({**ok, "task_id": "x"}, "task id text")]
for b, what in BAD:
    r = cl.post("/agent/usage", json=b)
    check(r.status_code == 400 and r.json().get("error", {}).get("message"), f"400: {what} ({r.status_code} {r.text[:120]})")
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
check(Api(tok).post("/agent/usage", json=ok).status_code == 403, "a person's token: 403")
job = cl.post("/agent/jobs", json={"title": "Notes"}).json()["id"]
job2 = cx.post("/agent/jobs", json={"title": "Other"}).json()["id"]
check(cl.post("/agent/usage", json={**ok, "job_id": job2}).status_code == 400, "someone else's job: 400")

r = cl.post("/agent/usage", json={**ok, "input_tokens": 1000, "output_tokens": 200, "cache_read_tokens": 5000, "cache_write_tokens": 300,
                                  "cost_usd": 0.5, "task_id": T1, "job_id": job, "note": "session 1"})
j = r.json()
check(r.status_code == 201 and j["list_id"] == TEAM and j["task_id"] == T1 and j["day"] == date.today().isoformat() and j["limit"] is None,
      f"report: list from the task: {r.text[:300]}")
check(cl.post("/agent/usage", json={**ok, "input_tokens": 400, "output_tokens": 100, "task_id": T2}).status_code == 201, "report on T2")
check(cl.post("/agent/usage", json={**ok, "model": "claude-other", "input_tokens": 70, "output_tokens": 30, "task_id": TS}).status_code == 201, "report on the secret list")
check(cl.post("/agent/usage", json={**ok, "input_tokens": 900, "output_tokens": 100, "task_id": TB, "cost_usd": 0.25}).status_code == 201, "report on bob's list")
check(cl.post("/agent/usage", json={**ok, "input_tokens": 10, "output_tokens": 10, "list_id": TEAM}).status_code == 201, "report on a list only")
check(cl.post("/agent/usage", json={**ok, "input_tokens": 5, "output_tokens": 5}).status_code == 201, "report without task / list")
check(cx.post("/agent/usage", json={**ok, "model": "gpt-x", "input_tokens": 60, "output_tokens": 40, "task_id": T1}).status_code == 201, "codex reports")
con = sqlite3.connect(os.path.join(DATA, "tasks.db"))
cols = [x[1] for x in con.execute("PRAGMA table_info(agent_usage)")]
check(cols == ["id", "agent_id", "model", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_usd", "task_id",
               "list_id", "job_id", "note", "day", "created_at"], f"only numbers + ids stored: {cols}")
con.close()

# ================================================================== the agent's own view
j = cl.get("/agent/usage").json()
tot = j["totals"]
check(tot["input"] == 2385 and tot["output"] == 445 and tot["cache_read"] == 5000 and tot["cache_write"] == 300 and tot["tokens"] == 2385 + 445 + 300
      and tot["calls"] == 6 and abs(tot["cost"] - 0.75) < 1e-9, f"totals: {tot}")
check(j["group"] == "day" and [d["day"] for d in j["data"]] == [date.today().isoformat()], "group day")
j = cl.get("/agent/usage", params={"group": "task"}).json()
bt = {d["task_id"]: d for d in j["data"]}
check(bt[T1]["title"] == "Write the release notes" and bt[T1]["tokens"] == 1500 and None in bt, f"group task: {j['data'][:2]}")
j = cl.get("/agent/usage", params={"group": "list"}).json()
check({d["list_id"]: d["name"] for d in j["data"]}.get(SECRET) == "Secret", "group list with names")
j = cl.get("/agent/usage", params={"group": "model"}).json()
check({d["model"] for d in j["data"]} == {"claude-test-1", "claude-other"}, "group model")
check(cl.get("/agent/usage", params={"from": (date.today() + timedelta(days=1)).isoformat()}).status_code == 400, "from after to: 400")
check(cl.get("/agent/usage", params={"group": "week"}).status_code == 400, "bad group: 400")
check(cl.get("/agent/usage", params={"from": "2020-01-01", "to": "2022-01-01"}).status_code == 400, "range > 366 days: 400")
check(cl.get("/agent/usage", params={"x": "1"}).status_code == 400, "unknown parameter: 400")
check(Api(tok).get("/agent/usage").status_code == 403, "a person's token cannot read it")
j = cl.get("/agent/usage", params={"from": "2030-01-01", "to": "2030-01-31"}).json()
check(j["data"] == [] and j["totals"]["calls"] == 0 and j["totals"]["cost"] is None, "empty range")

# ================================================================== the dashboard
d = A.get(B + "/api/agents/usage").json()
ag = {a["id"]: a for a in d["agents"]}
check(d["admin"] and set(ag) == {AG, AG2} and ag[AG]["totals"]["today"]["tokens"] == 3130 and ag[AG]["totals"]["d30"]["calls"] == 6
      and ag[AG2]["totals"]["d7"]["tokens"] == 100 and "limit" in ag[AG], f"admin: every agent, totals: {ag.get(AG, {}).get('totals')}")
check(len(d["per_day"]) == 30 and d["per_day"][-1]["day"] == date.today().isoformat() and d["per_day"][-1]["tokens"] == 3230, "30 days, today last")
tk = {t["task_id"]: t for t in d["tasks"]}
check(tk[T1]["tokens"] == 1600 and tk[T1]["title"] == "Write the release notes" and d["tasks"][0]["task_id"] == T1, f"top tasks: {d['tasks'][:3]}")
check(None in tk and tk[None]["hidden"] and "Bobs private thing" not in json.dumps(d), "admin: bob's task counted without its title")
ls = d["lists"]
check(any(x.get("hidden") for x in ls) and any(x.get("none") for x in ls) and "Bobs" not in json.dumps(ls), f"admin: lists I cannot see without a name: {ls}")
check(d["cost"] is True and {m["model"] for m in d["models"]} == {"claude-test-1", "claude-other", "gpt-x"}, "cost flag + models")
d1 = A.get(B + "/api/agents/usage", params={"agent_id": AG2, "days": 7}).json()
check(len(d1["per_day"]) == 7 and d1["per_day"][-1]["tokens"] == 100 and [m["model"] for m in d1["models"]] == ["gpt-x"], "one agent, 7 days")
check(A.get(B + "/api/agents/usage", params={"days": 3}).status_code == 400, "days < 7: 400")
d = Bo.get(B + "/api/agents/usage").json()
ag = {a["id"]: a for a in d["agents"]}
# bob sees TEAM (T1 1500 + T2 500 + list-only 20) and his own list (1000): not SECRET, not the unattributed row
check(not d["admin"] and set(ag) == {AG, AG2} and ag[AG]["totals"]["today"]["tokens"] == 3020 and "limit" not in ag[AG], f"bob: {ag.get(AG)}")
check("Secret plan" not in json.dumps(d) and "claude-other" not in json.dumps(d) and not any(x.get("hidden") for x in d["lists"]),
      "bob: nothing of the secret list, not even its model")
check({t["task_id"] for t in d["tasks"]} == {T1, T2, TB}, f"bob: his top tasks {d['tasks']}")
d = Ge.get(B + "/api/agents/usage").json()
ag = {a["id"]: a for a in d["agents"]}
check(ag[AG]["totals"]["today"]["tokens"] == 500 and [t["task_id"] for t in d["tasks"]] == [T2], f"participant gert: only his task: {d['tasks']}")
check(requests.get(B + "/api/agents/usage", headers={**H, "Authorization": "Bearer " + AGTOK}).status_code in (401, 403), "agents: not the dashboard")

# the task panel
st = {t["id"]: t for t in Bo.get(B + "/api/state").json()["tasks"]}
check(st[T1]["ai_usage"]["tokens"] == 1600 and st[T1]["ai_usage"]["calls"] == 2 and abs(st[T1]["ai_usage"]["cost"] - 0.5) < 1e-9, f"ai_usage: {st[T1].get('ai_usage')}")
check(st[TB]["ai_usage"]["tokens"] == 1000, "bob's own task")
st = {t["id"]: t for t in Ge.get(B + "/api/state").json()["tasks"]}
check(T1 not in st and st[T2]["ai_usage"]["tokens"] == 500, "participant: only on his task")
st = {t["id"]: t for t in A.get(B + "/api/state").json()["tasks"]}
check(TB not in st and "ai_usage" not in st[PRIV], "alice: not bob's task, nothing on tasks without usage")

# ================================================================== limits
for bad, what in (({"period": "week", "soft": 10}, "period"), ({"metric": "joules", "soft": 1}, "metric"), ({"soft": -1}, "negative"),
                  ({"soft": 10, "hard": 5}, "soft > hard"), ({"soft": "10"}, "text"), ({"soft": 1, "x": 1}, "unknown key"), ([1], "list")):
    check(A.patch(B + f"/api/admin/agents/{AG}", json={"limits": bad}).status_code == 400, f"limits 400: {what}")
check(Bo.patch(B + f"/api/admin/agents/{AG}", json={"limits": {"soft": 10}}).status_code == 403, "limits: admins only")
# today so far 3130 tokens (input + output + cache writes). soft 3600 -> 80 % = 2880 is already passed: the next report alerts
r = A.patch(B + f"/api/admin/agents/{AG}", json={"limits": {"period": "day", "metric": "tokens", "soft": 3600, "hard": 5000}})
j = r.json()
check(r.ok and j["limits"] == {"period": "day", "metric": "tokens", "soft": 3600, "hard": 5000} and j["usage"]["used"] == 3130
      and not j["usage"]["reached"], f"limits set: {j.get('limits')} {j.get('usage')}")
time.sleep(3.2)
r = cl.post("/agent/usage", json={**ok, "input_tokens": 10, "output_tokens": 10})
check(r.json()["limit"]["soft_pct"] > 80 and not r.json()["limit"]["soft_reached"], "report answers with the limit state")
pa = settle(aphone.notes)
nw = [x for x in A.get(B + "/api/news").json()["items"] if x["kind"] == "usage"]
check(len(pa) == 1 and pa[0]["title"] == "Claude: 80 % of the usage limit" and "3,150 tokens / 3,600 tokens" in pa[0]["body"], f"80 % push to the admin: {pa}")
check(len(nw) == 1 and nw[0]["data"]["level"] == "soft80" and nw[0]["actor_id"] == AG and nw[0]["task_id"] is None, f"80 % News: {nw}")
check(not [x for x in Bo.get(B + "/api/news").json()["items"] if x["kind"] == "usage"] and not settle(bphone.notes, 2), "not to bob (no admin)")
cl.post("/agent/usage", json={**ok, "input_tokens": 10, "output_tokens": 10})
time.sleep(1.5)
check(len([x for x in A.get(B + "/api/news").json()["items"] if x["kind"] == "usage"]) == 1, "80 % only once")
cl.post("/agent/usage", json={**ok, "input_tokens": 500, "output_tokens": 0})
nw = [x for x in A.get(B + "/api/news").json()["items"] if x["kind"] == "usage"]
check(len(nw) == 2 and nw[0]["data"]["level"] == "soft100", f"100 % of the soft limit: {[x['data'] for x in nw]}")
check(cl.get("/lists").ok, "soft limit: calls still work")
cl.post("/agent/usage", json={**ok, "input_tokens": 2000, "output_tokens": 0})
nw = [x for x in A.get(B + "/api/news").json()["items"] if x["kind"] == "usage"]
check(len(nw) == 3 and nw[0]["data"]["level"] == "hard" and nw[0]["data"]["limit"] == 5000, "hard limit: News")
r = cl.get("/lists")
check(r.status_code == 429 and "Usage limit reached" in r.json()["error"]["message"] and "today" in r.json()["error"]["message"]
      and int(r.headers.get("Retry-After", "0")) >= 60, f"hard limit: 429 + message + Retry-After ({r.status_code} {r.text[:200]})")
check(cl.post(f"/tasks/{T1}/comments", json={"body": "x"}).status_code == 429 and cl.get("/agent/events").status_code == 429, "writes and events refused too")
check(cl.post("/agent/usage", json={**ok}).status_code == 201, "reporting usage still works")
check(cl.req("PUT", "/agent/status", json={"status": "idle", "text": "over the limit"}).ok, "the status still works")
me_ = cl.get("/agent").json()
check(me_["limit_reached"] is True and me_["usage_limit"]["reached"] is True, "GET /agent: limit reached")
check(cx.get("/lists").ok, "the other agent is not affected")
check([a for a in Bo.get(B + "/api/agents").json()["agents"] if a["id"] == AG][0]["limit_reached"] is True, "people see 'limit reached'")
check({a["id"]: a for a in Bo.get(B + "/api/agents/usage").json()["agents"]}[AG]["limit_reached"] is True, "dashboard: limit reached")
pa = settle(aphone.notes)
check([p["title"] for p in pa][-1] == "Claude: usage limit reached, calls blocked", f"hard limit push: {[p['title'] for p in pa]}")
A.patch(B + f"/api/admin/agents/{AG}", json={"limits": {"period": "day", "metric": "tokens", "soft": 3600, "hard": 10 ** 6}})
check(cl.get("/lists").ok, "an admin raises the hard limit: calls work again")
A.patch(B + f"/api/admin/agents/{AG}", json={"limits": {"period": "day", "metric": "tokens", "hard": 1000}})
check(cl.get("/lists").status_code == 429, "lowered again: refused")
# cost metric, month period
A.patch(B + f"/api/admin/agents/{AG}", json={"limits": {"period": "month", "metric": "cost", "hard": 0.7}})
r = cl.get("/lists")
check(r.status_code == 429 and "this month" in r.json()["error"]["message"] and "$0.75 of $0.70" in r.json()["error"]["message"], f"cost / month: {r.text[:200]}")
st = A.get(B + "/api/admin/agents").json()["agents"]
st = [a for a in st if a["id"] == AG][0]["usage"]
check(st["key"] == date.today().strftime("%Y-%m") and st["metric"] == "cost" and abs(st["used"] - 0.75) < 1e-9, f"month key + cost: {st}")
check(A.patch(B + f"/api/admin/agents/{AG}", json={"limits": None}).json()["limits"] is None and cl.get("/lists").ok, "limits removed: calls work")
check(cl.get("/agent").json()["usage_limit"] is None, "no limit: usage_limit null")
# the notification setting "usage": off -> no News, no push
m = A.get(B + "/api/state").json()["notify"]
check(m["usage"] == {"news": True, "push": True}, f"notification row 'usage' defaults on: {m.get('usage')}")
A.patch(B + "/api/settings", json={"notify": {"usage": {"news": 0, "push": 0}}})
n0 = len([x for x in A.get(B + "/api/news").json()["items"] if x["kind"] == "usage"])
p0 = len(aphone.notes())
A.patch(B + f"/api/admin/agents/{AG2}", json={"limits": {"period": "day", "metric": "tokens", "soft": 10}})
time.sleep(3.2)
cx.post("/agent/usage", json={**ok})
time.sleep(2)
check(len([x for x in A.get(B + "/api/news").json()["items"] if x["kind"] == "usage"]) == n0 and len(aphone.notes()) == p0, "switched off: nothing")
A.patch(B + "/api/settings", json={"notify": ""})

# ================================================================== spec + deleting the agent
spec = requests.get(V + "/openapi.json").json()
check("post" in spec["paths"].get("/agent/usage", {}) and "get" in spec["paths"]["/agent/usage"], "OpenAPI documents /agent/usage")
check(A.delete(B + f"/api/users/{AG2}").ok, "delete codex")
con = sqlite3.connect(os.path.join(DATA, "tasks.db"))
check(con.execute("SELECT COUNT(*) FROM agent_usage WHERE agent_id=?", (AG2,)).fetchone()[0] == 0, "its usage rows are gone")
con.close()

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
