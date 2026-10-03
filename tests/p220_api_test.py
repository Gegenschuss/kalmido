#!/usr/bin/env python3
"""2.2.0 API tests.
 - #271 Git integration against a fake GitHub (Enterprise layout) and a fake Gitea / Forgejo (fake_git.py inside the test
   container; no real GitHub call): connecting (project lists only, owner / list admins only, never an agent; owner/name,
   addresses, the repository is read at once: not found / wrong token refused, duplicates, at most 5), tokens write-only
   and sealed (never in any answer, not plain in the database, sent only as Authorization to the fake), the SSRF guard
   (an internal address that no admin allowed is refused), the poller (ETag / If-None-Match, matching by #id in titles /
   bodies / commit messages and by branch names, only tasks of the connected list, CI from combined status + check runs),
   keywords (fixes / closes / erledigt in a merged pull request or a default-branch commit complete once; nothing from
   before the connection; undo), rate limits (pause until the reset) and back-off on errors, the optional inbound webhook
   (signature, no login, no CSRF header), requests never wait on the poller, removing a repository, the REST API
   (GET /lists/{id}/repos, get_task code + repo), without KALMIDO_SECRET_KEY
 - #339 merge requests: an agent's comment with suggestion {kind: merge_request, pr_url} (only agents, only pull requests of a
   connected repository, the pull request is linked at once), 👍 / 👎 only by approvers (owner, list admin, assignee, admin),
   the reaction event with approval + merge_request, "Apply" refused; the assigned event and get_task carry the repository
   with a suggested branch name
usage: p220_api_test.py <datadir>"""
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
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
GH = "http://127.0.0.1:8090"      # fake GitHub Enterprise (API under /api/v3)
GT = "http://127.0.0.1:8091"      # fake Gitea (API under /api/v1)
TOKEN = "ghp_fake_read_only_token_7f3a9c"
GTOKEN = "gitea-fake-token-51b2"
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

    def _r(self, m, p, **k):
        r = requests.request(m, V + p, headers=self.h, timeout=60, **k)
        SEEN.append(r.text)
        return r

    def get(self, p, **k):
        return self._r("GET", p, **k)

    def post(self, p, **k):
        return self._r("POST", p, **k)


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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"))
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def start(with_key=True):
    extra = ["-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1", "-e KALMIDO_GIT_POLL=2", "-e KALMIDO_GIT_TICK=1"] + \
        (["-e KALMIDO_SECRET_KEY=" + KEY] if with_key else [])
    env = dict(os.environ, EXTRA=" ".join(extra))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    put_state()
    subprocess.run(["cp", os.path.join(N, "fake_git.py"), DATA])
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_git.py"])
    time.sleep(0.8)


def pr(n, title, state="open", body="", ref="feature-x", sha=None, merged_at=None, user="dev"):
    return {"number": n, "title": title, "body": body, "state": "closed" if state in ("merged", "closed") else "open",
            "merged_at": merged_at if state == "merged" else None, "html_url": f"{GH}/acme/app/pull/{n}",
            "user": {"login": user}, "head": {"ref": ref, "sha": sha or f"sha{n:04d}"}, "updated_at": iso(datetime.now(timezone.utc))}


def cm(sha, msg, at=None, web=GH, repo="acme/app"):
    at = at or iso(datetime.now(timezone.utc))
    return {"sha": sha, "html_url": f"{web}/{repo}/commit/{sha}", "author": {"login": "dev"},
            "commit": {"message": msg, "author": {"name": "Dev", "date": at}, "committer": {"date": at}}}


def until(fn, t=15.0):
    t0 = time.time()
    while time.time() - t0 < t:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def task_of(s, tid):
    return next((x for x in s.get(B + "/api/state").json()["tasks"] if x["id"] == tid), None)


STATE.update({"8090": {"acme/app": {"token": TOKEN, "default_branch": "main", "pulls": [], "commits": {"main": []}}},
              "8091": {"team/tool": {"token": GTOKEN, "default_branch": "develop", "pulls": [], "commits": {"develop": []}}}})
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
PLAIN = A.post(B + "/api/lists", json={"name": "Groceries"}).json()["id"]
OTHER = A.post(B + "/api/lists", json={"name": "Other", "kind": "project"}).json()["id"]
for u, role in (("bob", "edit"), ("carol", "view"), ("dave", "admin")):
    assert A.put(B + f"/api/lists/{P}/members", json={"user_id": ids[u], "role": role}).ok
assert A.put(B + f"/api/lists/{P}/members", json={"user_id": AG, "role": "edit"}).ok
assert A.put(B + f"/api/lists/{OTHER}/members", json={"user_id": ids["bob"], "role": "edit"}).ok

# ================================================================== connecting
body = {"provider": "github", "base_url": GH, "repo": "acme/app", "token": TOKEN}
check(A.post(B + f"/api/lists/{PLAIN}/repos", json=body).status_code == 409, "a plain list cannot connect (project lists only)")
check(Bo.post(B + f"/api/lists/{P}/repos", json=body).status_code == 403, "a member (edit) cannot connect")
check(Ca.post(B + f"/api/lists/{P}/repos", json=body).status_code == 403, "a viewer cannot connect")
check(ag.post(f"/lists/{P}/repos", json=body).status_code in (404, 405), "no API route to connect (agents never connect)")
check(requests.post(B + f"/api/lists/{P}/repos", json=body, headers={"Authorization": "Bearer " + AGTOK, **H}).status_code in (401, 403),
      "an agent token cannot reach the web endpoint")
for bad in ({**body, "repo": "no-slash"}, {**body, "repo": "a/b c"}, {**body, "provider": "gitlab"}, {**body, "token": "has space"},
            {"provider": "gitea", "repo": "team/tool"}):
    r = A.post(B + f"/api/lists/{P}/repos", json=bad)
    check(r.status_code == 400, f"invalid input refused: {bad.get('repo')} {bad.get('provider')} -> {r.status_code}")
r = A.post(B + f"/api/lists/{P}/repos", json={**body, "repo": "acme/nope"})
check(r.status_code == 409 and "not found" in r.json().get("error", "").lower(), f"unknown repository: {r.status_code} {r.text[:120]}")
r = A.post(B + f"/api/lists/{P}/repos", json={**body, "token": "wrong-token"})
check(r.status_code == 409 and "token" in r.json().get("error", "").lower(), f"wrong token: {r.status_code} {r.text[:120]}")
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "gitea", "base_url": "http://10.255.1.2:3000", "repo": "x/y"})
check(r.status_code == 502 and "private network" in r.json().get("error", ""), f"SSRF guard: internal host not allowed: {r.status_code} {r.text[:120]}")
t_conn0 = datetime.now(timezone.utc)
r = Da.post(B + f"/api/lists/{P}/repos", json={**body, "repo": f"{GH}/acme/app.git"})  # a list admin, the whole address
check(r.status_code == 201, f"list admin connects via the address: {r.status_code} {r.text[:200]}")
RID = r.json().get("id")
check(r.json().get("full_name") == "acme/app" and r.json().get("token") is True and r.json().get("default_branch") == "main"
      and r.json().get("web_url") == f"{GH}/acme/app" and r.json().get("base_url") == GH, f"answer: {r.json()}")
check(A.post(B + f"/api/lists/{P}/repos", json=body).status_code == 409, "the same repository twice: 409")
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "gitea", "base_url": GT, "repo": "team/tool", "token": GTOKEN})
check(r.status_code == 201 and r.json().get("default_branch") == "develop", f"Gitea connected: {r.status_code} {r.text[:200]}")
RID2 = r.json().get("id")
row = dbq("SELECT token FROM git_conns WHERE id=?", (RID,))[0][0]
check(row.startswith("v1.") and TOKEN not in row, "token sealed in the database")
lst = next(x for x in Bo.get(B + "/api/state").json()["lists"] if x["id"] == P)
check([x["full_name"] for x in lst.get("repos", [])] == ["acme/app", "team/tool"], f"state: the list's repos for a member: {lst.get('repos')}")
j = Ca.get(B + f"/api/lists/{P}/repos").json()
check(len(j["repos"]) == 2 and not j["may"] and "token" not in j["repos"][0] and "hook_url" not in j["repos"][0], "a viewer sees the repos, no token flags")
j = A.get(B + f"/api/lists/{P}/repos").json()
check(j["may"] and j["key"] and j["repos"][0]["token"] is True, "the owner sees token set / not set")
j = ag.get(f"/lists/{P}/repos").json()
check([x["full_name"] for x in j.get("data", [])] == ["acme/app", "team/tool"] and all("token" not in x for x in j["data"]), f"v1: repos of a list: {j}")
check(ag.get(f"/lists/{P}").json().get("repos"), "v1 list carries repos")
check(Bo.get(B + f"/api/lists/{PLAIN}/repos").status_code == 404, "a list I do not see: 404")

# ================================================================== the poller: matching, CI, keywords
T1 = A.post(B + "/api/tasks", json={"title": "Login broken", "list_id": P}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Other list task", "list_id": OTHER}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"title": "Branch task", "list_id": P}).json()["id"]
T4 = A.post(B + "/api/tasks", json={"title": "Commit closes me", "list_id": P}).json()["id"]
T5 = A.post(B + "/api/tasks", json={"title": "PR closes me", "list_id": P}).json()["id"]
T6 = A.post(B + "/api/tasks", json={"title": "Old merged PR", "list_id": P}).json()["id"]
T7 = A.post(B + "/api/tasks", json={"title": "German keyword", "list_id": P}).json()["id"]
T8 = A.post(B + "/api/tasks", json={"title": "Gitea task", "list_id": P}).json()["id"]
now = datetime.now(timezone.utc)
old = iso(now - timedelta(days=3))
g = STATE["8090"]["acme/app"]
g["pulls"] = [pr(5, f"Fix login #{T1}", body=f"see also #{T2}", ref="fix-login", sha="aaa111"),
              pr(6, "Branch work", ref=f"feature/kalmido-{T3}-branch-task", sha="bbb222"),
              pr(7, "Closes the task", state="merged", body=f"closes #{T5}", ref="x", merged_at=iso(now + timedelta(seconds=5))),
              pr(8, "Old one", state="merged", body=f"fixes #{T6}", ref="y", merged_at=old),
              pr(9, f"Unrelated #{T2}", ref="z")]
g["commits"]["main"] = [cm("c0ffee1", f"Refactor login (#{T1})"), cm("c0ffee2", f"fixes #{T4}: done", at=iso(now + timedelta(seconds=5))),
                        cm("c0ffee3", f"Erledigt #{T7}", at=iso(now + timedelta(seconds=5))), cm("c0ffee4", f"fixes #{T6} long ago", at=old)]
g["compare"] = {f"feature/kalmido-{T3}-branch-task": [cm("bra0001", "wip on the branch")]}
g["status"] = {"aaa111": {"state": "success", "total_count": 1, "statuses": [{"state": "success"}]}}
g["checks"] = {"aaa111": [{"status": "completed", "conclusion": "failure"}], "bbb222": [{"status": "in_progress", "conclusion": None}]}
STATE["8091"]["team/tool"]["pulls"] = [{"number": 3, "title": f"Gitea change #{T8}", "body": "", "state": "open", "merged": False,
                                       "html_url": f"{GT}/team/tool/pulls/3", "user": {"login": "gdev"}, "head": {"ref": "g", "sha": "ggg333"},
                                       "updated_at": iso(now)}]
STATE["8091"]["team/tool"]["commits"]["develop"] = [cm("dd00001", f"Gitea commit for #{T8}", web=GT, repo="team/tool")]
STATE["8091"]["team/tool"]["status"] = {"ggg333": {"state": "pending", "total_count": 1, "statuses": [{"state": "pending"}]}}
put_state()
time.sleep(0.2)
dbq_c = sqlite3.connect(os.path.join(DATA, "tasks.db"))
dbq_c.execute("UPDATE git_conns SET next_at=0")
dbq_c.commit()
dbq_c.close()
t1 = until(lambda: (lambda t: t if t and t.get("code", {}).get("prs") and t["code"]["prs"][0].get("ci") else None)(task_of(Bo, T1)), 25)
code = (t1 or {}).get("code") or {}
check(code.get("prs") and code["prs"][0]["n"] == 5 and code["prs"][0]["state"] == "open" and code["prs"][0]["author"] == "dev",
      f"T1: PR #5 linked via #id in the title: {code.get('prs')}")
check(code.get("prs") and code["prs"][0]["ci"] == "failure", f"CI: status success + a failed check run = failure: {code.get('prs')}")
check([m["short"] for m in code.get("commits", [])] == ["c0ffee1"], f"T1: the commit linked via (#id): {code.get('commits')}")
t2 = task_of(Bo, T2)
check(t2 and not t2.get("code"), "T2 (another list) never linked, even when mentioned")
t3 = until(lambda: (lambda t: t if t and t.get("code", {}).get("commits") and t["code"].get("prs") and t["code"]["prs"][0].get("ci") else None)(task_of(A, T3)), 15)
check(t3 and t3["code"]["prs"][0]["n"] == 6 and t3["code"]["prs"][0]["branch"].endswith(f"kalmido-{T3}-branch-task"), "T3: PR linked via the branch name")
check(t3 and [m["sha"] for m in t3["code"]["commits"]] == ["bra0001"] and t3["code"]["prs"][0]["ci"] == "pending", f"T3: branch commit + pending CI: {t3 and t3['code']}")
t4, t5, t7 = until(lambda: task_of(A, T4)), task_of(A, T5), task_of(A, T7)
check(t4 and t4["status"] == 2, "T4: 'fixes #id' in a default-branch commit completed it")
check(t5 and t5["status"] == 2, "T5: 'closes #id' in a merged PR completed it")
check(t7 and t7["status"] == 2, "T7: German 'Erledigt #id' completed it")
check(task_of(A, T6)["status"] == 0, "T6: PR merged / commit from before the connection: not completed")
t8 = until(lambda: (lambda t: t if t and t.get("code", {}).get("prs") and t["code"].get("commits") else None)(task_of(A, T8)), 15)
check(t8 and t8["code"]["prs"][0]["repo"] == "team/tool" and t8["code"]["prs"][0]["ci"] == "pending" and t8["code"]["commits"][0]["short"] == "dd00001",
      f"Gitea: PR + commit + CI: {t8 and t8.get('code')}")
tl = A.get(B + f"/api/tasks/{T4}/timeline").json()
act = [a for a in tl["activity"] if a["kind"] == "git_done"]
check(act and act[0]["data"].get("kind") == "commit" and act[0]["data"].get("ref") == "c0ffee2" and act[0]["data"].get("repo") == "acme/app"
      and act[0]["user_id"] is None, f"T4 activity names the commit: {act}")
tl = A.get(B + f"/api/tasks/{T5}/timeline").json()
check([a["data"]["ref"] for a in tl["activity"] if a["kind"] == "git_done"] == ["7"], "T5 activity names the pull request")
tl = A.get(B + f"/api/tasks/{T1}/timeline").json()
check([(a["data"]["n"], a["data"]["state"], a["user_id"]) for a in tl["activity"] if a["kind"] == "git_pr"] == [(5, "opened", None)],
      "activity: PR #5 opened after the connection")
# ETag: a later poll sends If-None-Match and gets 304
until(lambda: any(x["inm"] and x["status"] == 304 and "/pulls" in x["path"] for x in git_log()), 12)
lg = git_log()
check(any(x["inm"] and x["status"] == 304 and "/pulls" in x["path"] for x in lg), "ETag: If-None-Match -> 304")
okl = [x for x in lg if x["status"] in (200, 304)]
check(okl and all(x["auth"] in ("Bearer " + TOKEN, "token " + GTOKEN) for x in okl), "every request carries its own token only")
check(all((x["auth"] == "Bearer " + TOKEN) == (x["port"] == 8090) for x in okl), "GitHub: Bearer, Gitea: token")
check(all((x["ua"] or "").startswith("Kalmido/") for x in lg), "own User-Agent")
# a new PR later: activity "opened", merged -> "merged"
g["pulls"].insert(0, pr(10, f"Second attempt #{T1}", ref="again", sha="ccc333"))
put_state()
until(lambda: len([a for a in A.get(B + f"/api/tasks/{T1}/timeline").json()["activity"] if a["kind"] == "git_pr"]) == 2, 15)
tl = A.get(B + f"/api/tasks/{T1}/timeline").json()
check([(a["data"]["n"], a["data"]["state"]) for a in tl["activity"] if a["kind"] == "git_pr"] == [(5, "opened"), (10, "opened")], f"activity: PR opened: {tl['activity'][-3:]}")
g["pulls"][0] = pr(10, f"Second attempt #{T1}", state="merged", ref="again", sha="ccc333", merged_at=iso(datetime.now(timezone.utc)))
put_state()
until(lambda: len([a for a in A.get(B + f"/api/tasks/{T1}/timeline").json()["activity"] if a["kind"] == "git_pr"]) == 3, 15)
tl = A.get(B + f"/api/tasks/{T1}/timeline").json()
check([a["data"]["state"] for a in tl["activity"] if a["kind"] == "git_pr"] == ["opened", "opened", "merged"], "activity: PR merged")
check(task_of(A, T1)["status"] == 0, "merged without a keyword: the task stays open")

# baseline: a repository connected when its pull requests already exist: linked, but no "opened" lines
STATE["8090"]["acme/lib"] = {"token": TOKEN, "default_branch": "main", "commits": {"main": []},
                             "pulls": [{**pr(21, f"Lib work #{T2}", ref="lib"), "html_url": f"{GH}/acme/lib/pull/21"}]}
put_state()
r = Bo.post(B + f"/api/lists/{OTHER}/repos", json={"provider": "github", "base_url": GH, "repo": "acme/lib", "token": TOKEN})
check(r.status_code == 403, "bob (member of OTHER) cannot connect")
r = A.post(B + f"/api/lists/{OTHER}/repos", json={"provider": "github", "base_url": GH, "repo": "acme/lib", "token": TOKEN})
t2 = until(lambda: (lambda t: t if t.get("code") else None)(task_of(A, T2)), 12)
check(t2 and t2["code"]["prs"][0]["repo"] == "acme/lib", "T2 linked in its own list's repository")
check(not [a for a in A.get(B + f"/api/tasks/{T2}/timeline").json()["activity"] if a["kind"] == "git_pr"], "the first poll (baseline) writes no activity")

# undo + once
r = Ca.post(B + f"/api/tasks/{T4}/git-undo")
check(r.status_code in (403, 404), f"a viewer cannot undo: {r.status_code}")
r = A.post(B + f"/api/tasks/{T4}/git-undo")
check(r.ok and r.json()["status"] == 0, f"undo reopens: {r.status_code} {r.text[:100]}")
check(A.post(B + f"/api/tasks/{T4}/git-undo").status_code == 409, "undo twice: 409")
g["commits"]["main"].insert(0, cm("c0ffee5", f"really fixes #{T4}", at=iso(datetime.now(timezone.utc) + timedelta(seconds=5))))
put_state()
until(lambda: dbq("SELECT 1 FROM git_commits WHERE sha='c0ffee5'"), 12)
time.sleep(1.5)
check(task_of(A, T4)["status"] == 0, "once: another keyword after the undo does not complete it again")

# ================================================================== requests never wait on the poller; rate limit; back-off
STATE["slow"] = 3
put_state()
c = sqlite3.connect(os.path.join(DATA, "tasks.db"))
c.execute("UPDATE git_conns SET next_at=0")
c.commit()
c.close()
time.sleep(1.5)
t0 = time.time()
ok = Bo.get(B + "/api/state").ok and Bo.get(B + f"/api/tasks/{T1}/timeline").ok
check(ok and time.time() - t0 < 1.5, f"requests do not wait on a slow Git server ({time.time() - t0:.2f} s)")
STATE["slow"] = 0
STATE["remaining"] = 3
put_state()
time.sleep(4)
c = sqlite3.connect(os.path.join(DATA, "tasks.db"))
c.execute("UPDATE git_conns SET next_at=0, last_error='' WHERE id=?", (RID,))
c.commit()
c.close()
row = until(lambda: (lambda r: r if r and r[0][0] == "rate" else None)(dbq("SELECT last_error, next_at FROM git_conns WHERE id=?", (RID,))), 12)
check(row and row[0][1] > time.time() + 60, f"rate limit: paused until the reset: {row}")
j = A.get(B + f"/api/lists/{P}/repos").json()
check(j["repos"][0]["status"] == "ok", "a rate pause is not shown as an error")
STATE["remaining"] = 4999
STATE["rate_block"] = True
put_state()
c = sqlite3.connect(os.path.join(DATA, "tasks.db"))
c.execute("UPDATE git_conns SET next_at=0, last_error='' WHERE id=?", (RID,))
c.commit()
c.close()
row = until(lambda: (lambda r: r if r and r[0][0] == "rate" else None)(dbq("SELECT last_error, next_at FROM git_conns WHERE id=?", (RID,))), 12)
check(row and row[0][1] > time.time() + 60, f"403 with remaining 0: paused: {row}")
STATE["rate_block"] = False
g["token"] = "rotated-on-the-server"
put_state()
c = sqlite3.connect(os.path.join(DATA, "tasks.db"))
c.execute("UPDATE git_conns SET next_at=0, last_error='' WHERE id=?", (RID,))
c.commit()
c.close()
row = until(lambda: (lambda r: r if r and r[0][0] and r[0][0].startswith("auth") and r[0][2] >= 2 else None)(
    dbq("SELECT last_error, next_at, fails FROM git_conns WHERE id=?", (RID,))), 20)
check(row and row[0][2] >= 2, f"auth errors count up: {row}")
check(row and row[0][1] - time.time() >= 2 * 2 ** 2 - 2, f"back-off grows with the failures: {row and row[0][1] - time.time()}")
j = A.get(B + f"/api/lists/{P}/repos").json()
check(j["repos"][0]["status"] == "error" and "token" in j["repos"][0]["error"], f"the dialog shows the error: {j['repos'][0]}")
r = A.patch(B + f"/api/repos/{RID}", json={"token": "rotated-on-the-server"})
check(r.ok and r.json().get("token") is True, "a new token")
g["token"] = TOKEN
put_state()
check(Bo.patch(B + f"/api/repos/{RID}", json={"token": "x"}).status_code == 403, "a member cannot change the token")
n0 = len(git_log())
r = A.patch(B + f"/api/repos/{RID}", json={"token": TOKEN})
check(r.ok, f"the right token again ({r.status_code})")


# 2.14.0: the real cause of the old CI flake: a poll that was still running with the "rotated" token when the right one was
# saved wrote its late 401 over the reset (fixed in git_poll), and this check used to accept the reset itself as the
# recovery. Now it waits for a real poll with the new token after the save and then for a clean state.
def recovered():
    ok = any(x["port"] == 8090 and "/acme/app/" in x["path"] and x["status"] in (200, 304) and x["auth"] == "Bearer " + TOKEN
             for x in git_log()[n0:])
    return ok and tuple(dbq("SELECT fails, last_error FROM git_conns WHERE id=?", (RID,))[0]) == (0, "")


until(recovered, 30)
st_ = dbq("SELECT fails, last_error, next_at FROM git_conns WHERE id=?", (RID,))[0]
check(recovered(), f"recovers after the token is fixed (a poll with the new token went through): {st_[0]} fails, {st_[1]!r}, "
      f"next in {round(st_[2] - time.time())} s" + ("" if recovered() else f"; last requests at the fake server: {git_log()[-4:]}"))
check(Bo.post(B + f"/api/repos/{RID}/refresh").ok, "a member may ask for a check")

# ================================================================== #339 merge requests + the agent's view
T9 = A.post(B + "/api/tasks", json={"title": "Implement the export", "list_id": P}).json()["id"]
cur = ag.get("/agent").json()["cursor"]
A.patch(B + f"/api/tasks/{T9}", json={"assignee_id": AG})


def events(since, want, t=10.0):
    t0, out = time.time(), []
    while time.time() - t0 < t:
        j = ag.get("/agent/events", params={"since": since}).json()
        out = [e for e in j.get("data", []) if e["event"] in want]
        if out:
            return out, j.get("cursor", since)
        time.sleep(0.3)
    return out, since


ev, cur = events(cur, {"assigned"})
rp = ev[0]["data"].get("repo") if ev else None
check(rp and rp["full_name"] == "acme/app" and rp["default_branch"] == "main" and rp["branch"] == f"kalmido-{T9}"
      and rp["provider"] == "github" and rp["web_url"] == f"{GH}/acme/app" and rp["api_url"] == GH + "/api/v3"
      and rp["others"][0]["full_name"] == "team/tool" and "token" not in json.dumps(rp), f"assigned event: repo: {rp}")
j = ag.get(f"/tasks/{T9}").json()
check(j.get("repo", {}).get("branch") == f"kalmido-{T9}" and j.get("code") == {"prs": [], "commits": []}, f"get_task: repo + code: {j.get('repo')}")
j = ag.get(f"/tasks/{T1}").json()
check({p["n"] for p in j.get("code", {}).get("prs", [])} == {5, 10} and j["code"]["prs"][0]["n"] == 5, f"get_task code (open first): {j.get('code')}")
url = f"{GH}/acme/app/pull/11"
r = ag.post(f"/tasks/{T9}/comments", json={"body": "Ready to merge", "suggestion": {"kind": "merge_request", "pr_url": "https://github.com/evil/repo/pull/1"}})
check(r.status_code == 400 and "not in a repository" in r.text, f"a PR of another repository: {r.status_code}")
r = ag.post(f"/tasks/{T9}/comments", json={"body": "x", "suggestion": {"kind": "merge_request", "pr_url": url, "extra": 1}})
check(r.status_code == 400, "unknown field refused")
r = A.post(B + f"/api/tasks/{T9}/comments", json={"body": "me too", "suggestion": {"kind": "merge_request", "pr_url": url}})
check(r.status_code == 403, "people cannot post merge requests")
r = ag.post(f"/tasks/{T9}/comments", json={"body": f"Ready to merge: {url}", "suggestion": {"kind": "merge_request", "pr_url": url, "summary": "Adds CSV export"}})
check(r.status_code == 201 or r.ok, f"agent posts a merge request: {r.status_code} {r.text[:200]}")
CM = r.json().get("id")
sug = r.json().get("suggestion") or {}
check(sug.get("kind") == "merge_request" and sug.get("state") == "open" and sug.get("number") == 11 and sug.get("repo") == "acme/app", f"stored: {sug}")
t9 = task_of(A, T9)
check(t9.get("code", {}).get("prs") and t9["code"]["prs"][0]["n"] == 11, "the PR is linked to the task at once")
g["pulls"].insert(0, pr(11, "CSV export", body="", ref=f"kalmido-{T9}-implement-the-export", sha="eee555"))
g["status"]["eee555"] = {"state": "success", "total_count": 1, "statuses": [{"state": "success"}]}
g["checks"]["eee555"] = [{"status": "completed", "conclusion": "success"}]
put_state()
t9 = until(lambda: (lambda t: t if t["code"]["prs"][0]["title"] == "CSV export" and t["code"]["prs"][0]["ci"] else None)(task_of(A, T9)), 15)
check(t9 and t9["code"]["prs"][0]["ci"] == "success", f"the poll fills in title + CI: {t9 and t9['code']}")
tl = A.get(B + f"/api/tasks/{T9}/timeline").json()
check(tl.get("approver") is True and Bo.get(B + f"/api/tasks/{T9}/timeline").json().get("approver") is False, "timeline: approver flag")
check(A.post(B + f"/api/comments/{CM}/apply").status_code == 409, "Apply refused for a merge request")
r = Ca.post(B + f"/api/comments/{CM}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["suggestion"]["state"] == "open" and not r.json().get("approval"), "a viewer's 👍: no approval")
r = Bo.post(B + f"/api/comments/{CM}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["suggestion"]["state"] == "open", "a member's 👍 (not an approver): still open")
ev, cur = events(cur, {"reaction"})
check(ev and all(e["data"].get("approval") is None for e in ev) and ev[0]["data"].get("merge_request", {}).get("state") == "open", "reaction events without approval")
r = Da.post(B + f"/api/comments/{CM}/reactions", json={"emoji": "down"})
check(r.ok and r.json()["suggestion"]["state"] == "rejected" and r.json().get("merge") == "rejected", f"a list admin's 👎 rejects: {r.text[:200]}")
ev, cur = events(cur, {"reaction"})
d = ev[-1]["data"] if ev else {}
check(d.get("approval") == "rejected" and d.get("merge_request") == {"pr_url": url, "number": 11, "repo": "acme/app", "state": "rejected"},
      f"event: rejected with the PR: {d.get('merge_request')}")
r = ag.post(f"/tasks/{T9}/comments", json={"body": "Fixed, again", "suggestion": {"kind": "merge_request", "pr_url": url}})
CM2 = r.json().get("id")
r = A.post(B + f"/api/comments/{CM2}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["suggestion"]["state"] == "approved" and r.json()["suggestion"]["by"] == 1, "the owner's 👍 approves")
ev, cur = events(cur, {"reaction"})
d = ev[-1]["data"] if ev else {}
check(d.get("approval") == "approved" and d.get("merge_request", {}).get("pr_url") == url and d.get("comment", {}).get("suggestion", {}).get("kind") == "merge_request",
      f"event: approved: {d.get('approval')} {d.get('merge_request')}")
r = A.post(B + f"/api/comments/{CM2}/reactions", json={"emoji": "down"})
check(json.loads(dbq("SELECT suggestion FROM comments WHERE id=?", (CM2,))[0][0])["state"] == "approved", "decided once")

# ================================================================== inbound webhook
r = A.patch(B + f"/api/repos/{RID}", json={"hook": "on"})
sec = r.json().get("hook_secret")
check(r.ok and sec and len(sec) >= 24 and r.json().get("hook") is True and r.json()["hook_url"].endswith(f"/api/hooks/git/{RID}"), "webhook on: secret once")
check("hook_secret" not in A.get(B + f"/api/lists/{P}/repos").text and sec not in A.get(B + f"/api/lists/{P}/repos").text, "the secret is never shown again")
check(sec not in dbq("SELECT hook_secret FROM git_conns WHERE id=?", (RID,))[0][0], "the secret is sealed")
raw = json.dumps({"action": "opened"}).encode()
sig = "sha256=" + hmac.new(sec.encode(), raw, hashlib.sha256).hexdigest()
c = sqlite3.connect(os.path.join(DATA, "tasks.db"))
# 2.15.1: the hook ignores calls within 10 s of the last poll (debounce); an earlier step may just have polled, so age
# polled_at too, or the check below races that poll (CI flake "the hook triggers a poll")
c.execute("UPDATE git_conns SET next_at=?, polled_at=? WHERE id=?", (time.time() + 999, "2000-01-01T00:00:00+00:00", RID))
c.commit()
c.close()
r = requests.post(B + f"/api/hooks/git/{RID}", data=raw, headers={"X-Hub-Signature-256": "sha256=" + "0" * 64, "Content-Type": "application/json"})
check(r.status_code == 401, f"wrong signature: {r.status_code}")
r = requests.post(B + f"/api/hooks/git/{RID}", data=raw, headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json", "X-GitHub-Event": "pull_request"})
check(r.status_code == 202, f"valid GitHub signature, no login, no CSRF header: {r.status_code} {r.text[:100]}")
check(until(lambda: dbq("SELECT next_at FROM git_conns WHERE id=?", (RID,))[0][0] < time.time() + 900, 5), "the hook triggers a poll")
r = requests.post(B + f"/api/hooks/git/{RID2}", data=raw, headers={"X-Gitea-Signature": hmac.new(sec.encode(), raw, hashlib.sha256).hexdigest()})
check(r.status_code == 404, "a repository without webhook: 404")
r = requests.post(B + f"/api/hooks/git/{RID}", data=raw, headers={"X-Gitea-Signature": hmac.new(sec.encode(), raw, hashlib.sha256).hexdigest()})
check(r.status_code == 202, "Gitea signature header accepted")
check(A.patch(B + f"/api/repos/{RID}", json={"hook": "off"}).ok and requests.post(B + f"/api/hooks/git/{RID}", data=raw, headers={"X-Hub-Signature-256": sig}).status_code == 404,
      "webhook off: 404")

# ================================================================== OpenAPI, removal, no token anywhere
spec = requests.get(V + "/openapi.json").json()
check("/lists/{id}/repos" in spec.get("paths", {}) and "Repo" in spec.get("components", {}).get("schemas", {}), "OpenAPI: repos documented")
check(Bo.delete(B + f"/api/repos/{RID2}").status_code == 403, "a member cannot remove")
check(A.delete(B + f"/api/repos/{RID2}").ok and not dbq("SELECT 1 FROM git_links WHERE conn_id=?", (RID2,)), "removed with its links")
t8 = task_of(A, T8)
check(not t8.get("code"), "the Gitea links are gone from the task")
check(task_of(A, T5)["status"] == 2, "completed tasks stay completed")
leak = [t for t in SEEN if TOKEN in t or GTOKEN in t or (sec and sec in t and "hook_secret" not in t)]
check(not leak, f"no token in any answer ({len(leak)})")
check(TOKEN not in "".join(open(os.path.join(DATA, f), errors="ignore").read() for f in os.listdir(DATA) if f.startswith("tasks.db")),
      "no token in the database files")

# ================================================================== without KALMIDO_SECRET_KEY
start(with_key=False)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
P = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
r = A.post(B + f"/api/lists/{P}/repos", json=body)
check(r.status_code == 409 and "KALMIDO_SECRET_KEY" in r.json().get("error", ""), f"no key: a token cannot be stored: {r.text[:120]}")
STATE["8090"]["acme/pub"] = {"default_branch": "main", "pulls": [], "commits": {"main": []}}
put_state()
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "github", "base_url": GH, "repo": "acme/pub"})
check(r.status_code == 201 and r.json().get("token") is False, "no key: a public repository without a token works")
check(A.get(B + f"/api/lists/{P}/repos").json()["key"] is False, "the dialog learns the key is missing")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
