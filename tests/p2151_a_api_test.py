#!/usr/bin/env python3
"""2.151.0 API tests, part A (#2558): a task knows its build state. Own container with the fake Git servers of fake_git.py
inside (GitHub :8090, Gitea :8091, GitLab :8092, Bitbucket Cloud :8093; no real provider is ever called).
freelancer-matrix: lists
 - the first version tag of a commit: the baseline tags of a new connection are compared once pairwise (numeric order:
   v2.9.3 < v2.10.0, "nightly" ignored), a new tag once against the version before it; the first tag wins; a squash-merged
   pull request gets the tag of its merge commit (merge_commit_sha)
 - task branches: kalmido-<id> / kalmido-<id>-slug from the branch list (not a branch of an unknown task, not others), ahead
   of the default branch (compare), ahead 0 = merged, a deleted branch disappears, a compare only when a head moved
 - code.build: released (version = the highest tag) / main / branch / none, branches, package (the field "Paket" found by
   its name, 2.11 = 2.11.0 released, "2.46c" and a renumbered 2.10.5 never), stale only for open tasks
 - the version field: automatic / off / a picked field (list owner / admins; a member, an agent: 403; invalid: 400)
 - GET /api/lists/{id}/build-status and /api/v1/lists/{id}/build-status (stale + branch-only tasks), agents: repo.build
   and the branches marked untrusted; a stranger (person or agent) 404
 - GitLab and Bitbucket: tag compare + branch list in their shapes; a person without an organisation (Gitea) the same
 - the rate: per poll at most the usual requests + the branch list; no tag compare twice
 - 2.151.0 A2 (review): released without a known tag = exact (one compare newest tag...main per head, only a complete answer
   marks; old commit dates merged today stay "main"), a failing tag compare gives up after 3 tries (404 at once), a branch
   that is gone before it was measured merged: compare default...head, merged -> its commits in main, else no open branch,
   build-status leaves out a participant's context tasks, code.build branches marked untrusted in v1
usage: p2151_a_api_test.py <datadir>   (P2151A_NOSTART=1 / KMT_NOSTART=1: the container runs already, with
KALMIDO_GIT_POLL=2, KALMIDO_GIT_TICK=1, KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1 and fake_git.py started)"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, login  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
GH, GT, GL, BB = "http://127.0.0.1:8090", "http://127.0.0.1:8091", "http://127.0.0.1:8092", "http://127.0.0.1:8093"
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def get(self, p, **k):
        return requests.get(V + p, headers=self.h, timeout=60, **k)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


STATE = {"8090": {}, "8091": {}, "8092": {}, "8093": {}}


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
    c = dbx.connect(os.path.join(DATA, "tasks.db"))
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def until(fn, t=30.0):
    t0 = time.time()
    while time.time() - t0 < t:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def polls(cid, n=2):
    """Waits until connection cid was polled n more times."""
    def at():
        r = dbq("SELECT polled_at FROM git_conns WHERE id=?", (cid,))
        return r[0][0] if r else None
    for _ in range(n):
        a = at()
        until(lambda: at() != a, 20)


def task_of(s, tid):
    return next((x for x in s.get(B + "/api/state").json()["tasks"] if x["id"] == tid), None)


def build(s, tid):
    t = task_of(s, tid) or {}
    return (t.get("code") or {}).get("build")


NOW = datetime.now(timezone.utc)


def gh_cm(sha, msg, at=None, repo="acme/app", base=GH):
    at = at or iso(datetime.now(timezone.utc) + timedelta(seconds=5))
    return {"sha": sha, "html_url": f"{base}/{repo}/commit/{sha}", "author": {"login": "dev"},
            "commit": {"message": msg, "author": {"name": "Dev", "date": at}, "committer": {"date": at}}}


def gl_cm(sha, msg, repo="grp/app"):
    at = iso(datetime.now(timezone.utc))
    return {"id": sha, "short_id": sha[:8], "message": msg, "author_name": "G Dev", "authored_date": at, "committed_date": at,
            "web_url": f"{GL}/{repo}/-/commit/{sha}"}


def bb_cm(sha, msg, repo="ws/web"):
    return {"hash": sha, "message": msg, "date": iso(datetime.now(timezone.utc)), "author": {"raw": "B Dev <b@example.com>"},
            "links": {"html": {"href": f"{BB}/{repo}/commits/{sha}"}}}


if not (os.environ.get("P2151A_NOSTART") or os.environ.get("KMT_NOSTART")):
    extra = ["-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1", "-e KALMIDO_GIT_POLL=2", "-e KALMIDO_GIT_TICK=1"]
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, EXTRA=" ".join(extra)), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    put_state()
    subprocess.run(["cp", os.path.join(N, "fake_git.py"), DATA])
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_git.py"])
    time.sleep(0.8)
put_state()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = login(B, "bob"), login(B, "carol")
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
assert r.status_code == 201, r.text
AG, ag = r.json()["id"], Api(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "stranger", "display_name": "Stranger"})
assert r.status_code == 201, r.text
other = Api(r.json()["token"])
P = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
for uid, role in ((ids["bob"], "edit"), (AG, "edit")):
    assert A.put(B + f"/api/lists/{P}/members", json={"user_id": uid, "role": role}).ok
T = {k: A.post(B + "/api/tasks", json={"title": f"Task {k}", "list_id": P}).json()["id"] for k in range(1, 12)}
D = {k: iso(NOW - timedelta(days=k)) for k in range(1, 11)}
r = A.post(B + f"/api/lists/{P}/fields", json={"name": " Paket ", "type": "text"})
check(r.ok, f"field Paket {r.status_code} {r.text[:100]}")
FPAK = r.json().get("id")
FZIEL = A.post(B + f"/api/lists/{P}/fields", json={"name": "Ziel", "type": "text"}).json().get("id")
for k, v in ((7, "2.11"), (8, "2.46c"), (9, "2.10.5"), (10, "v2.11.0")):
    check(A.patch(B + f"/api/tasks/{T[k]}", json={"fields": {str(FPAK): v}}).ok, f"package value {v}")
A.patch(B + f"/api/tasks/{T[9]}", json={"fields": {str(FZIEL): "2.10.0"}})

# ================================================================== GitHub: baseline tags + their first fill
g = STATE["8090"]["acme/app"] = {
    "default_branch": "main", "pulls": [],
    "commits": {"main": [gh_cm("a3", f"Polish #{T[3]}", D[1]), gh_cm("a2", f"Later work #{T[2]}", D[2]), gh_cm("a1", f"Feature #{T[1]}", D[3]),
                         gh_cm("a0", f"Ancient #{T[11]}", D[9])]},
    "tags": [{"name": "nightly"}, {"name": "v2.10.0"}, {"name": "v2.9.3"}],
    "compare": {"v2.9.3...v2.10.0": [gh_cm("a1", f"Feature #{T[1]}", D[3])],
                # 2.151.0 A2 (#2558 review): newest tag...main = in main, not released (a0 is not: an earlier version)
                "v2.10.0...main": [gh_cm("a2", f"Later work #{T[2]}", D[2]), gh_cm("a3", f"Polish #{T[3]}", D[1])]},
    "branches": [{"name": "main", "commit": {"sha": "a3"}}, {"name": f"kalmido-{T[4]}", "commit": {"sha": "b4"}},
                 {"name": f"kalmido-{T[6]}-done", "commit": {"sha": "b6"}}, {"name": "kalmido-99999999", "commit": {"sha": "b9"}},
                 {"name": "random-work", "commit": {"sha": "b0"}}]}
g["compare"].update({f"kalmido-{T[4]}": [gh_cm("b41", "wip on the branch")], f"kalmido-{T[6]}-done": []})
put_state()
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "github", "base_url": GH, "repo": "acme/app"})
check(r.status_code == 201, f"GitHub connected {r.status_code} {r.text[:150]}")
CID = r.json().get("id")
check(until(lambda: dbq("SELECT tag FROM git_commits WHERE conn_id=? AND sha='a1'", (CID,)) == [("v2.10.0",)]),
      f"fill: the commit of v2.10.0 got its tag {dbq('SELECT sha, tag FROM git_commits WHERE conn_id=?', (CID,))}")
# 2.151.0 A2 (#2558 review): not the compare newest tag...main
cmps = [x["path"] for x in git_log() if x["port"] == 8090 and "/compare/v" in x["path"] and not x["path"].endswith("...main")]
check(cmps == ["/api/v3/repos/acme/app/compare/v2.9.3...v2.10.0"], f"fill: numeric order, nightly ignored, one compare: {cmps}")
check(dbq("SELECT tag FROM git_commits WHERE conn_id=? AND sha IN ('a2','a3')", (CID,)) == [("",), ("",)], "commits after the tag: no tag")
b = build(A, T[1])
check(b and b["state"] == "released" and b["version"] == "2.10.0" and b["stale"] is True,
      f"task 1 (open, in 2.10.0): released, stale {b}")
b = build(A, T[3])
check(b and b["state"] == "main" and b["version"] is None and not b["stale"], f"task 3: in main, not released {b}")
t3 = task_of(A, T[3])
b = build(A, T[11])
# 2.151.0 A2 (#2558 review): in main but not in v2.10.0...main (was: older than the oldest compared commit)
check(b and b["state"] == "released" and b["version"] is None and b["stale"], f"task 11: not in newest tag...main = an earlier version {b}")
check(t3["code"]["commits"][0]["tag"] is None and task_of(A, T[1])["code"]["commits"][0]["tag"] == "v2.10.0", "commits carry tag")
check(task_of(A, T[11])["code"]["commits"][0]["tag"] is None and dbq("SELECT tag FROM git_commits WHERE conn_id=? AND sha='a0'", (CID,)) == [("~",)],
      "an earlier version: stored ~, tag null in the API")

# branches
check(until(lambda: dbq("SELECT ahead FROM git_branches WHERE conn_id=? AND name=?", (CID, f"kalmido-{T[4]}")) == [(1,)]),
      f"branch kalmido-{T[4]}: one commit ahead {dbq('SELECT name, task_id, ahead FROM git_branches WHERE conn_id=?', (CID,))}")
names = {x[0] for x in dbq("SELECT name FROM git_branches WHERE conn_id=?", (CID,))}
check(names == {f"kalmido-{T[4]}", f"kalmido-{T[6]}-done"}, f"only task branches of known tasks: {names}")
check(until(lambda: dbq("SELECT ahead FROM git_branches WHERE conn_id=? AND name=?", (CID, f"kalmido-{T[6]}-done")) == [(0,)]),
      "kalmido-<id>-slug compared: ahead 0 (merged)")
b = build(A, T[4])
check(b and b["state"] == "branch" and [x["name"] for x in b["branches"]] == [f"kalmido-{T[4]}"] and b["branches"][0]["ahead"] == 1
      and b["branches"][0]["url"] == f"{GH}/acme/app/tree/kalmido-{T[4]}" and b["branches"][0]["repo"] == "acme/app" and not b["stale"],
      f"task 4: built, not in main {b}")
b = build(A, T[6])
check(b is None or (b["state"] == "none" and not b["branches"]), f"task 6: merged branch, nothing ahead {b}")

# no compare again while nothing moved
n0 = len(git_log())
polls(CID, 3)
lg = git_log()[n0:]
pc = sum(1 for x in lg if x["port"] == 8090 and x["path"].startswith("/api/v3/repos/acme/app/pulls"))
check(pc >= 2 and not [x for x in lg if "/compare/" in x["path"]], f"steady: no compare ({[x['path'] for x in lg if '/compare/' in x['path']]})")
check(len([x for x in lg if x["port"] == 8090]) <= 4 * (pc + 1), f"steady: at most 4 requests per poll ({len(lg)} for {pc} polls)")
check(any(x["path"].startswith("/api/v3/repos/acme/app/branches") and x["status"] == 304 for x in lg), "the branch list with ETag (304)")

# ================================================================== a new tag, a squash-merged pull request, first tag wins
g["pulls"] = [{"number": 5, "title": f"Feature #{T[5]}", "body": "", "state": "closed", "merged_at": iso(NOW), "merge_commit_sha": "m5",
               "html_url": f"{GH}/acme/app/pull/5", "user": {"login": "dev"}, "head": {"ref": "feature-x", "sha": "h5"},
               "updated_at": iso(NOW)},
              {"number": 6, "title": f"Open one #{T[6]}", "body": "", "state": "open", "merged_at": None, "merge_commit_sha": "test6",
               "html_url": f"{GH}/acme/app/pull/6", "user": {"login": "dev"}, "head": {"ref": "open-6", "sha": "h6"},
               "updated_at": iso(NOW)}]
g["tags"].insert(0, {"name": "v2.11.0"})
g["compare"]["v2.10.0...v2.11.0"] = [gh_cm("a1", f"Feature #{T[1]}", D[3]), gh_cm("a2", f"Later work #{T[2]}", D[2]),
                                     gh_cm("m5", "Squashed feature", D[2]), gh_cm("a9", f"Old fix #{T[10]}", D[2])]
g["compare"]["main...open-6"] = []
g["compare"]["v2.11.0...main"] = [gh_cm("a3", f"Polish #{T[3]}", D[1])]
put_state()
check(until(lambda: dbq("SELECT tag FROM git_commits WHERE conn_id=? AND sha='a2'", (CID,)) == [("v2.11.0",)]), "a new tag: its commits")
check(dbq("SELECT tag FROM git_commits WHERE conn_id=? AND sha='a1'", (CID,)) == [("v2.10.0",)], "the first tag wins (a1 stays v2.10.0)")
check(dbq("SELECT merge_sha, tag FROM git_prs WHERE conn_id=? AND number=5", (CID,)) == [("m5", "v2.11.0")], "squash merge: the pull request's tag")
check(dbq("SELECT merge_sha FROM git_prs WHERE conn_id=? AND number=6", (CID,)) == [("",)], "an open pull request keeps no merge commit")
check(dbq("SELECT tag FROM git_commits WHERE conn_id=? AND sha='a9'", (CID,)) == [("v2.11.0",)], "a commit only in the tag compare is linked + tagged")
cmps = [x["path"] for x in git_log() if x["port"] == 8090 and "/compare/v" in x["path"] and not x["path"].endswith("...main")]
check(sorted(cmps) == ["/api/v3/repos/acme/app/compare/v2.10.0...v2.11.0", "/api/v3/repos/acme/app/compare/v2.9.3...v2.10.0"],
      f"each tag compared once: {cmps}")
b = build(A, T[5])
check(b and b["state"] == "released" and b["version"] == "2.11.0" and b["stale"], f"task 5 (squash PR): released 2.11.0, stale {b}")
b = build(A, T[2])
check(b and b["version"] == "2.11.0", f"task 2: version 2.11.0 {b}")
b = build(A, T[6])
check(b and b["state"] == "branch", f"task 6: open pull request -> branch {b}")

# package field
b = build(A, T[7])
check(b and b["package"] == {"field": "Paket", "value": "2.11", "released": True, "latest": "2.11.0"} and b["stale"] and b["state"] == "none",
      f"task 7: Paket 2.11 = 2.11.0 released, stale {b}")
b = build(A, T[8])
check(b and b["package"]["released"] is False and not b["stale"], f"task 8: 2.46c never released {b}")
b = build(A, T[9])
check(b and b["package"]["value"] == "2.10.5" and b["package"]["released"] is False and not b["stale"], f"task 9: renumbered 2.10.5 no alarm {b}")
b = build(A, T[10])
check(b and b["state"] == "released" and b["package"]["released"] and b["stale"], f"task 10 (open): stale {b}")
r = A.post(B + f"/api/tasks/{T[10]}/complete")
check(r.ok, f"complete task 10 {r.status_code} {r.text[:100]}")
b = (ag.get(f"/tasks/{T[10]}").json().get("code") or {}).get("build")
check(b and b["state"] == "released" and not b["stale"], f"task 10 (completed): released, not stale {b}")

# the version field
r = A.get(B + f"/api/lists/{P}/repos").json()
check(r.get("version_field", {}).get("setting") == "auto" and r["version_field"]["field"] == {"id": FPAK, "name": "Paket"}
      and {f["id"] for f in r["version_field"]["fields"]} == {FPAK, FZIEL}, f"repos: version field automatic = Paket {r.get('version_field')}")
check(Bo.put(B + f"/api/lists/{P}/repos/version-field", json={"field": "off"}).status_code == 403, "a member cannot pick the version field")
check(Ca.put(B + f"/api/lists/{P}/repos/version-field", json={"field": "off"}).status_code == 404, "a stranger: 404")
for bad in ("nope", 999999, True, None):
    check(A.put(B + f"/api/lists/{P}/repos/version-field", json={"field": bad}).status_code == 400, f"invalid field {bad!r}: 400")
r = A.put(B + f"/api/lists/{P}/repos/version-field", json={"field": FZIEL})
check(r.ok and r.json()["setting"] == FZIEL and r.json()["field"]["name"] == "Ziel", f"pick Ziel {r.text[:200]}")
b = build(A, T[9])
check(b and b["package"]["field"] == "Ziel" and b["package"]["value"] == "2.10.0" and b["package"]["released"] and b["stale"],
      f"task 9 by Ziel: 2.10.0 released {b}")
b = build(A, T[7])
check(b is None or b["package"] is None, f"task 7: no Ziel value, no package {b}")
check(A.put(B + f"/api/lists/{P}/repos/version-field", json={"field": "off"}).json()["setting"] == "off", "off")
b = build(A, T[7])
check(b is None or (b["package"] is None and not b["stale"]), f"off: no package {b}")
check(A.put(B + f"/api/lists/{P}/repos/version-field", json={"field": "auto"}).json()["field"]["id"] == FPAK, "automatic again")

# build-status (web, v1), agents, the boundary
r = A.get(B + f"/api/lists/{P}/build-status")
j = r.json()
got = {x["id"] for x in j.get("data", [])}
want = {T[1], T[2], T[4], T[5], T[6], T[7], T[11]}
check(r.ok and got == want and j["latest"] == "2.11.0" and j["repos"] == 1,
      f"build-status: stale + branch-only tasks {sorted(got)} vs {sorted(want)} {j.get('latest')}")
r = ag.get(f"/lists/{P}/build-status")
j = r.json()
x4 = next((x for x in j.get("data", []) if x["id"] == T[4]), None)
check(r.ok and x4 and x4["build"]["branches"][0].get("untrusted") is True and x4["build"]["branches"][0].get("origin") == "git",
      f"v1 build-status: branch names untrusted {r.status_code} {x4}")
check(other.get(f"/lists/{P}/build-status").status_code == 404, "a stranger agent: 404")
check(Ca.get(B + f"/api/lists/{P}/build-status").status_code == 404, "a stranger person: 404")
check(ag.get(f"/lists/{P}/build-status?x=1").status_code == 400, "unknown parameter: 400")
r = ag.get(f"/tasks/{T[4]}")
j = r.json()
check(r.ok and j["code"]["build"]["state"] == "branch" and j["repo"]["build"]["branches"][0]["untrusted"] is True
      and j["code"]["build"]["branches"][0]["untrusted"] is True and j["code"]["build"]["branches"][0]["origin"] == "git",
      f"v1 get_task: code.build + repo.build {r.status_code} {str(j.get('code'))[:200]}")
spec = requests.get(V + "/openapi.json").json()
check("/lists/{id}/build-status" in spec.get("paths", {}) and "build" in spec["components"]["schemas"]["Code"]["properties"], "OpenAPI")

# branches: deleted, the default branch moves, merged
n0 = len(git_log())
g["branches"] = [x for x in g["branches"] if not x["name"].startswith(f"kalmido-{T[6]}")]
g["commits"]["main"].insert(0, gh_cm("a4", "Unrelated"))
g["compare"]["v2.11.0...main"] = [gh_cm("a3", f"Polish #{T[3]}", D[1]), gh_cm("a4", "Unrelated")]
put_state()
check(until(lambda: not dbq("SELECT 1 FROM git_branches WHERE conn_id=? AND name=?", (CID, f"kalmido-{T[6]}-done"))), "a deleted branch disappears")
until(lambda: [x for x in git_log()[n0:] if x["path"].endswith(f"compare/main...kalmido-{T[4]}")])
polls(CID, 2)
cm4 = [x for x in git_log()[n0:] if x["path"].endswith(f"compare/main...kalmido-{T[4]}")]
check(len(cm4) == 1, f"the default branch moved: the branch compared once again ({len(cm4)})")
g["branches"] = [x if x["name"] != f"kalmido-{T[4]}" else {"name": x["name"], "commit": {"sha": "b4x"}} for x in g["branches"]]
g["compare"][f"kalmido-{T[4]}"] = []
put_state()
check(until(lambda: dbq("SELECT ahead FROM git_branches WHERE conn_id=? AND name=?", (CID, f"kalmido-{T[4]}")) == [(0,)]), "merged: ahead 0")
b = build(A, T[4])
check(b and b["state"] == "main" and not b["branches"], f"task 4 after the merge: in main {b}")

# ================================================================== 2.151.0 A2 (#2558 review)
T.update({k: A.post(B + "/api/tasks", json={"title": f"Task {k}", "list_id": P}).json()["id"] for k in range(12, 17)})


def rel_n():
    return len([x for x in git_log() if x["path"].endswith("/compare/v2.11.0...main")])


def rel_check():
    return (dbq("SELECT rel_check FROM git_conns WHERE id=?", (CID,)) or [("",)])[0][0]


# 1. merged today, its commits nine days old: in main, not released. A cut-off compare (ahead_by > its list) marks nothing
n_rel = rel_n()
c12, c13 = gh_cm("c12", f"Old work #{T[12]}", D[9]), gh_cm("c13", f"Repair #{T[13]}", D[8])
g["commits"]["main"][:0] = [gh_cm("mg12", "Merge pull request 12"), c12, c13]
g["compare"]["v2.11.0...main"] = {"commits": [gh_cm("a3", f"Polish #{T[3]}", D[1]), gh_cm("a4", "Unrelated"), c12], "ahead_by": 300}
put_state()
check(until(lambda: rel_check() == "v2.11.0 mg12 x"), f"a cut-off compare: done for this head without marks ({rel_check()!r})")
for k in (12, 13):
    b = build(A, T[k])
    check(b and b["state"] == "main" and b["version"] is None and not b["stale"], f"task {k}: cut-off answer -> stays main {b}")
polls(CID, 2)
check(rel_n() == n_rel + 1, f"a cut-off answer is not asked again for the same head ({rel_n() - n_rel})")
# 2. complete: c13 is not in v2.11.0...main (its tag compare was cut off) -> an earlier version; c12 (old date) stays main
g["commits"]["main"].insert(0, gh_cm("c14", "Docs"))
g["compare"]["v2.11.0...main"] = [gh_cm("a3", f"Polish #{T[3]}", D[1]), gh_cm("a4", "Unrelated"), c12, gh_cm("mg12", "Merge pull request 12"), gh_cm("c14", "Docs")]
put_state()
check(until(lambda: (build(A, T[13]) or {}).get("state") == "released"), f"task 13: not in newest tag...main -> released {build(A, T[13])}")
b = build(A, T[13])
check(b["version"] is None and b["stale"], f"task 13: an earlier version, stale {b}")
b = build(A, T[12])
check(b and b["state"] == "main" and not b["stale"], f"task 12: merged today with old commit dates -> main, no alarm {b}")
check(rel_check() == "v2.11.0 c14 ok" and rel_n() == n_rel + 2, f"one compare per head ({rel_check()!r}, {rel_n() - n_rel})")
j = A.get(B + f"/api/lists/{P}/build-status").json()
check(T[13] in {x["id"] for x in j["data"]} and T[12] not in {x["id"] for x in j["data"]}, "build-status: 13 stale, 12 not")
# 3. a new tag: the commits get it, the compare newest tag...main follows the tag
g["tags"].insert(0, {"name": "v2.12.0"})
g["compare"]["v2.11.0...v2.12.0"] = [c12, gh_cm("mg12", "Merge pull request 12"), gh_cm("c14", "Docs")]
g["compare"]["v2.12.0...main"] = []
put_state()
check(until(lambda: (build(A, T[12]) or {}).get("version") == "2.12.0"), f"task 12: released 2.12.0 {build(A, T[12])}")
check(until(lambda: rel_check() == "v2.12.0 c14 ok"), f"the newest tag moved: compared again ({rel_check()!r})")
check(dbq("SELECT tag FROM git_commits WHERE conn_id=? AND sha='c13'", (CID,)) == [("~",)], "c13 keeps: an earlier version")

# 4. a tag compare that fails: 500 is tried in 3 polls, 404 (tag gone) given up at once
g["tags"][:0] = [{"name": "v2.14.0"}, {"name": "v2.13.0"}]
g["compare"]["v2.12.0...v2.13.0"] = {"status": 500}
g["compare"]["v2.13.0...v2.14.0"] = {"status": 404}
g["compare"]["v2.14.0...main"] = []
put_state()


def tcmp(name):
    return (dbq("SELECT cmp FROM git_tags WHERE conn_id=? AND name=?", (CID, name)) or [(None,)])[0][0]


def tries(path):
    return len([x for x in git_log() if x["path"].endswith(path)])


check(until(lambda: tcmp("v2.14.0") == 2), f"404: given up at once ({tcmp('v2.14.0')})")
check(until(lambda: tcmp("v2.13.0") == 2), f"500: given up after its tries ({tcmp('v2.13.0')})")
polls(CID, 2)
check(tries("/compare/v2.13.0...v2.14.0") == 1 and tries("/compare/v2.12.0...v2.13.0") == 3,
      f"tries: 404 once, 500 three times ({tries('/compare/v2.13.0...v2.14.0')}, {tries('/compare/v2.12.0...v2.13.0')})")

# 5. branches that are gone before they were measured merged: compare main...<last head>
g["branches"] += [{"name": f"kalmido-{T[15]}", "commit": {"sha": "h15b"}}, {"name": f"kalmido-{T[16]}", "commit": {"sha": "h16"}}]
g["compare"][f"kalmido-{T[15]}"] = [gh_cm("h15a", "step one"), gh_cm("h15b", "step two")]
g["compare"][f"kalmido-{T[16]}"] = [gh_cm("h16", "a try")]
put_state()
check(until(lambda: dbq("SELECT name, ahead FROM git_branches WHERE conn_id=? AND name IN (?,?) ORDER BY name",
                        (CID, f"kalmido-{T[15]}", f"kalmido-{T[16]}")) == [(f"kalmido-{T[15]}", 2), (f"kalmido-{T[16]}", 1)]),
      "two task branches ahead")
g["branches"] = [x for x in g["branches"] if x["name"] not in (f"kalmido-{T[15]}", f"kalmido-{T[16]}")]
g["compare"]["main...h15b"] = []
g["compare"]["main...h16"] = [gh_cm("h16", "a try")]
put_state()
check(until(lambda: not dbq("SELECT 1 FROM git_branches WHERE conn_id=? AND name IN (?,?)", (CID, f"kalmido-{T[15]}", f"kalmido-{T[16]}"))),
      "the gone branches are decided and removed")
check(tries("/compare/main...h15b") == 1 and tries("/compare/main...h16") == 1, "one compare each")
b = build(A, T[15])
check(b and b["state"] == "main" and not b["branches"], f"task 15: merged, then deleted -> main {b}")
check(sorted(dbq("SELECT branch FROM git_commits WHERE conn_id=? AND sha IN ('h15a','h15b')", (CID,))) == [("main",), ("main",)],
      "its commits moved to the default branch")
b = build(A, T[16])
check(b and b["state"] == "branch" and not b["branches"], f"task 16: deleted unmerged -> branch, no open branch listed {b}")

# 6. build-status of a participant: not the context tasks (the parent of their subtask)
r = A.post(B + "/api/users", json={"username": "dave", "display_name": "Dave", "password": "password123"})
assert r.ok, r.text
DID, Dv = r.json()["id"], login(B, "dave")
assert A.put(B + f"/api/lists/{P}/members", json={"user_id": DID, "role": "participant"}).ok
r = A.post(B + "/api/tasks", json={"title": "Sub for Dave", "list_id": P, "parent_id": T[1], "assignee_id": DID})
check(r.ok, f"subtask for the participant {r.status_code} {r.text[:100]}")
r = Dv.get(B + f"/api/lists/{P}/build-status")
check(r.ok and T[1] not in {x["id"] for x in r.json()["data"]}, f"participant: the context task (stale) is left out {r.status_code} {r.text[:200]}")
r = A.get(B + f"/api/lists/{P}/build-status")
check(T[1] in {x["id"] for x in r.json()["data"]}, "the owner still sees task 1")

# ================================================================== GitLab + Bitbucket shapes
GLP = A.post(B + "/api/lists", json={"name": "GL", "kind": "project"}).json()["id"]
BBP = A.post(B + "/api/lists", json={"name": "BB", "kind": "project"}).json()["id"]
G1, G2 = (A.post(B + "/api/tasks", json={"title": f"G{k}", "list_id": GLP}).json()["id"] for k in (1, 2))
B1, B2 = (A.post(B + "/api/tasks", json={"title": f"B{k}", "list_id": BBP}).json()["id"] for k in (1, 2))
STATE["8092"]["grp/app"] = {"default_branch": "main", "pulls": [], "commits": {"main": [gl_cm("glc1", f"Done #{G1}")]},
                            "tags": [{"name": "v1.1.0"}, {"name": "v1.0.0"}],
                            "compare": {"v1.0.0...v1.1.0": [gl_cm("glc1", f"Done #{G1}")], f"kalmido-{G2}": [gl_cm("glb2", "wip")]},
                            "branches": [{"name": "main", "commit": {"id": "glc1"}}, {"name": f"kalmido-{G2}", "commit": {"id": "glh2"}}]}
STATE["8093"]["ws/web"] = {"default_branch": "master", "pulls": [], "commits": {"master": [bb_cm("bbc1", f"Done #{B1}")]},
                           "tags": [{"name": "1.1"}, {"name": "1.0"}],
                           "compare": {"1.0...1.1": [bb_cm("bbc1", f"Done #{B1}")], f"kalmido-{B2}": [bb_cm("bbb2", "wip")]},
                           "branches": [{"name": "master", "target": {"hash": "bbc1"}}, {"name": f"kalmido-{B2}", "target": {"hash": "bbh2"}}]}
put_state()
r1 = A.post(B + f"/api/lists/{GLP}/repos", json={"provider": "gitlab", "base_url": GL, "repo": "grp/app"})
r2 = A.post(B + f"/api/lists/{BBP}/repos", json={"provider": "bitbucket", "base_url": BB, "repo": "ws/web"})
check(r1.status_code == 201 and r2.status_code == 201, f"GitLab + Bitbucket connected {r1.text[:100]} {r2.text[:100]}")
check(until(lambda: (build(A, G1) or {}).get("version") == "1.1.0"), f"GitLab: tag compare from...to {build(A, G1)}")
check(until(lambda: (build(A, G2) or {}).get("state") == "branch"), f"GitLab: branch list + compare {build(A, G2)}")
check(until(lambda: (build(A, B1) or {}).get("version") == "1.1"), f"Bitbucket: commits/<tag>?exclude=<tag> {build(A, B1)}")
b = until(lambda: (build(A, B2) or {}).get("branches") and build(A, B2))
check(b and b["state"] == "branch" and b["branches"][0]["ahead"] == 1 and b["branches"][0]["url"] == f"{BB}/ws/web/branch/kalmido-{B2}",
      f"Bitbucket: branch ahead {b}")

# ================================================================== a person without an organisation (Gitea)
FID, Fr = freelancer(B, A)
FP = Fr.post(B + "/api/lists", json={"name": "Site", "kind": "project"}).json()["id"]
F1, F2 = (Fr.post(B + "/api/tasks", json={"title": f"F{k}", "list_id": FP}).json()["id"] for k in (1, 2))
fk = Fr.post(B + f"/api/lists/{FP}/fields", json={"name": "Version", "type": "text"}).json().get("id")
Fr.patch(B + f"/api/tasks/{F2}", json={"fields": {str(fk): "0.2"}})
STATE["8091"]["frida/site"] = {"default_branch": "main", "pulls": [], "commits": {"main": [gh_cm("fc1", f"Page #{F1}", repo="frida/site", base=GT)]},
                               "tags": [{"name": "v0.2"}, {"name": "v0.1"}],
                               "compare": {"v0.1...v0.2": [gh_cm("fc1", f"Page #{F1}", repo="frida/site", base=GT)]},
                               "branches": [{"name": "main", "commit": {"id": "fc1"}}]}
put_state()
r = Fr.post(B + f"/api/lists/{FP}/repos", json={"provider": "gitea", "base_url": GT, "repo": "frida/site"})
check(r.status_code == 201, f"freelancer: Gitea connected {r.status_code} {r.text[:150]}")
check(until(lambda: (build(Fr, F1) or {}).get("version") == "0.2"), f"freelancer: released 0.2 {build(Fr, F1)}")
r = Fr.get(B + f"/api/lists/{FP}/build-status")
check(r.ok and {x["id"] for x in r.json()["data"]} == {F1, F2}, f"freelancer: build-status {r.status_code} {r.text[:200]}")
r = Fr.put(B + f"/api/lists/{FP}/repos/version-field", json={"field": "off"})
check(r.ok and r.json()["setting"] == "off", f"freelancer: own admin of the version field {r.status_code}")
check(Ca.get(B + f"/api/lists/{FP}/build-status").status_code == 404, "the freelancer's list: a stranger 404")

print(f"p2151_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
