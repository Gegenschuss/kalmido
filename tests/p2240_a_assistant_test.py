#!/usr/bin/env python3
"""2.240.0 A (#2884): the assistant and other members' comments, the embedding service on another host.
 - a task in a list of an organisation: what reaches the model has only the asking person's own comments while the
   organisation's switch asst_comments is off (default); with it on, the other members' comments go along too; only an
   admin of the organisation changes the switch
 - a private list (a person without organisation, freelancer-matrix: assistant): the owner decides as before, every
   comment goes along
 - switching asst_comments on: the organisation's other members get a News entry (orglist, action asstcomments) once
 - sharing a list with the assistant: its other members get a News entry (kind agentjoin, like an agent joining) once;
   saving the same choice again adds none
 - KALMIDO_EMBED_URL on another host: off (logged) unless KALMIDO_EMBED_EXTERNAL=1; local / container / this server
   stay as they were (a number form of an address is no container name); the service is called through safe_urlopen
Invented names only; the model is tests/fake_ai.py.
usage: p2240_a_assistant_test.py <datadir>      (starts its own container)"""
import json
import os
import shutil
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check, done, sess  # noqa: E402,F401
AI_ENV = (" -e KALMIDO_AI_BASE_URL=http://127.0.0.1:8089/v1 -e KALMIDO_AI_MODEL=fake-1 -e KALMIDO_AI_KEY=test-key"
          " -e KALMIDO_AI_NAME=Fake-AI -e KALMIDO_AI_TIMEOUT_S=5")


def dbx(sql, args=()):
    c = dbxm.connect(DATA, timeout=10)
    cur = c.execute(sql, args)
    rows = cur.fetchall() if sql.lstrip().upper().startswith("SELECT") else []
    c.commit()
    return rows


def ai_log():
    try:
        with open(os.path.join(DATA, "ai.log"), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except OSError:
        return []


def asked(s, tid):
    """The user message of one summary call for task tid ('' when the call failed)."""
    n0 = len(ai_log())
    r = s.post(B + "/api/assistant/run", json={"kind": "summary", "task_id": tid})
    if not r.ok:
        print("summary failed:", r.status_code, r.text[:200], flush=True)
        return ""
    L = ai_log()
    return L[-1]["messages"][-1]["content"] if len(L) > n0 else ""


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + AI_ENV)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "assistant_on": "1"})
shutil.copy(os.path.join(N, "fake_ai.py"), DATA)
try:
    os.remove(os.path.join(DATA, "ai.log"))
except OSError:
    pass
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_ai.py"], check=True)
for _ in range(50):
    if subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8089), 1)"],
                      capture_output=True).returncode == 0:
        break
    time.sleep(0.2)

ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en"})
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{W}/members", json={"user_id": BOB, "role": "edit"})
T = A.post(B + "/api/tasks", json={"title": "Plan the launch", "list_id": W, "content": "Budget note"}).json()["id"]
check(A.post(B + f"/api/tasks/{T}/comments", json={"body": "Alice own remark"}).ok, "alice comments")
check(Bo.post(B + f"/api/tasks/{T}/comments", json={"body": "Bob member remark"}).ok, "bob comments")


def joins(uid):
    return [json.loads(x[0] or "{}") for x in dbx("SELECT data FROM notifications WHERE user_id=? AND kind='agentjoin' AND list_id=?", (uid, W))]


# ---- sharing: the other members learn it once
r = A.put(B + "/api/assistant/lists", json={"list_ids": [W]})
check(r.ok, "alice shares Work with the assistant " + r.text[:200])
j = joins(BOB)
check(len(j) == 1 and j[0].get("name") == "Work" and j[0].get("agent") == "Assistant" and j[0].get("provider") == "127.0.0.1",
      f"bob: one News entry about the assistant in Work {j}")
check(not joins(1), "alice: no News entry about her own share")
A.put(B + "/api/assistant/lists", json={"list_ids": [W]})
check(len(joins(BOB)) == 1, "saving the same choice again: no second entry")

# ---- organisation list: own comments only until the organisation allows it
um = asked(A, T)
check("Alice own remark" in um and "Budget note" in um, "org list, switch off: own comment and note go along")
check("Bob member remark" not in um, "org list, switch off: bob's comment does not go to the model")
check(Bo.patch(B + f"/api/orgs/{ORG}", json={"asst_comments": True}).status_code in (403, 404), "bob (member) cannot switch it on")
r = A.patch(B + f"/api/orgs/{ORG}", json={"asst_comments": True})
check(r.ok, "alice (admin) switches it on " + r.text[:200])
o = next((x for x in A.get(B + "/api/orgs").json().get("orgs", []) if x["id"] == ORG), {})
check(o.get("asst_comments") is True, f"GET /api/orgs: asst_comments true {o.get('asst_comments')}")
NOTE = "SELECT data FROM notifications WHERE user_id=? AND kind='orglist' AND data::text LIKE '%asstcomments%'"
check(len(dbx(NOTE, (BOB,))) == 1 and not dbx(NOTE, (1,)), "switched on: bob learns it in his News (alice not)")
A.patch(B + f"/api/orgs/{ORG}", json={"asst_comments": True})
check(len(dbx(NOTE, (BOB,))) == 1, "switched on again while on: no second entry")
um = asked(A, T)
check("Alice own remark" in um and "Bob member remark" in um, "org list, switch on: every comment goes along")
A.patch(B + f"/api/orgs/{ORG}", json={"asst_comments": False})
check("Bob member remark" not in asked(A, T), "switched off again: bob's comment stays out")

# ---- a person without organisation: the private list as before
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"assistant_on": "1"})
FL = Fr.post(B + "/api/lists", json={"name": "Frida private"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Private plan", "list_id": FL}).json()["id"]
Fr.post(B + f"/api/tasks/{FT}/comments", json={"body": "Frida own remark"})
dbx("INSERT INTO comments(task_id,user_id,body,created_at) VALUES(?,?,?,?)", (FT, BOB, "Guest remark in private list", "2026-10-25T10:00:00Z"))
check(Fr.put(B + "/api/assistant/lists", json={"list_ids": [FL]}).ok, "freelancer shares her private list")
um = asked(Fr, FT)
check("Frida own remark" in um and "Guest remark in private list" in um, "freelancer: private list, every comment goes along as before")

# ---- embedding service on another host
EMB = """
import json, app
from kalmido.tasks import related as R
print(json.dumps({"url": R.EMBED_URL, "ext": R.EMB_EXTERNAL, "blocked": R.EMB_BLOCKED,
                  "num": [R.emb_url_kind(u) for u in ("http://134744072:8090", "http://0x08080808:8090", "http://embed_1:8090")],
                  "kinds": [R.emb_external_host(u) for u in ("https://embed.example.com/x", "http://embed:8090", "http://127.0.0.1:8090", "https://localhost:8090")]}))
"""


def emb(*env):
    a = ["docker", "exec", "-i"]
    for e in env:
        a += ["-e", e]
    r = subprocess.run(a + [CT, "python", "-c", EMB], capture_output=True, text=True, timeout=300)
    out = [x for x in (r.stdout or "").splitlines() if x.startswith("{")]
    if not out:
        print("EMB FAILED:", r.stdout[-1500:], r.stderr[-2000:], flush=True)
    return json.loads(out[-1]) if out else {}, r.stdout or ""


j, out = emb("KALMIDO_EMBED_URL=https://embed.example.com")
check(j.get("url") == "" and j.get("blocked") is True and "KALMIDO_EMBED_EXTERNAL" in out, f"another host without the switch: off + log line {j}")
check(j.get("kinds") == ["embed.example.com", "", "", ""], f"only another host counts as external {j.get('kinds')}")
check(j.get("num") == ["", "", "internal"], f"a number form of an address is no container {j.get('num')}")
j, _ = emb("KALMIDO_EMBED_URL=https://embed.example.com", "KALMIDO_EMBED_EXTERNAL=1")
check(j.get("url") == "https://embed.example.com" and j.get("ext") == "embed.example.com" and not j.get("blocked"), f"with KALMIDO_EMBED_EXTERNAL=1: on {j}")
j, _ = emb("KALMIDO_EMBED_URL=http://embed:8090")
check(j.get("url") == "http://embed:8090" and not j.get("ext") and not j.get("blocked"), f"a container stays as it was {j}")
r = subprocess.run(["docker", "exec", CT, "python", "-c", "import inspect, app\nfrom kalmido.tasks import related as R\n"
                    "print(all('safe_urlopen' in inspect.getsource(f) and 'urllib.request.urlopen' not in inspect.getsource(f) for f in (R.emb_call, R.emb_health)))"],
                   capture_output=True, text=True, timeout=300)
check((r.stdout or "").strip().endswith("True"), "the embedding service is called through safe_urlopen " + (r.stdout or "")[-200:])
r = A.get(B + "/api/admin/related")
check(r.ok and "external" in r.json() and r.json().get("blocked") is False, "admin overview: external / blocked fields " + r.text[:200])

sys.exit(done("p2240_a_assistant"))
