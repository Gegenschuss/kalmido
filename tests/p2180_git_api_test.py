#!/usr/bin/env python3
"""2.18.0 API tests, package A "Software" (#408 "Software 2" A, B, F), own container with the fake Git servers of fake_git.py
inside (GitHub :8090, Gitea :8091, GitLab :8092 /api/v4, Bitbucket Cloud :8093 /2.0; no real provider is ever called).
 - A: GitLab (nested groups, the web address with /-/..., PRIVATE-TOKEN for gl* tokens, Bearer otherwise, wrong token, not
   found, SSRF guard) and Bitbucket Cloud (workspace access token as Bearer, user:app-password as Basic, Bitbucket Server
   addresses refused); the poller with their shapes: merge requests / pull requests (opened / locked / merged / closed,
   OPEN / MERGED / DECLINED), default-branch commits, commits of open branches (GitLab compare, Bitbucket exclude), CI
   (GitLab statuses, Bitbucket statuses), "fixes #id" on both, rate limits (RateLimit-Remaining, 429 + Retry-After), merge
   request URLs of agents (/-/merge_requests/<n>, /pull-requests/<n>), the inbound webhook (X-Gitlab-Token, Bitbucket
   X-Hub-Signature)
 - B: tags -> milestone reached (baseline: old tags do nothing; v / V prefix; exact; once; undo)
 - F: error reports -> tickets (Sentry issue / event alerts, generic JSON, dedupe while open, a new ticket once closed,
   rate limit, size limit, bad / rotated / switched-off token, a list without ticket types, nothing trusted as HTML,
   rights, the REST API + OpenAPI)
usage: p2180_git_api_test.py <datadir>"""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
GL = "http://127.0.0.1:8092"      # fake GitLab (API under /api/v4)
BB = "http://127.0.0.1:8093"      # fake Bitbucket Cloud (API under /2.0)
GLTOK = "glpat-fake-read-api-7c1d"
GLOAUTH = "oauth-fake-token-55aa"
BBTOK = "bb-workspace-access-token-91"
BBBASIC = "devuser:app-password-x1"
FAILS, OKS = [], [0]
SEEN = []


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


class S(requests.Session):
    def request(self, *a, **k):
        r = super().request(*a, **k)
        SEEN.append(r.text)
        return r


def sess(user, pw="password123"):
    s = S()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        r = requests.request(m, V + p, headers=self.h, timeout=60, **k)
        SEEN.append(r.text)
        return r


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


STATE = {}


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


def dbq(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def dbw(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def until(fn, t=20.0):
    t0 = time.time()
    while time.time() - t0 < t:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def task_of(s, tid):
    return next((x for x in s.get(B + "/api/state").json()["tasks"] if x["id"] == tid), None)


def acts(s, tid, kind=None):
    return [a for a in s.get(B + f"/api/tasks/{tid}/timeline").json()["activity"] if kind is None or a["kind"] == kind]


# ------------------------------------------------------------------ provider shapes
NOW = datetime.now(timezone.utc)
LATER = iso(NOW + timedelta(minutes=5))   # after the connection is made
OLD = iso(NOW - timedelta(days=3))


def gl_mr(iid, title, state="opened", desc="", ref="feature", sha=None, merged_at=None, repo="grp/sub/app"):
    return {"iid": iid, "id": 9000 + iid, "title": title, "description": desc, "state": state, "author": {"username": "gdev"},
            "web_url": f"{GL}/{repo}/-/merge_requests/{iid}", "source_branch": ref, "sha": sha or f"gl{iid:04d}",
            "updated_at": iso(datetime.now(timezone.utc)), "merged_at": merged_at}


def gl_cm(sha, msg, at=None, repo="grp/sub/app"):
    at = at or iso(datetime.now(timezone.utc))
    return {"id": sha, "short_id": sha[:8], "message": msg, "author_name": "G Dev", "authored_date": at, "committed_date": at,
            "web_url": f"{GL}/{repo}/-/commit/{sha}"}


def bb_pr(n, title, state="OPEN", desc="", ref="feature/x", sha=None, updated=None, repo="ws/web"):
    return {"id": n, "title": title, "description": desc, "state": state, "author": {"nickname": "bdev", "display_name": "B Dev"},
            "links": {"html": {"href": f"{BB}/{repo}/pull-requests/{n}"}}, "source": {"branch": {"name": ref}, "commit": {"hash": sha or f"bb{n:04d}"}},
            "updated_on": updated or iso(datetime.now(timezone.utc))}


def bb_cm(sha, msg, at=None, repo="ws/web"):
    at = at or iso(datetime.now(timezone.utc))
    return {"hash": sha, "message": msg, "date": at, "author": {"raw": "B Dev <b@example.test>"}, "links": {"html": {"href": f"{BB}/{repo}/commits/{sha}"}}}


def start():
    extra = ["-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1", "-e KALMIDO_GIT_POLL=2", "-e KALMIDO_GIT_TICK=1", "-e KALMIDO_SECRET_KEY=" + KEY,
             "-e KALMIDO_ERROR_REPORTS_PER_HOUR=5"]
    env = dict(os.environ, EXTRA=" ".join(extra))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    put_state()
    subprocess.run(["cp", os.path.join(N, "fake_git.py"), DATA])
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_git.py"])
    time.sleep(0.8)


STATE.update({"8092": {}, "8093": {}})
start()
s0 = S()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ids = {"alice": 1}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for x in (A, Bo, Ca, Da):
    x.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
assert r.status_code == 201, r.text
AG, AGTOK = r.json()["id"], r.json()["token"]
ag = Api(AGTOK)
P = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
Q = A.post(B + "/api/lists", json={"name": "Site", "kind": "project"}).json()["id"]
PLAIN = A.post(B + "/api/lists", json={"name": "Groceries"}).json()["id"]
check(A.patch(B + f"/api/lists/{P}", json={"tickets": True}).ok, "ticket types on for P")
for u, role in (("bob", "edit"), ("carol", "view"), ("dave", "admin")):
    assert A.put(B + f"/api/lists/{P}/members", json={"user_id": ids[u], "role": role}).ok
assert A.put(B + f"/api/lists/{P}/members", json={"user_id": AG, "role": "edit"}).ok
SEC1 = A.post(B + "/api/sections", json={"list_id": P, "name": "Inbox bugs"}).json().get("id")
A.post(B + "/api/sections", json={"list_id": P, "name": "Later"})

T = {}
for k in range(1, 11):
    T[k] = A.post(B + "/api/tasks", json={"title": f"Task {k}", "list_id": P}).json()["id"]

# ================================================================== A: GitLab + Bitbucket: the repositories (before connecting)
STATE["8092"]["grp/sub/app"] = {
    "token": GLTOK, "default_branch": "main",
    "pulls": [gl_mr(3, f"Fix login #{T[1]}", sha="gl111"),
              gl_mr(4, "Merged one", state="merged", desc=f"closes #{T[3]}", ref="m", merged_at=LATER),
              gl_mr(5, f"Being merged #{T[4]}", state="locked", ref="l", sha="gl444"),
              gl_mr(6, f"Abandoned #{T[5]}", state="closed", ref="c"),
              gl_mr(7, "Branch only", ref=f"kalmido-{T[2]}", sha="gl222"),
              gl_mr(8, "Old merged", state="merged", desc=f"fixes #{T[10]}", ref="o", merged_at=OLD)],
    "commits": {"main": [gl_cm("glc0001", f"fixes #{T[6]}: done", at=LATER), gl_cm("glc0002", f"Refs #{T[1]}")]},
    "compare": {f"kalmido-{T[2]}": [gl_cm("glb0001", "wip on the branch")]},
    "status": {"gl111": [{"status": "success", "name": "build"}, {"status": "failed", "name": "test"}],
               "gl444": [{"status": "running", "name": "build"}], "gl222": [{"status": "success"}]},
    "tags": [{"name": "v2.17.0"}, {"name": "v1.0.0"}]}
STATE["8092"]["grp/oauth"] = {"token": GLOAUTH, "default_branch": "trunk", "pulls": [], "commits": {"trunk": []}}
STATE["8093"]["ws/web"] = {
    "token": BBTOK, "default_branch": "master",
    "pulls": [bb_pr(7, f"New page #{T[7]}", sha="bb777"),
              bb_pr(8, "Merged page", state="MERGED", desc=f"fixes #{T[8]}", ref="p8", updated=LATER),
              bb_pr(9, f"Declined #{T[9]}", state="DECLINED", ref="p9")],
    "commits": {"master": [bb_cm("bbc0001", f"Refs #{T[7]} on master")]},
    "compare": {"feature/x": [bb_cm("bbb0002", f"second on branch #{T[7]}"), bb_cm("bbb0001", f"first on branch (#{T[7]})")]},
    "status": {"bb777": [{"state": "INPROGRESS"}, {"state": "SUCCESSFUL"}]},
    "tags": [{"name": "V2.0"}]}
STATE["8093"]["ws/basic"] = {"token": BBBASIC, "default_branch": "main", "pulls": [], "commits": {"main": []}}
put_state()

# ================================================================== A: connecting
gl = {"provider": "gitlab", "base_url": GL, "repo": "grp/sub/app", "token": GLTOK}
check(Bo.post(B + f"/api/lists/{P}/repos", json=gl).status_code == 403, "a member cannot connect GitLab")
for bad in ({**gl, "repo": "grp/sub/a b"}, {**gl, "repo": "grp//app"}, {**gl, "token": "has space"}, {**gl, "provider": "svn"},
            {"provider": "bitbucket", "repo": "https://bb.example.test/projects/KEY/repos/web"}):
    r = A.post(B + f"/api/lists/{P}/repos", json=bad)
    check(r.status_code == 400, f"invalid input refused: {bad.get('repo')} {bad.get('provider')} -> {r.status_code} {r.text[:100]}")
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "bitbucket", "repo": "https://bb.example.test/projects/KEY/repos/web"})
check("Bitbucket Cloud" in r.json().get("error", ""), f"Bitbucket Server address: a clear message: {r.text[:150]}")
r = A.post(B + f"/api/lists/{P}/repos", json={**gl, "repo": "grp/sub/nope"})
check(r.status_code == 409 and "not found" in r.json().get("error", "").lower(), f"GitLab: unknown project: {r.status_code} {r.text[:120]}")
r = A.post(B + f"/api/lists/{P}/repos", json={**gl, "token": "glpat-wrong"})
check(r.status_code == 409 and "token" in r.json().get("error", "").lower(), f"GitLab: wrong token: {r.status_code} {r.text[:120]}")
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "gitlab", "base_url": "http://10.255.1.2", "repo": "x/y"})
check(r.status_code == 502 and "private network" in r.json().get("error", ""), f"SSRF guard (GitLab): {r.status_code} {r.text[:120]}")
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "bitbucket", "base_url": "http://10.255.1.2", "repo": "x/y"})
check(r.status_code == 502 and "private network" in r.json().get("error", ""), f"SSRF guard (Bitbucket): {r.status_code} {r.text[:120]}")
n0 = len(git_log())
r = Da.post(B + f"/api/lists/{P}/repos", json={"provider": "gitlab", "repo": f"{GL}/grp/sub/app/-/tree/main", "token": GLTOK})
check(r.status_code == 201, f"GitLab connected via the web address (nested group, /-/tree/...): {r.status_code} {r.text[:200]}")
GLID = r.json().get("id")
j = r.json()
check(j.get("provider") == "gitlab" and j.get("full_name") == "grp/sub/app" and j.get("owner") == "grp/sub" and j.get("repo") == "app"
      and j.get("base_url") == GL and j.get("web_url") == f"{GL}/grp/sub/app" and j.get("default_branch") == "main" and j.get("token") is True,
      f"GitLab answer: {j}")
check(A.post(B + f"/api/lists/{P}/repos", json=gl).status_code == 409, "the same GitLab project twice: 409")
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "gitlab", "base_url": GL, "repo": "grp/oauth", "token": GLOAUTH})
check(r.status_code == 201 and r.json().get("default_branch") == "trunk", f"GitLab with an OAuth token: {r.status_code} {r.text[:150]}")
GLID2 = r.json().get("id")
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "bitbucket", "base_url": BB, "repo": "ws/web", "token": BBTOK})
check(r.status_code == 201 and r.json().get("default_branch") == "master" and r.json().get("full_name") == "ws/web", f"Bitbucket connected: {r.status_code} {r.text[:200]}")
BBID = r.json().get("id")
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "bitbucket", "repo": f"{BB}/ws/basic", "token": BBBASIC})
check(r.status_code == 201 and r.json().get("base_url") == BB, f"Bitbucket via the address with user:app-password: {r.status_code} {r.text[:200]}")
BBID2 = r.json().get("id")
lg = git_log()[n0:]
gl_ok = [x for x in lg if x["port"] == 8092 and x["status"] in (200, 304)]
check(gl_ok and all(x["path"].startswith("/api/v4/projects/grp%2Fsub%2Fapp") or x["path"].startswith("/api/v4/projects/grp%2Foauth") for x in gl_ok),
      "GitLab: the project path URL-encoded: " + ", ".join(sorted({x["path"].split("?")[0] for x in gl_ok}))[:300])
check(any(x["ptok"] == GLTOK and not x["auth"] for x in gl_ok), "GitLab: a glpat token goes as PRIVATE-TOKEN")
check(any(x["auth"] == "Bearer " + GLOAUTH and not x["ptok"] for x in gl_ok), "GitLab: another token goes as Bearer")
bb_ok = [x for x in lg if x["port"] == 8093 and x["status"] in (200, 304)]
check(any(x["auth"] == "Bearer " + BBTOK for x in bb_ok), "Bitbucket: an access token as Bearer")
check(any(x["auth"] == "Basic " + base64.b64encode(BBBASIC.encode()).decode() for x in bb_ok), "Bitbucket: user:app-password as Basic")
row = dbq("SELECT token FROM git_conns WHERE id=?", (GLID,))[0][0]
check(row.startswith("v1.") and GLTOK not in row, "GitLab token sealed")
j = A.get(B + f"/api/lists/{P}/repos").json()
check([x["provider"] for x in j["repos"]] == ["gitlab", "gitlab", "bitbucket", "bitbucket"], f"repos of the list: {[x['provider'] for x in j['repos']]}")
check([x["full_name"] for x in ag.req("GET", f"/lists/{P}/repos").json().get("data", [])] == ["grp/sub/app", "grp/oauth", "ws/web", "ws/basic"], "v1: repos")

# ================================================================== A: the poller
t1 = until(lambda: (lambda t: t if t and t.get("code", {}).get("prs") and t["code"]["prs"][0].get("ci") else None)(task_of(Bo, T[1])), 25)
code = (t1 or {}).get("code") or {}
check(code.get("prs") and code["prs"][0]["n"] == 3 and code["prs"][0]["state"] == "open" and code["prs"][0]["author"] == "gdev"
      and code["prs"][0]["url"] == f"{GL}/grp/sub/app/-/merge_requests/3", f"GitLab MR linked via #id: {code.get('prs')}")
check(code.get("prs") and code["prs"][0]["ci"] == "failure", f"GitLab CI: success + failed = failure: {code.get('prs')}")
check([m["short"] for m in code.get("commits", [])] == ["glc0002"], f"GitLab commit linked: {code.get('commits')}")
t2 = until(lambda: (lambda t: t if t and t.get("code", {}).get("commits") and t["code"].get("prs") else None)(task_of(A, T[2])), 15)
check(t2 and t2["code"]["prs"][0]["n"] == 7 and [m["sha"] for m in t2["code"]["commits"]] == ["glb0001"],
      f"GitLab: MR via the branch name + the branch commit (compare): {t2 and t2.get('code')}")
check(any("/repository/compare?from=main&to=kalmido-" in x["path"] for x in git_log()), "GitLab compare from/to")
check(until(lambda: task_of(A, T[3])["status"] == 2), "GitLab: 'closes #id' in a merged MR completed it")
t4 = until(lambda: (lambda t: t if t.get("code", {}).get("prs") and t["code"]["prs"][0].get("ci") else None)(task_of(A, T[4])), 15)
check(t4 and t4["code"]["prs"][0]["state"] == "open" and t4["code"]["prs"][0]["ci"] == "pending", f"GitLab locked = open, running = pending: {t4 and t4['code']}")
t5 = task_of(A, T[5])
check(t5.get("code", {}).get("prs") and t5["code"]["prs"][0]["state"] == "closed", f"GitLab closed MR: {t5.get('code')}")
check(until(lambda: task_of(A, T[6])["status"] == 2), "GitLab: 'fixes #id' in a default-branch commit")
check(task_of(A, T[10])["status"] == 0, "GitLab: an MR merged before the connection does not complete")
t7 = until(lambda: (lambda t: t if t.get("code", {}).get("prs") and t["code"]["prs"][0].get("ci") and t["code"].get("commits") else None)(task_of(A, T[7])), 20)
check(t7 and t7["code"]["prs"][0]["n"] == 7 and t7["code"]["prs"][0]["repo"] == "ws/web" and t7["code"]["prs"][0]["state"] == "open"
      and t7["code"]["prs"][0]["author"] == "bdev" and t7["code"]["prs"][0]["url"] == f"{BB}/ws/web/pull-requests/7", f"Bitbucket PR: {t7 and t7.get('code')}")
check(t7 and t7["code"]["prs"][0]["ci"] == "pending", "Bitbucket CI: INPROGRESS + SUCCESSFUL = pending")
check(t7 and "bbc0001" in [m["sha"] for m in t7["code"]["commits"]] and t7["code"]["commits"][0]["author"] == "B Dev",
      f"Bitbucket commit (author without the address): {t7 and t7['code']['commits']}")
check(any("/commits/feature%2Fx?exclude=master" in x["path"] for x in git_log()), "Bitbucket: branch commits via exclude")
t7c = until(lambda: (lambda t: t if {"bbb0001", "bbb0002"} <= {m["sha"] for m in t.get("code", {}).get("commits", [])} else None)(task_of(A, T[7])), 10)
check(t7c, "Bitbucket: the branch's own commits (exclude = the default branch) linked")
check(until(lambda: task_of(A, T[8])["status"] == 2), "Bitbucket: 'fixes #id' in a MERGED PR completed it")
t9 = task_of(A, T[9])
check(t9.get("code", {}).get("prs") and t9["code"]["prs"][0]["state"] == "closed", "Bitbucket DECLINED = closed")
act = acts(A, T[8], "git_done")
check(act and act[0]["data"].get("kind") == "pr" and act[0]["data"].get("repo") == "ws/web" and act[0]["user_id"] is None, f"activity names the PR: {act}")
check(not acts(A, T[1], "git_pr"), "baseline: no 'opened' lines for MRs that existed")
# later: a new MR -> opened line
STATE["8092"]["grp/sub/app"]["pulls"].insert(0, gl_mr(9, f"Second try #{T[1]}", ref="again", sha="gl999"))
put_state()
check(until(lambda: [(a["data"]["n"], a["data"]["state"]) for a in acts(A, T[1], "git_pr")] == [(9, "opened")], 15), "a new GitLab MR: 'opened'")
# ETag on GitLab
check(until(lambda: any(x["port"] == 8092 and x["status"] == 304 and x["inm"] for x in git_log()), 12), "GitLab: If-None-Match -> 304")

# rate limits: GitLab RateLimit-Remaining low, then 429 + Retry-After
STATE["gl_remaining"] = 3
put_state()
dbw("UPDATE git_conns SET next_at=0, last_error='' WHERE id=?", (GLID,))
row = until(lambda: (lambda r: r if r and r[0][0] == "rate" else None)(dbq("SELECT last_error, next_at FROM git_conns WHERE id=?", (GLID,))), 12)
check(row and row[0][1] > time.time() + 60, f"GitLab RateLimit-Remaining low: paused until the reset: {row}")
STATE["gl_remaining"] = 1999
STATE["gl_block"] = True
put_state()
dbw("UPDATE git_conns SET next_at=0, last_error='', etags='{}' WHERE id=?", (GLID,))
row = until(lambda: (lambda r: r if r and r[0][0] == "rate" else None)(dbq("SELECT last_error, next_at FROM git_conns WHERE id=?", (GLID,))), 12)
check(row and row[0][1] > time.time() + 90, f"429 + Retry-After: paused: {row and row[0][1] - time.time()}")
STATE["gl_block"] = False
put_state()
dbw("UPDATE git_conns SET next_at=0, last_error='' WHERE id=?", (GLID,))

# ================================================================== A: merge requests of agents
T11 = A.post(B + "/api/tasks", json={"title": "Agent work", "list_id": P, "assignee_id": AG}).json()["id"]
for u, n, ok_ in ((f"{GL}/grp/sub/app/-/merge_requests/12", 12, True), (f"{GL}/grp/sub/app/-/merge_requests/12/diffs", 12, True),
                  (f"{BB}/ws/web/pull-requests/13", 13, True), (f"{GL}/grp/sub/app/pull/12", 0, False), (f"{BB}/ws/web/pull/13", 0, False),
                  (f"{GL}/grp/app/-/merge_requests/12", 0, False)):
    r = ag.req("POST", f"/tasks/{T11}/comments", json={"body": "Ready", "suggestion": {"kind": "merge_request", "pr_url": u}})
    if ok_:
        sug = r.json().get("suggestion") or {}
        check(r.status_code in (200, 201) and sug.get("number") == n, f"merge request URL accepted: {u} -> {r.status_code} {sug}")
    else:
        check(r.status_code == 400, f"merge request URL refused: {u} -> {r.status_code}")
t11 = task_of(A, T11)
check({p["n"] for p in t11.get("code", {}).get("prs", [])} >= {12, 13}, f"merge requests linked at once: {t11.get('code')}")

# ================================================================== A: inbound webhooks
sec = A.patch(B + f"/api/repos/{GLID}", json={"hook": "on"}).json().get("hook_secret")
sec2 = A.patch(B + f"/api/repos/{BBID}", json={"hook": "on"}).json().get("hook_secret")
check(sec and sec2, "webhooks on")
raw = json.dumps({"object_kind": "push"}).encode()
dbw("UPDATE git_conns SET next_at=?, polled_at=? WHERE id IN (?,?)", (time.time() + 999, "2000-01-01T00:00:00+00:00", GLID, BBID))
r = requests.post(B + f"/api/hooks/git/{GLID}", data=raw, headers={"X-Gitlab-Token": "wrong", "X-Gitlab-Event": "Push Hook"})
check(r.status_code == 401, f"GitLab: wrong token: {r.status_code}")
r = requests.post(B + f"/api/hooks/git/{GLID}", data=raw, headers={"X-Gitlab-Token": sec, "X-Gitlab-Event": "Push Hook"})
check(r.status_code == 202, f"GitLab: X-Gitlab-Token, no login, no CSRF header: {r.status_code} {r.text[:100]}")
check(until(lambda: dbq("SELECT next_at FROM git_conns WHERE id=?", (GLID,))[0][0] < time.time() + 900, 5), "GitLab hook triggers a poll")
r = requests.post(B + f"/api/hooks/git/{BBID}", data=raw, headers={"X-Hub-Signature": "sha256=" + "0" * 64, "X-Event-Key": "repo:push"})
check(r.status_code == 401, f"Bitbucket: wrong signature: {r.status_code}")
r = requests.post(B + f"/api/hooks/git/{BBID}", data=raw, headers={"X-Hub-Signature": "sha256=" + hmac.new(sec2.encode(), raw, hashlib.sha256).hexdigest(),
                                                                   "X-Event-Key": "repo:push"})
check(r.status_code == 202, f"Bitbucket: X-Hub-Signature sha256: {r.status_code} {r.text[:100]}")
r = requests.post(B + f"/api/hooks/git/{BBID}", data=raw, headers={"X-Gitlab-Token": sec})
check(r.status_code == 401, "another connection's secret is refused")

# ================================================================== B: tags -> milestone reached
check(until(lambda: all(x[0] for x in dbq("SELECT tags_at FROM git_conns WHERE id IN (?,?)", (GLID, BBID))), 15), "the tag baseline was taken")
check({x[0] for x in dbq("SELECT name FROM git_tags WHERE conn_id=?", (GLID,))} == {"v2.17.0", "v1.0.0"}, "the existing tags are recorded")
M = {}
for k, title in (("m218", "Release 2.18.0"), ("m217", "2.17.0"), ("m3", "v3.0 launch"), ("m219", "2.19.0"), ("plain", "2.18.0 notes"),
                 ("rc", "Release 2.20.0")):
    M[k] = A.post(B + "/api/tasks", json={"title": title, "list_id": P}).json()["id"]
    if k != "plain":
        dbw("UPDATE tasks SET ms=1 WHERE id=?", (M[k],))
time.sleep(2.5)
check(task_of(A, M["m217"])["status"] == 0, "an old tag (baseline v2.17.0) does not complete milestone 2.17.0")
g = STATE["8092"]["grp/sub/app"]
g["tags"] = [{"name": "v2.18.0"}, {"name": "v2.20.0-rc1"}, {"name": "v2.17.0"}, {"name": "v1.0.0"}]
STATE["8093"]["ws/web"]["tags"] = [{"name": "V3.0"}, {"name": "V2.0"}]
put_state()
dbw("UPDATE git_conns SET next_at=0 WHERE id IN (?,?)", (GLID, BBID))
check(until(lambda: task_of(A, M["m218"])["status"] == 2, 20), "new tag v2.18.0 completed milestone 'Release 2.18.0'")
check(until(lambda: task_of(A, M["m3"])["status"] == 2, 20), "Bitbucket tag V3.0 completed milestone 'v3.0 launch' (case, v prefix)")
check(task_of(A, M["plain"])["status"] == 0, "a plain task with the version in the title stays open (milestones only)")
check(task_of(A, M["rc"])["status"] == 0, "v2.20.0-rc1 is not 2.20.0 (exact, never fuzzy)")
check(task_of(A, M["m219"])["status"] == 0, "other milestones stay open")
a = acts(A, M["m218"], "git_done")
check(a and a[0]["data"].get("kind") == "tag" and a[0]["data"].get("ref") == "v2.18.0" and a[0]["data"].get("repo") == "grp/sub/app"
      and a[0]["data"].get("url") == f"{GL}/grp/sub/app/-/tags/v2.18.0" and a[0]["user_id"] is None, f"activity names repo + tag: {a}")
a = acts(A, M["m3"], "git_done")
check(a and a[0]["data"].get("url") == f"{BB}/ws/web/src/V3.0", f"Bitbucket tag link: {a and a[0]['data']}")
r = A.post(B + f"/api/tasks/{M['m218']}/git-undo")
check(r.ok and r.json()["status"] == 0, f"undo reopens the milestone: {r.status_code} {r.text[:100]}")
dbw("UPDATE git_conns SET next_at=0, etags='{}' WHERE id=?", (GLID,))
time.sleep(3)
check(task_of(A, M["m218"])["status"] == 0, "once: the same tag does not complete it again after the undo")
# a later tag for a milestone created later
g["tags"].insert(0, {"name": "v2.19.0"})
put_state()
dbw("UPDATE git_conns SET next_at=0 WHERE id=?", (GLID,))
check(until(lambda: task_of(A, M["m219"])["status"] == 2, 20), "the next tag v2.19.0 completes milestone 2.19.0")

# ================================================================== F: error reports -> tickets
j = A.get(B + f"/api/lists/{P}/error-hook").json()
check(j.get("on") is False and j.get("may") is True, f"off at first, the owner may switch it: {j}")
check(Bo.get(B + f"/api/lists/{P}/error-hook").json().get("may") is False, "a member may not")
check(Bo.patch(B + f"/api/lists/{P}/error-hook", json={"state": "on"}).status_code == 403, "a member cannot switch it on")
check(Ca.patch(B + f"/api/lists/{P}/error-hook", json={"state": "on"}).status_code == 403, "a viewer cannot switch it on")
check(ag.req("PATCH", f"/lists/{P}/error-hook", json={"state": "on"}).status_code == 403, "an agent cannot switch it on")
check(A.patch(B + f"/api/lists/{PLAIN}/error-hook", json={"state": "on"}).status_code == 409, "project lists only")
check(A.patch(B + f"/api/lists/{P}/error-hook", json={"state": "maybe"}).status_code == 400, "invalid state")
check(A.patch(B + f"/api/lists/{P}/error-hook", json={"state": "on", "x": 1}).status_code == 400, "unknown field")
r = Da.patch(B + f"/api/lists/{P}/error-hook", json={"state": "on"})
URL = r.json().get("url", "")
check(r.ok and r.json().get("on") and f"/api/hooks/issues/{P}/" in URL, f"a list admin switches it on, the URL once: {r.text[:200]}")
TOK = URL.rsplit("/", 1)[-1]
EP = B + f"/api/hooks/issues/{P}/{TOK}"
check(TOK not in A.get(B + f"/api/lists/{P}/error-hook").text and TOK not in A.get(B + f"/api/lists/{P}/repos").text, "the URL is never shown again")
check(not any(TOK in str(x) for x in dbq("SELECT * FROM issue_hooks")), "the token is stored only hashed")
check(A.get(B + f"/api/lists/{P}/repos").json().get("errors", {}).get("on") is True, "the repos answer carries the error-hook state")
# generic report
gen = {"title": "Crash in <b>export</b>", "body": "Traceback:\n  File \"x.py\" <script>alert(1)</script>\n```\nnot a fence end", "url": "https://errors.example.test/e/1",
       "level": "error", "fingerprint": "export-crash"}
r = requests.post(EP, json=gen)
check(r.status_code == 201 and r.json().get("created"), f"generic report -> a new ticket, no login, no CSRF header: {r.status_code} {r.text[:150]}")
E1 = r.json().get("task_id")
t = task_of(A, E1) or {}
check(t.get("title") == "Crash in <b>export</b>" and t.get("ttype") == "bug" and t.get("section_id") == SEC1 and t.get("url") == gen["url"],
      f"bug ticket in the first section with the link: {[t.get(k) for k in ('title', 'ttype', 'section_id', 'url')]}")
ct = dbq("SELECT content, created_by FROM tasks WHERE id=?", (E1,))[0]
check(ct[1] is None, "created by nobody (system)")
check("\\<b\\>export\\</b\\>" in ct[0] and "<script>" in ct[0] and "````text\n" in ct[0] and "**Steps to reproduce**" in ct[0]
      and "https://errors.example.test/e/1" in ct[0], f"notes: escaped title, body in a code block (longer fence), the bug template, the link:\n{ct[0][:500]}")
# 2.18.0 (owner decision): a NEW error -> exactly one News item (+ push) per person who sees the list; repeats stay quiet
NE1 = dbq("SELECT COUNT(*) FROM notifications WHERE kind='errreport' AND task_id=?", (E1,))[0][0]
check(NE1 >= 2, f"a new error: News for the people of the list ({NE1})")
check(any(it.get("kind") == "errreport" and it.get("task_id") == E1 for it in Bo.get(B + "/api/news").json().get("items", [])),
      "the member sees it in News")
a = acts(A, E1, "created")
check(a and a[0]["user_id"] is None and a[0]["data"].get("report") == "generic", f"activity: created from an error report: {a}")
for n in (2, 3):
    r = requests.post(EP, json={**gen, "title": "Crash in export (changed text)"})
    check(r.status_code == 200 and r.json().get("duplicate") and r.json().get("task_id") == E1 and r.json().get("count") == n, f"the same fingerprint: counted ({n}): {r.text[:150]}")
check(dbq("SELECT COUNT(*) FROM notifications WHERE kind='errreport' AND task_id=?", (E1,))[0][0] == NE1, "repeats of the same error: no further News")
a = acts(A, E1, "err_again")
check(len(a) == 1 and a[0]["data"].get("n") == 3, f"one 'happened again' line that counts up: {a}")
# Sentry issue alert, then the same issue as an event alert
sentry_issue = {"action": "created", "installation": {"uuid": "x"}, "data": {"issue": {
    "id": "4711", "shortId": "APP-1", "title": "TypeError: x is undefined", "culprit": "app.js in render", "level": "error",
    "permalink": "https://sentry.example.test/organizations/o/issues/4711/", "metadata": {"type": "TypeError", "value": "x is undefined"}}}}
r = requests.post(EP, json=sentry_issue)
check(r.status_code == 201, f"Sentry issue alert -> a ticket: {r.status_code} {r.text[:150]}")
E2 = r.json().get("task_id")
ct = dbq("SELECT content, url FROM tasks WHERE id=?", (E2,))[0]
check("Sentry" in ct[0] and "app.js in render" in ct[0] and ct[1] == "https://sentry.example.test/organizations/o/issues/4711/", f"Sentry details: {ct}")
check(acts(A, E2, "created")[0]["data"].get("report") == "sentry", "activity: from Sentry")
sentry_event = {"action": "triggered", "data": {"event": {"issue_id": "4711", "event_id": "abc", "title": "TypeError: x is undefined",
                                                          "culprit": "app.js in render", "level": "error", "web_url": "https://sentry.example.test/e/abc"}}}
r = requests.post(EP, json=sentry_event)
check(r.status_code == 200 and r.json().get("task_id") == E2 and r.json().get("count") == 2, f"Sentry event alert of the same issue: counted: {r.text[:150]}")
# closed ticket -> the next report makes a new one
A.post(B + f"/api/tasks/{E2}/complete", json={})
r = requests.post(EP, json=sentry_event)
check(r.status_code == 201 and r.json().get("task_id") not in (None, E2), f"after the ticket was closed: a new ticket: {r.text[:150]}")
check(dbq("SELECT COUNT(*) FROM notifications WHERE kind='errreport' AND task_id=?", (E2,))[0][0] >= 1 and dbq("SELECT COUNT(*) FROM notifications WHERE kind='errreport' AND task_id=?", (r.json().get("task_id"),))[0][0] == 0, "a known error coming back (new ticket): no News, only a new error is announced")
# no fingerprint: hash of title + culprit
r1 = requests.post(EP, json={"title": "Timeout", "culprit": "api/sync"})
r2 = requests.post(EP, json={"title": "Timeout", "culprit": "api/sync", "body": "other body"})
check(r1.status_code == 201 and r2.status_code == 200 and r2.json().get("task_id") == r1.json().get("task_id"), "no fingerprint: title + culprit dedupe")
# bad input / tokens
check(requests.post(B + f"/api/hooks/issues/{P}/wrongtoken", json=gen).status_code == 404, "bad token: 404")
check(requests.post(B + f"/api/hooks/issues/{Q}/{TOK}", json=gen).status_code == 404, "the token of another list: 404")
check(requests.post(EP, data=b"{not json", headers={"Content-Type": "application/json"}).status_code == 400, "invalid JSON: 400")
check(requests.post(EP, json={"foo": 1}).status_code == 400, "an unknown shape: 400")
check(requests.post(EP, json={"title": "   "}).status_code == 400, "an empty title: 400")
check(requests.post(EP, json={"title": "Big", "body": "x" * 300000}).status_code == 413, "too large: 413")
r = requests.post(EP, json={"title": "Bad link", "url": "javascript:alert(1)", "level": "<b>"})
t = task_of(A, r.json().get("task_id")) or {}
check(r.status_code == 201 and not t.get("url") and "javascript" not in dbq("SELECT content FROM tasks WHERE id=?", (t.get("id"),))[0][0],
      "only http(s) links are kept")
# rate limit: 5 new tickets per hour in this test (KALMIDO_ERROR_REPORTS_PER_HOUR=5) -- P has made 5 already
r = requests.post(EP, json={"title": "One too many"})
check(r.status_code == 202 and r.json().get("limited"), f"over the hourly limit: only counted: {r.status_code} {r.text[:120]}")
NALL = dbq("SELECT COUNT(*) FROM notifications WHERE kind='errreport'")[0][0]
r = requests.post(EP, json={"title": "One too many"})
check(r.status_code == 202 and dbq("SELECT count, task_id FROM issue_reports WHERE list_id=? AND fp LIKE 'h:%' AND task_id IS NULL", (P,))[0] == (2, None),
      "counted again, still no ticket")
check(dbq("SELECT COUNT(*) FROM notifications WHERE kind='errreport'")[0][0] == NALL, "over the limit: no News / push")
r = requests.post(EP, json={**gen})
check(r.status_code == 200 and r.json().get("task_id") == E1, "a repeat of an open ticket is still counted over the limit")
# rotate + off
r = A.patch(B + f"/api/lists/{P}/error-hook", json={"state": "rotate"})
URL2 = r.json().get("url", "")
check(r.ok and URL2 and URL2 != URL, "rotate: a new URL")
check(requests.post(EP, json=gen).status_code == 404, "the old URL stops working")
check(requests.post(URL2.replace(URL2.split("/api/")[0], B), json=gen).status_code == 200, "the new URL works")
j = ag.req("GET", f"/lists/{P}/error-hook").json()
check(j.get("on") is True and "url" not in j and j.get("received", 0) >= 10 and j.get("open", 0) >= 3, f"v1: the state (no URL): {j}")
check(A.patch(B + f"/api/lists/{P}/error-hook", json={"state": "off"}).json().get("on") is False, "off")
check(requests.post(URL2.replace(URL2.split("/api/")[0], B), json=gen).status_code == 404, "off: 404")
# a list without ticket types
r = A.patch(B + f"/api/lists/{Q}/error-hook", json={"state": "on"})
EQ = B + "/api/hooks/issues/" + r.json()["url"].split("/api/hooks/issues/")[1]
r = requests.post(EQ, json={"title": "Page 500", "body": "boom"})
t = task_of(A, r.json().get("task_id")) or {}
cq = dbq("SELECT content FROM tasks WHERE id=?", (t.get("id"),))[0][0]
check(r.status_code == 201 and not t.get("ttype") and not t.get("section_id") and "Steps to reproduce" not in cq and "boom" in cq,
      f"no ticket types: a plain task without template, no section: {t.get('ttype')!r} {cq[:200]}")
# 2.18.0 review (R6): only what Markdown interprets mid-line is escaped (no "\(" noise in the editor); links stay text
r = requests.post(EQ, json={"title": "TypeError: x (reading 'id') in __init__ *a* [b] <i> ~c~ & see https://e.example.test/x"})
cq = dbq("SELECT content FROM tasks WHERE id=?", (r.json().get("task_id"),))[0][0]
check(r.status_code == 201 and "(reading 'id')" in cq and "\\_\\_init\\_\\_" in cq and "\\*a\\*" in cq and "\\[b\\]" in cq and "\\<i\\>" in cq
      and "\\~c\\~" in cq and "\\&" in cq and "https\\://e.example.test/x" in cq and "\\(" not in cq,
      f"error title: parentheses plain, Markdown characters escaped, the link no link: {cq[:300]}")
# OpenAPI
spec = requests.get(V + "/openapi.json").json()
check("/lists/{id}/error-hook" in spec.get("paths", {}) and set(spec["components"]["schemas"]["Repo"]["properties"]["provider"]["enum"]) == {"github", "gitea", "gitlab", "bitbucket"},
      "OpenAPI: error hook + the providers")
# removal cleans tags
check(A.delete(B + f"/api/repos/{GLID2}").ok, "remove a GitLab repo")
check(A.delete(B + f"/api/repos/{BBID}").ok and not dbq("SELECT 1 FROM git_tags WHERE conn_id=?", (BBID,)), "removed with its tags")
leak = [x for x in SEEN if GLTOK in x or GLOAUTH in x or BBTOK in x or BBBASIC in x]
check(not leak, f"no provider token in any answer ({len(leak)})")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
