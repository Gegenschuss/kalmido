#!/usr/bin/env python3
"""2.33.0 API tests (agent D), own container (start.sh).
 - #1045 the usage ring: PUT / GET / DELETE /api/v1/agent/quota -- windows {label, percent, resets_at (ISO or Unix seconds),
   main} or Claude Code's rate_limits as it is, an own limit; validation (unknown fields, both forms, two main windows, bad
   percent / label / time / limit, too many windows); level ok / warn (75 %) / over (limit, else 100 %) with paused_until =
   the main window's reset; a window past its reset counts 0 %; stale after 24 h; visible as "quota" in GET /api/agents
   only to people who may chat with the agent (same organisation, list shared) -- never to a person of another organisation;
   allowed while the agent's hard usage limit is reached; the agents column is new (2.32 keeps working)
 - #934 the repository on a folder (see below)
usage: p2330_d_api_test.py <datadir>"""
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
KEY = __import__("base64").b64encode(os.urandom(32)).decode()
GH = "http://127.0.0.1:8090"      # fake GitHub Enterprise (fake_git.py, API under /api/v3)
TOKEN = "ghp_fake_read_only_token_934"
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
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
# two organisations (instance mode workspaces, as in p2300_tenant_test): carol is only in the other one
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces"
                        # #934: the fake Git servers inside the container (fake_git.py), fast polling, a key for tokens
                        " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1 -e KALMIDO_GIT_POLL=2 -e KALMIDO_GIT_TICK=1 -e KALMIDO_SECRET_KEY=" + KEY))
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en"})
# carol: only in another organisation
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
OT, OTH = agent("otto")  # a second agent of the same organisation
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
for who in (CL, BOB):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": "edit"}).ok, f"setup: {who} in the list")
W2 = A.post(B + "/api/lists", json={"name": "Other agent", "org_id": ORG}).json()["id"]  # one agent per list: otto works here
A.put(B + f"/api/lists/{W2}/members", json={"user_id": OT, "role": "edit"})
A.patch(B + f"/api/lists/{W}", json={"agent_members": True})  # bob may use the list's agents (he chats with claude too)
T = A.post(B + "/api/tasks", json={"title": "Shared task", "list_id": W}).json()["id"]
LB = Ca.post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json()["id"]


import json
from datetime import datetime, timedelta, timezone


def chat(s, aid=CL):
    return s.get(B + f"/api/agents/{aid}/chat")


def ags(s):
    r = s.get(B + "/api/agents")
    return {a["id"]: a for a in r.json()["agents"]} if r.ok else {}


def qput(body, h=CLH):
    return requests.put(V + "/agent/quota", headers=h, json=body)


check(ags(A)[CL].get("quota") is None, "#1045: no report = quota null (no ring)")
soon = int((datetime.now(timezone.utc) + timedelta(days=3)).timestamp())
r = qput({"rate_limits": {"five_hour": {"used_percentage": 23.5, "resets_at": soon - 86400}, "seven_day": {"used_percentage": 41.2, "resets_at": soon}},
          "limit": 90})
q = r.json().get("quota") if r.ok else None
check(r.status_code == 200 and q and [w["key"] for w in q["windows"]] == ["seven_day", "five_hour"] and q["main"] == 0 and q["percent"] == 41.2,
      "#1045: rate_limits taken as they are, the week is the main window " + r.text[:200])
check(q and q["level"] == "ok" and q["limit"] == 90 and q["paused_until"] is None and not q["stale"] and q["windows"][0]["resets_at"].startswith(
    datetime.fromtimestamp(soon, timezone.utc).strftime("%Y-%m-%dT%H:%M")), "#1045: level ok, reset time as ISO " + str(q)[:200])
check(ags(A)[CL]["quota"]["percent"] == 41.2 and ags(Bo)[CL]["quota"]["percent"] == 41.2, "#1045: alice and bob (chat with claude) see it")
check(CL not in ags(Ca) and chat(Ca).status_code == 404, "#1045: carol (other organisation) sees nothing of claude")
check(requests.get(V + "/agent", headers=CLH).json().get("quota", {}).get("percent") == 41.2, "#1045: GET /agent carries it")
check(requests.get(V + "/agent/quota", headers=CLH).json()["quota"]["percent"] == 41.2, "#1045: GET /agent/quota")
check(requests.get(V + "/agent/quota", headers=OTH).json()["quota"] is None, "#1045: per agent (otto has none)")
check(requests.get(V + "/agent/quota", headers={"Authorization": "Bearer nope"}).status_code == 401, "#1045: a token is needed")
tok = A.post(B + "/api/me/tokens", json={"name": "mine", "scopes": ["read", "tasks:write"]})
if tok.ok and tok.json().get("token"):
    check(requests.put(V + "/agent/quota", headers={"Authorization": "Bearer " + tok.json()["token"]}, json={"windows": []}).status_code in (403, 404),
          "#1045: a person's token cannot report a quota")

# levels
r = qput({"windows": [{"label": "5 hours", "percent": 10}, {"label": "Week", "percent": 80, "resets_at": "2031-01-02T09:00:00+01:00", "main": True}]})
q = r.json()["quota"]
check(q["main"] == 1 and q["level"] == "warn" and q["percent"] == 80 and q["limit"] is None and q["windows"][1]["resets_at"] == "2031-01-02T08:00:00+00:00",
      "#1045: windows with main, from 75 % yellow, ISO time in UTC " + str(q)[:200])
q = qput({"windows": [{"label": "Week", "percent": 100, "resets_at": "2031-01-02T09:00:00+01:00"}]}).json()["quota"]
check(q["level"] == "over" and q["paused_until"] == "2031-01-02T08:00:00+00:00", "#1045: no limit: red at 100 % with paused until the reset")
q = qput({"windows": [{"label": "Week", "percent": 90.4, "resets_at": "2031-01-02T09:00:00+01:00"}], "limit": 90}).json()["quota"]
check(q["level"] == "over" and q["paused_until"], "#1045: from the own limit red + paused until")
q = qput({"windows": [{"label": "Week", "percent": 95, "resets_at": "2020-01-02T09:00:00+01:00"}], "limit": 90}).json()["quota"]
check(q["level"] == "ok" and q["percent"] == 0 and q["windows"][0]["reset_passed"] and q["windows"][0]["resets_at"] is None and q["paused_until"] is None,
      "#1045: a window past its reset counts 0 % " + str(q)[:200])
q = qput({"windows": [{"label": "Spend", "percent": 130}]}).json()["quota"]
check(q["percent"] == 130 and q["level"] == "over" and q["paused_until"] is None, "#1045: above 100 % (a spend limit) accepted, no reset = no pause time")
# stale after 24 h
old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec="seconds")
raw = json.loads(dbx("SELECT quota FROM agents WHERE user_id=?", (CL,))[0][0])
dbx("UPDATE agents SET quota=? WHERE user_id=?", (json.dumps({**raw, "at": old}), CL), write=True)
check(ags(A)[CL]["quota"]["stale"] is True, "#1045: a report older than 24 h is stale (grey)")
v0 = A.get(B + "/api/version").json()
qput({"windows": [{"label": "Spend", "percent": 130}]})
check(ags(A)[CL]["quota"]["stale"] is False, "#1045: a new report is fresh again")
check(A.get(B + "/api/version").json() != v0, "#1045: a fresh report after a stale one moves the version (the ring turns coloured)")
v1 = A.get(B + "/api/version").json()
qput({"windows": [{"label": "Spend", "percent": 130.02}]})
check(A.get(B + "/api/version").json() == v1, "#1045: the same values again do not make every app reload")

# validation
bad = [({"windows": [{"label": "W", "percent": 5}], "rate_limits": {}}, "both forms"), ({"windowz": []}, "unknown field"),
       ({"windows": [{"label": "W", "percent": 5, "x": 1}]}, "unknown window field"),
       ({"windows": [{"label": "A", "percent": 5, "main": True}, {"label": "B", "percent": 5, "main": True}]}, "two main windows"),
       ({"windows": [{"label": "W", "percent": -1}]}, "negative"), ({"windows": [{"label": "W", "percent": 1001}]}, "too high"),
       ({"windows": [{"label": "W", "percent": True}]}, "bool percent"), ({"windows": [{"label": "W", "percent": "5"}]}, "string percent"),
       ({"windows": [{"label": "W"}]}, "no percent"), ({"windows": [{"label": "", "percent": 5}]}, "empty label"),
       ({"windows": [{"label": "<b>W</b>", "percent": 5}]}, "markup label"), ({"windows": [{"label": "x" * 41, "percent": 5}]}, "long label"),
       ({"windows": [{"label": "W", "percent": 5, "resets_at": "tomorrow"}]}, "bad time"),
       ({"windows": [{"label": "W", "percent": 5, "resets_at": "2031-01-02T09:00:00"}]}, "time without zone"),
       ({"windows": [{"label": "W", "percent": 5, "main": 1}]}, "main not bool"),
       ({"windows": [{"label": f"W{i}", "percent": 5} for i in range(7)]}, "7 windows"),
       ({"windows": [{"label": "W", "percent": 5}], "limit": 0}, "limit 0"), ({"windows": [{"label": "W", "percent": 5}], "limit": 101}, "limit 101"),
       ({"rate_limits": {"seven_day": {"resets_at": 1}}}, "rate_limits without percentage"), ({"rate_limits": [1]}, "rate_limits not an object"),
       ({"windows": "W"}, "windows not a list")]
for body, what in bad:
    r = qput(body)
    check(r.status_code == 400, f"#1045: refused: {what} ({r.status_code})")
check(ags(A)[CL]["quota"]["percent"] == 130.0, "#1045: a refused report changes nothing (percent kept to one decimal)")

# measured_at (relayed older values grey out by their own age, a future time counts as now)
r = qput({"windows": [{"label": "Week", "percent": 12}], "measured_at": int(time.time()) - 25 * 3600})
check(r.status_code == 200 and r.json()["quota"]["stale"] is True, "#1045: measured_at 25 h ago is stale at once " + r.text[:200])
r = qput({"windows": [{"label": "Week", "percent": 12}], "measured_at": (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()})
check(r.status_code == 200 and r.json()["quota"]["stale"] is False and r.json()["quota"]["at"] <= datetime.now(timezone.utc).isoformat()[:19] + "Z~",
      "#1045: a measured_at in the future counts as now " + r.text[:200])
check(qput({"windows": [{"label": "Week", "percent": 12}], "measured_at": "gestern"}).status_code == 400, "#1045: bad measured_at -> 400")

# a person never reports one
check(A.put(V + "/agent/quota", json={"windows": []}).status_code in (401, 403), "#1045: a session is no agent")
# hard usage limit reached: reporting still works
A.patch(B + f"/api/admin/agents/{OT}", json={"limits": {"period": "day", "metric": "tokens", "hard": 10}})
requests.post(V + "/agent/usage", headers=OTH, json={"model": "m", "input_tokens": 50, "output_tokens": 50})
check(requests.get(V + "/lists", headers=OTH).status_code == 429, "setup: otto is over its hard limit")
check(qput({"windows": [{"label": "Week", "percent": 99}]}, OTH).status_code == 200, "#1045: reporting the quota works over the hard limit")
check(requests.delete(V + "/agent/quota", headers=OTH).status_code == 200, "#1045: DELETE works over the hard limit")
# remove
r = qput({"windows": []})
check(r.ok and r.json()["quota"] is None and ags(A)[CL]["quota"] is None and dbx("SELECT quota FROM agents WHERE user_id=?", (CL,))[0][0] == "",
      "#1045: no windows = removed (no ring)")
qput({"rate_limits": {"seven_day": {"used_percentage": 5, "resets_at": soon}}})
r = requests.delete(V + "/agent/quota", headers=CLH)
check(r.ok and r.json()["quota"] is None and ags(A)[CL]["quota"] is None, "#1045: DELETE removes it")
check(qput({"rate_limits": {}}).json()["quota"] is None, "#1045: empty rate_limits (the window passed) = no ring")
# 2.32 keeps working with the database: the column has a default, an insert without it works
cols = {r[1]: r for r in dbx("PRAGMA table_info(agents)")}
check("quota" in cols and cols["quota"][3] == 1 and cols["quota"][4] == "''", "#1045: agents.quota NOT NULL DEFAULT '' " + str(cols.get("quota")))

# ================================================================== #934 the repository on a folder
STATE = {"8090": {"acme/app": {"token": TOKEN, "default_branch": "main", "pulls": [], "commits": {"main": []}},
                  "acme/own": {"token": TOKEN, "default_branch": "main", "pulls": [], "commits": {"main": []}},
                  "acme/sub": {"token": TOKEN, "default_branch": "main", "pulls": [], "commits": {"main": []}}}}


def put_state():
    tmp = os.path.join(DATA, "git.json.tmp")
    with open(tmp, "w") as f:
        json.dump(STATE, f)
    os.replace(tmp, os.path.join(DATA, "git.json"))


def git_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "git.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def until(fn, t=20.0):
    t0 = time.time()
    while time.time() - t0 < t:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def gts(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ghpr(n, title, state="open", body="", ref="feature-x"):
    return {"number": n, "title": title, "body": body, "state": "closed" if state == "merged" else "open",
            "merged_at": gts(datetime.now(timezone.utc)) if state == "merged" else None, "html_url": f"{GH}/acme/app/pull/{n}",
            "user": {"login": "dev"}, "head": {"ref": ref, "sha": f"sha{n:04d}"}, "updated_at": gts(datetime.now(timezone.utc))}


def ghcm(sha, msg, repo="acme/app"):
    at = gts(datetime.now(timezone.utc) + timedelta(seconds=5))
    return {"sha": sha, "html_url": f"{GH}/{repo}/commit/{sha}", "author": {"login": "dev"},
            "commit": {"message": msg, "author": {"name": "Dev", "date": at}, "committer": {"date": at}}}


put_state()
subprocess.run(["cp", os.path.join(N, "fake_git.py"), DATA])
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_git.py"])
time.sleep(0.8)


def mk(name, folder, kind="project"):
    r = A.post(B + "/api/lists", json={"name": name, "folder": folder, "kind": kind, "org_id": ORG})
    return r.json()["id"]


P1, P2, NP = mk("App one", "Apps"), mk("App two", "Apps"), mk("Notes", "Apps", "list")
P3, P4, P5 = mk("App off", "Apps"), mk("App own", "Apps"), mk("App sub", "Apps/Sub")
OUT = mk("Elsewhere", "")
T = {k: A.post(B + "/api/tasks", json={"title": f"Task {k}", "list_id": v}).json()["id"] for k, v in
     (("p1", P1), ("p2", P2), ("np", NP), ("p3", P3), ("p4", P4), ("p5", P5), ("out", OUT))}
for who in (BOB, CL):
    A.put(B + f"/api/lists/{P2}/members", json={"user_id": who, "role": "edit"})
body = {"provider": "github", "base_url": GH, "repo": "acme/app", "token": TOKEN}
# rights: only the folder's owner (a person) connects
check(Bo.post(B + "/api/folders/repos", json={**body, "folder": "Apps"}).status_code == 404, "#934: bob has no folder Apps: 404 (no lists)")
check(requests.post(B + "/api/folders/repos", headers={**CLH, **H}, json={**body, "folder": "Apps"}).status_code in (401, 403), "#934: an agent never connects")
check(A.post(B + "/api/folders/repos", json={**body, "folder": ""}).status_code == 400, "#934: a folder is needed")
check(A.post(B + "/api/folders/repos", json={**body, "folder": "Nope"}).status_code == 404, "#934: a folder without lists: 404")
check(A.post(B + "/api/folders/repos", json={**body, "folder": "Apps", "token": "wrong"}).status_code == 409, "#934: a wrong token is refused, nothing stored")
# a list with its own repository and one switched off
check(A.post(B + f"/api/lists/{P4}/repos", json={**body, "repo": "acme/own"}).status_code == 201, "#934: P4 has its own repository")
r = A.put(B + f"/api/lists/{P3}/folder-repo", json={"use": False})
check(r.ok and r.json()["off"] is True, "#934: P3 switches the folder repository off " + r.text[:120])
check(Bo.put(B + f"/api/lists/{P2}/folder-repo", json={"use": False}).status_code == 403, "#934: an editor cannot switch it off")
check(A.put(B + f"/api/lists/{P2}/folder-repo", json={"use": "no"}).status_code == 400, "#934: use must be true / false")
r = A.post(B + "/api/folders/repos", json={**body, "folder": "Apps"})
check(r.status_code == 201 and r.json().get("folder") == "Apps" and r.json().get("token") is True, "#934: connected to the folder " + r.text[:160])
FC = r.json().get("id")
check(A.post(B + "/api/folders/repos", json={**body, "folder": "Apps"}).status_code == 409, "#934: the same repository twice: 409")
carrier = dbx("SELECT list_id FROM git_conns WHERE id=?", (FC,))[0][0]
check(carrier in (P1, P2, P5) and dbx("SELECT owner_id, folder FROM git_folders WHERE conn_id=?", (FC,)) == [(ALICE, "Apps")],
      "#934: one connection row on a project list of the folder + git_folders " + str(carrier))
j = A.get(B + "/api/folders/repos", params={"folder": "Apps"}).json()
st = {x["id"]: x for x in j.get("lists", [])}
check([x["full_name"] for x in j["repos"]] == ["acme/app"] and st[P1]["uses"] and st[P2]["uses"] and st[P5]["uses"] and not st[P3]["uses"]
      and st[P3]["off"] and st[P4]["own"] and not st[P4]["uses"] and not st[NP]["project"], "#934: the folder dialog: who uses it " + str(st)[:300])
check(OUT not in st, "#934: a list outside the folder is not listed")
# what the lists show
lr = {lid: A.get(B + f"/api/lists/{lid}/repos").json() for lid in (P1, P3, P4, OUT, carrier)}
check([x["full_name"] for x in lr[P1]["folder_repos"]] == ["acme/app"] and lr[P1]["folder"]["uses"] and lr[P1]["repos"] == [] or carrier == P1,
      "#934: P1 shows the folder repository as inherited " + str(lr[P1])[:200])
check(lr[carrier]["repos"] == [] and lr[carrier]["folder"]["uses"], "#934: the carrier list does not show it as its own")
check(lr[P3]["folder"]["off"] and not lr[P3]["folder"]["uses"] and lr[P3]["folder_repos"], "#934: P3 shows it switched off")
check([x["full_name"] for x in lr[P4]["repos"]] == ["acme/own"] and lr[P4]["folder"]["own"], "#934: P4 keeps its own")
check(lr[OUT]["folder"]["folder"] is None and not lr[OUT]["folder_repos"], "#934: a list outside the folder has none")
v = requests.get(V + f"/lists/{P2}/repos", headers=CLH).json()
check([(x["full_name"], x["folder"]) for x in v.get("data", [])] == [("acme/app", "")], "#934: the REST API (agent in P2) reads the folder repository, not the owner's folder name " + str(v)[:200])
bj = Bo.get(B + f"/api/lists/{P2}/repos").json()
check(bj["folder"]["folder"] == "" and bj["folder"]["inherited"] and bj["folder_repos"][0]["folder"] == "" and "Apps" not in json.dumps(bj),
      "#934: bob (member of P2) sees that it comes from the folder, not the folder's name")
lst = {x["id"]: x for x in A.get(B + "/api/state").json()["lists"]}
check([x["full_name"] for x in lst[P5].get("repos", [])] == ["acme/app"] and [x["full_name"] for x in lst[P4].get("repos", [])] == ["acme/own"],
      "#934: the state's list repos (subfolder inherits, own wins)")
check(Ca.get(B + f"/api/lists/{P1}/repos").status_code == 404 and Ca.get(B + "/api/folders/repos", params={"folder": "Apps"}).json().get("repos") == [],
      "#934: carol (other organisation) sees nothing (her own folder Apps is empty)")
# PATCH / DELETE / refresh rights on the folder connection
check(Bo.patch(B + f"/api/repos/{FC}", json={"hook": "on"}).status_code == 403, "#934: bob (sees P2) cannot change the folder repository")
check(Ca.patch(B + f"/api/repos/{FC}", json={"hook": "on"}).status_code == 404, "#934: carol gets 404")
check(Ca.post(B + f"/api/repos/{FC}/refresh").status_code == 404, "#934: carol cannot refresh it")
check(Bo.post(B + f"/api/repos/{FC}/refresh").ok, "#934: bob (a list that uses it) may refresh")
# polling: ONE request series per repository, tasks of all lists
g = STATE["8090"]["acme/app"]
g["pulls"] = [ghpr(1, f"Change for #{T['p2']} and #{T['p5']}", body=f"also #{T['p3']} #{T['p4']} #{T['out']} #{T['np']}")]
g["commits"]["main"] = [ghcm("c0ffee1", f"Work on #{T['p1']}")]
put_state()
time.sleep(1)
dbx("UPDATE git_conns SET next_at=0, polled_at=NULL WHERE id=?", (FC,), write=True)  # baseline read
until(lambda: dbx("SELECT polled_at FROM git_conns WHERE id=?", (FC,))[0][0])
links = lambda: {r[0] for r in dbx("SELECT task_id FROM git_links WHERE conn_id=?", (FC,))}
check(until(lambda: links() >= {T["p1"], T["p2"], T["p5"]}), "#934: #id links tasks of every list that uses it " + str(links()))
check(not links() & {T["p3"], T["p4"], T["out"], T["np"]}, "#934: never a switched-off list, a list with its own repository, a list outside, a plain list")
pulls = [x for x in git_log() if x.get("path", "").startswith("/api/v3/repos/acme/app/pulls")]
check(pulls and not [x for x in git_log() if "/acme/app/" in x.get("path", "") and x.get("port") != 8090], "#934: the folder repository is read from its server")
t2 = until(lambda: (lambda t: t if t and t.get("code", {}).get("prs") else None)(next((x for x in Bo.get(B + "/api/state").json()["tasks"] if x["id"] == T["p2"]), None)))
check(t2 and t2["code"]["prs"][0]["repo"] == "acme/app", "#934: bob sees the pull request at his task in P2")
# fixes #id completes a task of another list of the folder (after the connection)
g["pulls"] = [ghpr(2, f"Fix it, fixes #{T['p5']}", state="merged"), ghpr(3, f"fixes #{T['out']}", state="merged")]
put_state()
dbx("UPDATE git_conns SET next_at=0 WHERE id=?", (FC,), write=True)
check(until(lambda: dbx("SELECT status FROM tasks WHERE id=?", (T["p5"],))[0][0] == 2), "#934: 'fixes #id' completes a task in the subfolder's list")
check(dbx("SELECT status FROM tasks WHERE id=?", (T["out"],))[0][0] == 0, "#934: never a task outside the folder")
# switching back on: P3's tasks are found from then on
check(A.put(B + f"/api/lists/{P3}/folder-repo", json={"use": True}).json()["uses"], "#934: P3 uses it again")
g["commits"]["main"] = [ghcm("c0ffee2", f"Now #{T['p3']}")] + g["commits"]["main"]
put_state()
dbx("UPDATE git_conns SET next_at=0 WHERE id=?", (FC,), write=True)
check(until(lambda: T["p3"] in links()), "#934: switched on again: P3's task is linked")
# a subfolder with its own repository replaces the parent's for its lists
r = A.post(B + "/api/folders/repos", json={**body, "repo": "acme/sub", "folder": "Apps/Sub"})
check(r.status_code == 201, "#934: a subfolder's own repository " + r.text[:120])
j = A.get(B + "/api/folders/repos", params={"folder": "Apps/Sub"}).json()
check(j["inherited"] and j["inherited"]["folder"] == "Apps" and [x["full_name"] for x in j["repos"]] == ["acme/sub"], "#934: the subfolder names its parent's")
check([x["full_name"] for x in A.get(B + f"/api/lists/{P5}/repos").json()["folder_repos"]] == ["acme/sub"], "#934: P5 uses the subfolder's repository now")
# a new list in the folder uses it at once; a list moved out does not
P6 = mk("App new", "Apps")
check([x["full_name"] for x in A.get(B + f"/api/lists/{P6}/repos").json()["folder_repos"]] == ["acme/app"] and A.get(B + f"/api/lists/{P6}/repos").json()["folder"]["uses"],
      "#934: a new project list in the folder uses it")
A.patch(B + f"/api/lists/{P1}", json={"folder": ""})
check(not A.get(B + f"/api/lists/{P1}/repos").json()["folder"]["uses"], "#934: a list moved out of the folder no longer uses it")
# the carrier list leaves / is deleted: the connection moves to another list of the folder
c0 = dbx("SELECT list_id FROM git_conns WHERE id=?", (FC,))[0][0]
A.patch(B + f"/api/lists/{c0}", json={"archived": True})
r = A.delete(B + f"/api/lists/{c0}")
c1 = dbx("SELECT list_id FROM git_conns WHERE id=?", (FC,))
check(r.ok and c1 and c1[0][0] != c0 and dbx("SELECT folder FROM lists WHERE id=?", (c1[0][0],))[0][0].startswith("Apps"),
      "#934: the carrier list deleted: the folder repository moves to another list of the folder " + str((r.status_code, c0, c1)))
# rename the folder: its repositories go along
check(A.post(B + "/api/folders/rename", json={"old": "Apps", "new": "Products"}).ok, "#934: rename the folder")
check(dbx("SELECT folder FROM git_folders WHERE conn_id=?", (FC,)) == [("Products",)] and
      dbx("SELECT folder FROM git_folders WHERE owner_id=? AND folder LIKE 'Products/%'", (ALICE,)) == [("Products/Sub",)], "#934: renamed with its subfolder")
check(A.get(B + f"/api/lists/{P6}/repos").json()["folder"]["folder"] == "Products", "#934: the lists still use it")
# remove: the owner only; the connection and its links go
check(A.delete(B + f"/api/repos/{FC}").ok and not dbx("SELECT 1 FROM git_folders WHERE conn_id=?", (FC,)), "#934: the owner removes it")
check(A.get(B + f"/api/lists/{P6}/repos").json()["folder_repos"] == [], "#934: gone for the lists")
# 2.32 keeps working: new table + a column with a default
cols = {r[1]: r for r in dbx("PRAGMA table_info(lists)")}
check(cols["git_folder_off"][3] == 1 and cols["git_folder_off"][4] == "0", "#934: lists.git_folder_off NOT NULL DEFAULT 0")

print(f"p2330_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
