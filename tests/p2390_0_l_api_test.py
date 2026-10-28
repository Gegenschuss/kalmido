#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.390.0 (#3353): ticket keys APP-123, own container (start.sh) with the fake Git servers of fake_git.py (GitHub :8090).
 - the key of a project (PATCH /api/lists/<id> ticket_key): 2-6 capitals / digits with a letter first, upper-cased,
   unique per workspace (the same key in another person's private space and in an organisation next to a private list of
   the same person is fine), only owner / project admins; the tasks there before get numbers in the order they were made,
   new ones (app + API v1) the next one
 - a task moved out keeps its old key as an alias and gets the next number of the new project (moved back: its old
   number again); a changed key keeps the old keys; a removed key leaves the task without key (the alias still finds it)
 - API v1: field key of a task, ticket_key of a list (also PATCH), GET /api/v1/tasks/APP-12 (current and old keys, only
   tasks the token sees: 404 otherwise)
 - Git: "MOB-4" in a commit links, "fixes MOB-3" completes, branch "mob-1-login" of a pull request links, an old key
   (APP-4) still links; in a project with a key a NEW connection ignores "#id" until its switch hash_ids is on; a project
   without a key reads "#id" as before; existing connections keep hash_ids on (column default 1)
freelancer-matrix: tasks
usage: p2390_0_l_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
from kt import FAILS, OKS, check, sess, until, B, H, DATA, CT  # noqa: E402,F401  (shared helpers, tests/kt.py)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
KEY = base64.b64encode(os.urandom(32)).decode()
GH = "http://127.0.0.1:8090"      # fake GitHub Enterprise (fake_git.py, API under /api/v3)
TOKEN = "ghp_fake_read_only_token_3353"
V = B + "/api/v1"
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1"
                        " -e KALMIDO_GIT_POLL=2 -e KALMIDO_GIT_TICK=1 -e KALMIDO_SECRET_KEY=" + KEY))
A = kt.setup()
FID, Fr = freelancer(B, A)                 # the person without an organisation: every key check runs as her
GID, Gi = freelancer(B, A, "fiona")


def tok(s, scopes=("read", "tasks:write")):
    r = s.post(B + "/api/me/tokens", json={"name": "keys", "scopes": list(scopes)})
    assert r.ok, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def nos(lid):
    return [tuple(x) for x in kt.dbx("SELECT id, ticket_no FROM tasks WHERE list_id=? AND deleted_at IS NULL ORDER BY id", (lid,))]


def no_of(tid):
    r = kt.dbx("SELECT ticket_no FROM tasks WHERE id=?", (tid,))
    return r[0][0] if r else None


def key_get(h, key):
    return requests.get(V + f"/tasks/{key}", headers=h)


FH, GH_H = tok(Fr), tok(Gi)
P = Fr.post(B + "/api/lists", json={"name": "Mobile App", "kind": "project"}).json()["id"]
check(Fr.patch(B + f"/api/lists/{P}", json={"tickets": True}).ok, "setup: ticket types on")
T = [Fr.post(B + "/api/tasks", json={"title": f"Ticket {i}", "list_id": P}).json()["id"] for i in range(1, 4)]
check(all(no_of(t) is None for t in T), "#3353: without a key the tasks have no number")
for bad in ("a", "1AB", "TOOLONG", "A-B", "Ä B"):
    r = Fr.patch(B + f"/api/lists/{P}", json={"ticket_key": bad})
    check(r.status_code == 400, f"#3353: key {bad!r} refused (400) " + r.text[:120])
r = Fr.patch(B + f"/api/lists/{P}", json={"ticket_key": " app "})
check(r.ok, "#3353: the freelancer sets the key of her project " + r.text[:160])
st = Fr.get(B + "/api/state").json()
lp = next(x for x in st["lists"] if x["id"] == P)
check(lp.get("ticket_key") == "APP", "#3353: stored upper case, the app state carries it " + str(lp.get("ticket_key")))
check(nos(P) == [(T[0], 1), (T[1], 2), (T[2], 3)], "#3353: the tasks there before are numbered in the order they were made " + str(nos(P)))
tp = {x["id"]: x for x in st["tasks"]}
check(tp.get(T[1], {}).get("ticket_no") == 2, "#3353: the app's task carries ticket_no")
T4 = Fr.post(B + "/api/tasks", json={"title": "Ticket 4", "list_id": P}).json()["id"]
check(no_of(T4) == 4, "#3353: a new task gets the next number")
r = requests.post(V + "/tasks", headers=FH, json={"title": "Ticket 5", "list_id": P})
check(r.status_code == 201 and r.json().get("key") == "APP-5", "#3353: API v1 create answers key APP-5 " + r.text[:160])
T5 = r.json().get("id")
r = requests.get(V + f"/tasks/{T[0]}", headers=FH)
check(r.ok and r.json().get("key") == "APP-1", "#3353: GET /tasks/<id> carries key")
r = key_get(FH, "APP-2")
check(r.ok and r.json().get("id") == T[1], "#3353: GET /api/v1/tasks/APP-2 " + r.text[:160])
check(key_get(FH, "app-2").json().get("id") == T[1], "#3353: a key in lower case finds it too")
check(key_get(FH, "APP-99").status_code == 404 and key_get(FH, "APP-0x").status_code == 404, "#3353: an unknown key / no key: 404")
check(key_get(GH_H, "APP-2").status_code == 404, "#3353: another person's token does not see it (404, no leak)")
r = requests.get(V + "/tasks", headers=FH, params={"key": "APP-3"})
check(r.ok and [x["id"] for x in r.json()["data"]] == [T[2]], "#3353: GET /api/v1/tasks?key=APP-3 " + r.text[:160])
check(requests.get(V + "/tasks", headers=GH_H, params={"key": "APP-3"}).json().get("data") == [], "#3353: ?key= only lists tasks the token sees")
check(requests.get(V + "/tasks", headers=FH, params={"key": "nokey"}).status_code == 400, "#3353: ?key= with no key: 400")
r = requests.get(V + f"/lists/{P}", headers=FH)
check(r.ok and r.json().get("ticket_key") == "APP", "#3353: API v1 list carries ticket_key")
lt = requests.get(V + "/tasks", headers=FH, params={"list_id": P}).json()["data"]
check(sorted(x.get("key") or "" for x in lt) == ["APP-1", "APP-2", "APP-3", "APP-4", "APP-5"], "#3353: the task list carries key " + str([x.get("key") for x in lt]))

# the workspace rule
Q = Fr.post(B + "/api/lists", json={"name": "Website", "kind": "project"}).json()["id"]
r = Fr.patch(B + f"/api/lists/{Q}", json={"ticket_key": "APP"})
check(r.status_code == 400, "#3353: the same key twice in one workspace: 400 " + r.text[:120])
GQ = Gi.post(B + "/api/lists", json={"name": "Her app", "kind": "project"}).json()["id"]
check(Gi.patch(B + f"/api/lists/{GQ}", json={"ticket_key": "APP"}).ok, "#3353: another person's private space may use APP too")
check(Fr.patch(B + f"/api/lists/{Q}", json={"ticket_key": "WEB"}).ok, "#3353: WEB for the second project")
# only owner / project admins
AL = A.post(B + "/api/lists", json={"name": "Shared one", "kind": "project"}).json()["id"]
check(A.put(B + f"/api/lists/{AL}/members", json={"user_id": FID, "role": "edit"}).ok, "setup: shared with the freelancer (edit)")
check(Fr.patch(B + f"/api/lists/{AL}", json={"ticket_key": "SHR"}).status_code == 403, "#3353: a member (edit) cannot set the key: 403")
r = requests.patch(V + f"/lists/{P}", headers=tok(Fr, ("read", "structure")), json={"ticket_key": "APP"})
check(r.ok and r.json().get("ticket_key") == "APP", "#3353: API v1 PATCH accepts ticket_key (unchanged) " + r.text[:160])

# moves and aliases
check(Fr.patch(B + f"/api/tasks/{T[1]}", json={"list_id": Q}).ok, "setup: APP-2 moved to Website")
check(no_of(T[1]) == 1, "#3353: the moved task gets WEB-1 " + str(no_of(T[1])))
check(key_get(FH, "APP-2").json().get("id") == T[1] and key_get(FH, "WEB-1").json().get("id") == T[1],
      "#3353: the old key APP-2 still finds it (alias), WEB-1 too")
check(requests.get(V + f"/tasks/{T[1]}", headers=FH).json().get("key") == "WEB-1", "#3353: its key now WEB-1")
check(Fr.patch(B + f"/api/lists/{P}", json={"ticket_key": "MOB"}).ok, "#3353: the key changed to MOB")
check(key_get(FH, "APP-1").json().get("id") == T[0] and key_get(FH, "MOB-1").json().get("id") == T[0], "#3353: APP-1 and MOB-1 both find it")
T6 = Fr.post(B + "/api/tasks", json={"title": "Ticket 6", "list_id": P}).json()["id"]
check(no_of(T6) == 6, "#3353: numbers go on after a key change (no reuse) " + str(no_of(T6)))
check(Fr.patch(B + f"/api/lists/{Q}", json={"ticket_key": ""}).ok, "#3353: the key of Website removed")
check(requests.get(V + f"/tasks/{T[1]}", headers=FH).json().get("key") is None and key_get(FH, "WEB-1").json().get("id") == T[1],
      "#3353: without a key the task has no key, the old one still finds it")
check(Fr.patch(B + f"/api/tasks/{T[1]}", json={"list_id": P}).ok and no_of(T[1]) == 7, "#3353: moved back it gets the next number MOB-7")
check(Fr.patch(B + f"/api/tasks/{T4}", json={"list_id": Q}).ok and no_of(T4) is None, "setup: MOB-4 moved to Website (no key: no number)")
check(Fr.patch(B + f"/api/tasks/{T4}", json={"list_id": P}).ok and no_of(T4) == 4, "#3353: moved back (an undo) it gets MOB-4 again " + str(no_of(T4)))

# ------------------------------------------------------------------ Git
STATE = {"8090": {"acme/app": {"token": TOKEN, "default_branch": "main", "pulls": [], "commits": {"main": []}},
                  "acme/web": {"token": TOKEN, "default_branch": "main", "pulls": [], "commits": {"main": []}}}}


def put_state():
    tmp = os.path.join(DATA, "git.json.tmp")
    with open(tmp, "w") as f:
        json.dump(STATE, f)
    os.replace(tmp, os.path.join(DATA, "git.json"))


def gts(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ghpr(n, title, body="", ref="feature-x", repo="acme/app"):
    return {"number": n, "title": title, "body": body, "state": "open", "merged_at": None, "html_url": f"{GH}/{repo}/pull/{n}",
            "user": {"login": "dev"}, "head": {"ref": ref, "sha": f"sha{n:04d}"}, "updated_at": gts(datetime.now(timezone.utc))}


def ghcm(sha, msg, repo="acme/app"):
    at = gts(datetime.now(timezone.utc) + timedelta(seconds=5))
    return {"sha": sha, "html_url": f"{GH}/{repo}/commit/{sha}", "author": {"login": "dev"},
            "commit": {"message": msg, "author": {"name": "Dev", "date": at}, "committer": {"date": at}}}


def links(tid):
    return {(x[0], x[1]) for x in kt.dbx("SELECT kind, ref FROM git_links WHERE task_id=?", (tid,))}


put_state()
subprocess.run(["cp", os.path.join(N, "fake_git.py"), DATA])
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_git.py"])
time.sleep(0.8)
dflt = kt.dbx("SELECT column_default FROM information_schema.columns WHERE table_name='git_conns' AND column_name='hash_ids'")
check(dflt and str(dflt[0][0]).strip("'") == "1", "#3353: connections from before 2.390.0 keep reading #id (column default 1) " + str(dflt))
r = Fr.post(B + f"/api/lists/{P}/repos", json={"provider": "github", "base_url": GH, "repo": "acme/app", "token": TOKEN})
check(r.status_code == 201 and r.json().get("hash_ids") is False, "#3353: a new connection starts with hash_ids off " + r.text[:200])
CID = r.json().get("id")
STATE["8090"]["acme/app"]["commits"]["main"] = [ghcm("c0001", "MOB-4: first part"), ghcm("c0002", "fixes MOB-3"),
                                                 ghcm("c0003", f"refs #{T6}"), ghcm("c0004", "old key APP-5 in a message")]
STATE["8090"]["acme/app"]["pulls"] = [ghpr(5, "Login screen", ref="mob-1-login"), ghpr(6, "Unrelated", body=f"see #{T6} upstream", ref=f"{T6}-slug")]
put_state()
Fr.post(B + f"/api/repos/{CID}/refresh")
check(until(lambda: ("commit", "c0001") in links(T4), 40), "#3353: MOB-4 in a commit links the task " + str(links(T4)))
check(until(lambda: kt.dbx("SELECT status FROM tasks WHERE id=?", (T[2],))[0][0] == 2, 30), "#3353: fixes MOB-3 on the default branch completes it")
check(until(lambda: ("pr", "5") in links(T[0]), 30), "#3353: branch mob-1-login of a pull request links MOB-1")
check(("commit", "c0004") in links(T5), "#3353: the old key APP-5 still links")
check(not links(T6), "#3353: with a key and hash_ids off, #id / <id>-slug do not link (no clash with the Git server's issues) " + str(links(T6)))
r = Fr.patch(B + f"/api/repos/{CID}", json={"hash_ids": True})
check(r.ok and r.json().get("hash_ids") is True, "#3353: the switch hash_ids on " + r.text[:160])
check(Fr.patch(B + f"/api/repos/{CID}", json={"hash_ids": "yes"}).status_code == 400, "#3353: hash_ids must be a boolean")
STATE["8090"]["acme/app"]["commits"]["main"].append(ghcm("c0005", f"again #{T6}"))
put_state()
Fr.post(B + f"/api/repos/{CID}/refresh")
check(until(lambda: ("commit", "c0005") in links(T6), 40), "#3353: with the switch on #id links again " + str(links(T6)))
# a project without a key reads #id on a new connection as before
TW = Fr.post(B + "/api/tasks", json={"title": "Web task", "list_id": Q}).json()["id"]
r = Fr.post(B + f"/api/lists/{Q}/repos", json={"provider": "github", "base_url": GH, "repo": "acme/web", "token": TOKEN})
check(r.status_code == 201, "setup: acme/web on Website (no key) " + r.text[:120])
STATE["8090"]["acme/web"]["commits"]["main"] = [ghcm("w0001", f"work on #{TW}", repo="acme/web")]
put_state()
Fr.post(B + f"/api/repos/{r.json().get('id')}/refresh")
check(until(lambda: ("commit", "w0001") in links(TW), 40), "#3353: a project without a key reads #id as before")

sys.exit(kt.done("p2390_0_l_api"))
