#!/usr/bin/env python3
"""2.24.0 "Usability" API tests.
 - #910 storage quota per person: usage counts task + comment files, project files and a person's agent-chat files; the
   instance default (admin), a person's own value (0 = unlimited), the pool "org" (quota x members), 413 quota_exceeded on
   the web API and the REST API (code + used / limit), nothing is written when refused, GET /api/me/storage +
   /api/v1/me/storage, the state's "storage", the admin's user list shows usage, the backfill of the uploader
 - #907 the notice: admin PUT /api/admin/announcement (validation, minutes -> ends_at, a later start is "not active yet",
   clear), everybody's state "announce", GET /api/v1/announcement, PUT /api/v1/admin/announcement (admins only, unknown
   fields), the command `python app.py announce`
 - #899 mail limits: per sender and per receiving address and day (mail_budget), the admin setting mail_day_limit
 - #896 agents: "where it runs" (provider) on admin and personal agents; everyone in a list gets the News "agentjoin" when
   an agent joins (not the person who added it), the organisation setting user_agents in about
 - #905 KALMIDO_HOSTED=1: about.hosted, the old module "paperless" off for new accounts (2.36.0: connection removed)
Restarts its container (start.sh). usage: p2240_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
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


def tok(s, scopes):
    r = s.post(B + "/api/me/tokens", json={"name": "t" + str(time.monotonic_ns())[-6:], "scopes": scopes})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def up(s, url, size, name="f.bin"):
    return s.post(B + url, files={"file": (name, os.urandom(size), "application/octet-stream")})


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {"alice": 1}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")

# ================================================================== #910 storage quota
st = Bo.get(B + "/api/state").json()["storage"]
check(st["used"] == 0 and st["limit"] is None and st["level"] == "ok", f"#910: a self-hosted server without a quota: unlimited {st}")
lid = Bo.post(B + "/api/lists", json={"name": "Files"}).json()["id"]
tid = Bo.post(B + "/api/tasks", json={"title": "with files", "list_id": lid}).json()["id"]
r = up(Bo, f"/api/tasks/{tid}/attachments", 300_000)
check(r.ok, f"#910: upload without a quota {r.status_code}")
check(dbx("SELECT user_id FROM attachments WHERE task_id=?", (tid,)) == [(ids["bob"],)], "#910: the uploader is stored")
q = Bo.get(B + "/api/me/storage").json()
check(q["used"] == 300_000, f"#910: GET /api/me/storage counts the file {q}")
r = A.patch(B + "/api/admin/settings", json={"storage_quota_mb": 1})
check(r.ok and r.json()["storage_quota_mb"] == 1, f"#910: admin sets 1 MB per person {r.text[:200]}")
check(A.patch(B + "/api/admin/settings", json={"storage_quota_mb": -1}).status_code == 400, "#910: a negative quota is refused")
check(A.patch(B + "/api/admin/settings", json={"storage_pool": "galaxy"}).status_code == 400, "#910: an unknown pool is refused")
check(Bo.patch(B + "/api/admin/settings", json={"storage_quota_mb": 0}).status_code == 403, "#910: only admins set the quota")
q = Bo.get(B + "/api/me/storage").json()
check(q["limit"] == 1024 * 1024 and q["level"] == "ok" and 28 < q["pct"] < 29, f"#910: limit + percent {q}")
r = up(Bo, f"/api/tasks/{tid}/attachments", 500_000)
check(r.ok and Bo.get(B + "/api/me/storage").json()["level"] == "ok", "#910: a second file still fits (76 %: ok)")
r = up(Bo, f"/api/tasks/{tid}/attachments", 100_000)
q = Bo.get(B + "/api/me/storage").json()
check(r.ok and q["level"] == "warn", f"#910: 86 % -> level warn {q}")
n0 = dbx("SELECT COUNT(*) FROM attachments")[0][0]
r = up(Bo, f"/api/tasks/{tid}/attachments", 400_000)
j = r.json()
check(r.status_code == 413 and j.get("code") == "quota_exceeded" and j.get("limit") == 1024 * 1024 and "storage" in j.get("error", "").lower(),
      f"#910: over the quota -> 413 quota_exceeded {r.status_code} {j}")
check(dbx("SELECT COUNT(*) FROM attachments")[0][0] == n0, "#910: nothing written when refused")
check(len([f for f in os.listdir(os.path.join(DATA, "attachments", str(tid)))]) == 3, "#910: no file left on disk")
r = Bo.post(B + f"/api/tasks/{tid}/comments", files={"file": ("c.bin", os.urandom(400_000), "application/octet-stream")}, data={"body": "x"})
check(r.status_code == 413 and r.json().get("code") == "quota_exceeded", f"#910: a comment file is refused too {r.status_code}")
check(not dbx("SELECT 1 FROM comments WHERE task_id=? AND body='x'", (tid,)), "#910: ... and the comment is not saved half")
TB = tok(Bo, ["read", "tasks:write", "attachments:write", "account"])
r = requests.post(V + f"/tasks/{tid}/attachments", headers=TB, files={"file": ("v.bin", os.urandom(400_000), "application/octet-stream")})
check(r.status_code == 413 and r.json()["error"]["code"] == "quota_exceeded" and r.json()["error"]["limit"] == 1024 * 1024,
      f"#910: REST API 413 quota_exceeded {r.status_code} {r.text[:200]}")
r = requests.get(V + "/me/storage", headers=TB)
check(r.ok and r.json()["used"] == 900_000, f"#910: GET /api/v1/me/storage {r.text[:200]}")
r = up(Ca, f"/api/tasks/{Ca.post(B + '/api/tasks', json={'title': 'c'}).json()['id']}/attachments", 400_000)
check(r.ok, "#910: the quota is per person (carol still has room)")
# a person's own value: 0 = unlimited, null = the default again
r = A.patch(B + f"/api/users/{ids['bob']}", json={"storage_quota_mb": 0})
check(r.ok and r.json()["storage"]["quota_mb"] == 0 and r.json()["storage"]["used"] == 900_000, f"#910: admin: bob unlimited, the user list shows his usage {r.text[:200]}")
check(up(Bo, f"/api/tasks/{tid}/attachments", 400_000).ok, "#910: unlimited -> fits again")
check(A.patch(B + f"/api/users/{ids['bob']}", json={"storage_quota_mb": "lots"}).status_code == 400, "#910: a bad own quota is refused")
A.patch(B + f"/api/users/{ids['bob']}", json={"storage_quota_mb": None})
check(Bo.get(B + "/api/me/storage").json()["level"] == "full", "#910: back on the default: full (nothing deleted)")
# project files + the pool
pl = Ca.post(B + "/api/lists", json={"name": "P", "kind": "project"}).json()["id"]
r = Ca.post(B + f"/api/lists/{pl}/files", files={"file": ("p.bin", os.urandom(700_000), "application/octet-stream")})
check(r.status_code == 413 and r.json().get("code") == "quota_exceeded", f"#910: project files count + refuse ({r.status_code})")
r = A.patch(B + "/api/admin/settings", json={"storage_pool": "org"})
q = Ca.get(B + "/api/me/storage").json()
check(r.ok and q["pool"] == "org" and q["members"] == 3 and q["limit"] == 3 * 1024 * 1024 and q["used"] == 1_700_000, f"#910: pool org = quota x members, usage of all {q}")
check(Ca.post(B + f"/api/lists/{pl}/files", files={"file": ("p.bin", os.urandom(700_000), "application/octet-stream")}).ok, "#910: the pool has room")
A.patch(B + "/api/admin/settings", json={"storage_pool": "user", "storage_quota_mb": None, "support_email": "help@example.com"})
ab = A.get(B + "/api/about").json()
check(ab.get("support_email") == "help@example.com" and ab.get("storage_quota_mb") is None and ab.get("hosted") is False, f"#910: about for admins {ab.get('support_email')} {ab.get('hosted')}")
check("support_email" not in Bo.get(B + "/api/about").json(), "#910: people do not see the admin settings")
check(A.patch(B + "/api/admin/settings", json={"support_email": "no address"}).status_code == 400, "#910: a bad support address is refused")
check(Bo.get(B + "/api/state").json()["storage"]["support"] == "help@example.com", "#910: the support address reaches the app")
# the backfill: rows from before 2.24 get their uploader (comment author, else the task's creator)
dbx("UPDATE attachments SET user_id=NULL")
c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
c.execute("DELETE FROM settings WHERE key='migr_att_user'")
c.commit()
c.close()
subprocess.run(["docker", "restart", CT], check=True, stdout=subprocess.DEVNULL)
for _ in range(60):
    try:
        if requests.get(B + "/api/health", timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(0.5)
check(dbx("SELECT COUNT(*) FROM attachments WHERE user_id IS NULL")[0][0] == 0, "#910: the backfill gives every old file its uploader")
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")

# ================================================================== #907 the notice
check(Bo.get(B + "/api/state").json()["announce"] is None, "#907: no notice by default")
check(Bo.put(B + "/api/admin/announcement", json={"text": "x"}).status_code == 403, "#907: only admins")
check(A.put(B + "/api/admin/announcement", json={"text": "x" * 501}).status_code == 400, "#907: at most 500 characters")
check(A.put(B + "/api/admin/announcement", json={"text": "x", "level": "panic"}).status_code == 400, "#907: unknown level")
check(A.put(B + "/api/admin/announcement", json={"text": "x", "starts_at": "2030-01-02T00:00:00Z", "ends_at": "2030-01-01T00:00:00Z"}).status_code == 400, "#907: end before start")
r = A.put(B + "/api/admin/announcement", json={"text": "  Maintenance   tonight <b>22:00</b> ", "level": "maintenance", "minutes": 30})
j = r.json()
check(r.ok and j["text"] == "Maintenance tonight <b>22:00</b>" and j["active"] and j.get("ends_at") and j["level"] == "maintenance", f"#907: set {j}")
a = Bo.get(B + "/api/state").json()["announce"]
check(a and a["text"].startswith("Maintenance") and a["id"] == j["id"], f"#907: everybody's state has it {a}")
TR = tok(Bo, ["read"])
r = requests.get(V + "/announcement", headers=TR)
check(r.ok and r.json()["level"] == "maintenance", f"#907: GET /api/v1/announcement {r.text[:120]}")
r = requests.put(V + "/admin/announcement", headers=tok(Bo, ["read", "account"]), json={"text": "y"})
check(r.status_code == 403, f"#907: a person's token cannot set it {r.status_code}")
TA = tok(A, ["read", "account", "admin-read"])
check(requests.put(V + "/admin/announcement", headers=TR, json={"text": "y"}).status_code == 403, "#907: a read token cannot set it")
r = requests.put(V + "/admin/announcement", headers=TA, json={"text": "y", "colour": "red"})
check(r.status_code == 400 and r.json()["error"]["code"] == "unknown_field", f"#907: unknown fields {r.text[:120]}")
r = requests.put(V + "/admin/announcement", headers=TA, json={"text": "Update at 23:00", "starts_at": "2099-01-01T22:00:00Z"})
check(r.ok and r.json()["active"] is False, f"#907: a later notice is not active yet {r.text[:160]}")
a = Bo.get(B + "/api/state").json()["announce"]
check(a and a["active"] is False, "#907: ... the state still announces it (active false)")
r = requests.put(V + "/admin/announcement", headers=TA, json={"text": ""})
check(r.ok and Bo.get(B + "/api/state").json()["announce"] is None, "#907: {text: ''} clears it")
out = subprocess.run(["docker", "exec", CT, "python", "app.py", "announce", "Restart in a moment", "--minutes", "5", "--maintenance"], capture_output=True, text=True)
check(out.returncode == 0 and '"maintenance"' in out.stdout, f"#907: python app.py announce {out.stdout[-200:]} {out.stderr[-200:]}")
check(Bo.get(B + "/api/state").json()["announce"]["text"] == "Restart in a moment", "#907: the command's notice shows")
out = subprocess.run(["docker", "exec", CT, "python", "app.py", "announce", "--clear"], capture_output=True, text=True)
check(out.returncode == 0 and Bo.get(B + "/api/state").json()["announce"] is None, "#907: announce --clear")
spec = requests.get(V + "/openapi.json").json()
check({"/me/storage", "/announcement", "/admin/announcement"} <= set(spec["paths"]), "OpenAPI: the new routes are documented")

# ================================================================== #899 mail limits
code = ("import app\nc=app.connect()\nr=[app.mail_budget(c, 7, 'x@example.com') for _ in range(6)]\n"
        "s=[app.mail_budget(c, 8, f'y{i}@example.com') for i in range(31)]\nc.commit()\nprint(r, s.count(True))")
out = subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True)
check(out.returncode == 0 and out.stdout.strip().endswith("[True, True, True, True, True, False] 30"), f"#899: 5 per address, 30 per sender and day {out.stdout[-160:]} {out.stderr[-300:]}")
r = A.patch(B + "/api/admin/settings", json={"mail_day_limit": 2})
check(r.ok and r.json()["mail_day_limit"] == 2, "#899: the admin sets the daily limit")
check(A.patch(B + "/api/admin/settings", json={"mail_day_limit": 0}).status_code == 400, "#899: at least 1")

# ================================================================== #896 agents: provider + notice when one joins
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
check(A.get(B + "/api/about").json().get("user_agents") is True, "#896: about shows whether members may connect agents")
r = A.post(B + "/api/admin/agents", json={"username": "helper", "provider": "Claude (Anthropic, USA)"})
check(r.status_code in (200, 201), f"#896: admin agent with provider {r.text[:160]}")
ag = r.json().get("agent", r.json())
aid = ag.get("id") or dbx("SELECT id FROM users WHERE username='helper'")[0][0]
check(dbx("SELECT provider FROM agents WHERE user_id=?", (aid,)) == [("Claude (Anthropic, USA)",)], "#896: provider stored")
sl = A.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
for u in ("bob", "carol"):
    A.put(B + f"/api/lists/{sl}/members", json={"user_id": ids[u], "role": "edit"})
A.put(B + f"/api/lists/{sl}/members", json={"user_id": aid, "role": "edit"})
nb = [x for x in Bo.get(B + "/api/news").json()["items"] if x["kind"] == "agentjoin"]
check(nb and nb[0]["data"]["provider"] == "Claude (Anthropic, USA)" and nb[0]["data"]["agent"] == "helper", f"#896: bob learns that the agent joined and where it runs {nb[:1]}")
check([x for x in Ca.get(B + "/api/news").json()["items"] if x["kind"] == "agentjoin"], "#896: carol too")
check(not [x for x in A.get(B + "/api/news").json()["items"] if x["kind"] == "agentjoin"], "#896: not the person who added it")
r = Bo.post(B + "/api/my/agents", json={"username": "bobs-bot", "provider": "Local model (own PC)"})
check(r.ok or r.status_code == 201, f"#896: personal agent with provider {r.text[:160]}")
r = Bo.get(B + "/api/my/agents").json()
check(r["agents"] and r["agents"][0]["provider"] == "Local model (own PC)", "#896: the owner sees it")
r = Bo.patch(B + f"/api/my/agents/{r['agents'][0]['id']}", json={"provider": "Mistral (EU)"})
check(r.ok and dbx("SELECT provider FROM agents WHERE owner_id=?", (ids["bob"],)) == [("Mistral (EU)",)], "#896: the owner changes it")
A.put(B + "/api/admin/agent-policy", json={"user_agents": False})
check(Ca.post(B + "/api/my/agents", json={"username": "carols-bot"}).status_code in (403, 409), "#896: switched off -> members cannot connect agents")

# ================================================================== #905 a hosted server
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env={**os.environ, "KEEP": "1", "EXTRA": "-e KALMIDO_HOSTED=1 -e KALMIDO_SECRET_KEY=" + "A" * 43 + "="})
A, Bo = sess("alice"), sess("bob")
check(A.get(B + "/api/about").json().get("hosted") is True and "hosted" not in Bo.get(B + "/api/about").json(), "#905: about.hosted (admins)")
feats = dbx("SELECT value FROM settings WHERE key='default_features'")
check(feats and "paperless" not in feats[0][0].split(","), f"#905: hosted: Paperless is off for new accounts {feats}")
r = A.post(B + "/api/users", json={"username": "dave", "password": "password123"})
f = dbx("SELECT value FROM user_settings WHERE user_id=? AND key='features'", (r.json()["id"],))
check(f and "paperless" not in f[0][0].split(","), "#905: ... a new account starts without it")

print(f"p2240_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
