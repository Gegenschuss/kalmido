#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.394.0 B (#3377): the one-time import of GitHub / GitLab issues through a repository connection
(POST /api/repos/<id>/issues/import), against the fake servers of tests/fake_git.py (GitHub :8090, GitLab :8092), never a
real provider. Invented names only.
 - rights: a project member who is no admin 403, a stranger 404, an agent token never (no session route for agents)
 - preview (dry run): counts, pull requests skipped, the comments counted, nothing written; "skip closed issues"
 - the import: title, text, closed = done with its date, labels = tags, the first assignee matched to a member, the others as
   text, comments as comments with an author line and their own date, the issue's address as the link, git_issue_links;
   pages of 100 (GitHub mixes pull requests in); the import history names "GitHub Issues"
 - a second run takes nothing twice ("already"); undo takes the tasks back and their links, then it imports again
 - GitLab: notes without system notes, iid, labels as strings
 - a token without read access to issues, issues switched off, Gitea, a folder repository: a clear message
 - a person without an organisation imports into their own project (freelancer-matrix: tasks)
 - the access tokens never in an answer or the server's log
usage: p2394_b_git_issues_test.py <datadir>"""
import base64
import json
import os
import shutil
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, done, until  # noqa: E402

GH, GL = "http://127.0.0.1:8090", "http://127.0.0.1:8092"
GHTOK, GLTOK, FTOK = "ghp_acmeIssuesRead0042", "glpat-acme-issues-77aa", "ghp_fridaSiteRead0099"
KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()
SEEN = []


def gh_issue(n, title, state="open", body="", labels=(), assignees=(), comments=0, pr=False, closed_at=None, repo="acme/app"):
    return {"number": n, "title": title, "body": body, "state": state, "labels": [{"name": x} for x in labels],
            "assignees": [{"login": a} for a in assignees], "user": {"login": "reporter"}, "html_url": f"{GH}/{repo}/issues/{n}",
            "created_at": "2026-09-01T10:00:00Z", "updated_at": "2026-09-05T10:00:00Z", "closed_at": closed_at, "comments": comments,
            **({"pull_request": {"url": f"{GH}/api/v3/repos/{repo}/pulls/{n}"}} if pr else {})}


ISSUES = [gh_issue(1, "Login fails", body="Steps **to** reproduce", labels=("bug", "ui"), assignees=("octocat", "ghost"), comments=2),
          gh_issue(2, "Old crash", state="closed", closed_at="2026-09-04T12:00:00Z"),
          gh_issue(3, "Add feature", pr=True)] + [gh_issue(n, f"Bulk {n}") for n in range(4, 105)]
STATE = {
    "8090": {"acme/app": {"token": GHTOK, "default_branch": "main", "issues": sorted(ISSUES, key=lambda x: -x["number"]),
                          "issue_comments": {"1": [
                              {"id": 11, "user": {"login": "octocat"}, "body": "I can reproduce", "created_at": "2026-09-02T08:00:00Z"},
                              {"id": 12, "user": {"login": "ghost"}, "body": "Fixed upstream?", "created_at": "2026-09-03T09:00:00Z"}]}},
             "frida/site": {"token": FTOK, "default_branch": "main", "issues": [gh_issue(7, "Contact form", repo="frida/site")]},
             "acme/folder": {"token": GHTOK, "default_branch": "main"}},
    "8092": {"grp/app": {"token": GLTOK, "default_branch": "main", "issues": [
        {"iid": 2, "title": "GL closed", "description": "", "state": "closed", "labels": [], "assignees": [], "author": {"username": "gdev"},
         "web_url": f"{GL}/grp/app/-/issues/2", "created_at": "2026-08-01T10:00:00.123Z", "updated_at": "2026-08-02T10:00:00Z",
         "closed_at": "2026-08-02T10:00:00.000Z", "user_notes_count": 0},
        {"iid": 1, "title": "GL feature", "description": "Text from GitLab", "state": "opened", "labels": ["feature", "scope::x"],
         "assignees": [{"username": "octocat"}], "author": {"username": "gdev"}, "web_url": f"{GL}/grp/app/-/issues/1",
         "created_at": "2026-08-01T09:00:00Z", "updated_at": "2026-08-03T10:00:00Z", "closed_at": None, "user_notes_count": 2}],
        "issue_comments": {"1": [{"id": 31, "system": True, "body": "added ~feature label", "author": {"username": "gdev"},
                                  "created_at": "2026-08-01T09:01:00Z"},
                                 {"id": 32, "system": False, "body": "GL note", "author": {"username": "gdev"},
                                  "created_at": "2026-08-02T09:00:00Z"}]}}},
}


def put_state():
    tmp = os.path.join(DATA, "git.json.tmp")
    with open(tmp, "w") as f:
        json.dump(STATE, f)
    os.replace(tmp, os.path.join(DATA, "git.json"))


if kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_CALENDAR_ALLOW_HOSTS": "127.0.0.1"}, prefix="P2394B"):
    shutil.copy(os.path.join(N, "fake_git.py"), DATA)
    put_state()
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_git.py"])
kt.docker_logs_on_first_fail()
until(lambda: os.path.exists(os.path.join(DATA, "git.log")), 20)  # fake_git.py opens its log when it starts


class S(requests.Session):
    def request(self, *a, **k):
        r = super().request(*a, **k)
        SEEN.append(r.text)
        return r


A = kt.setup(lang="en")
A.__class__ = S
ids = {}
for u, dn in (("bob", "Bob"), ("carol", "Carol"), ("octocat", "Octo Cat")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": dn, "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = kt.sess("bob", session_cls=S), kt.sess("carol", session_cls=S)
for x in (Bo, Ca):
    x.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["write", "import"], "username": "claude", "display_name": "Claude"})
assert r.status_code == 201, r.text
AG, AGTOK = r.json()["id"], r.json()["token"]
P = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
for u, role in (("bob", "edit"), ("octocat", "edit")):
    assert A.put(B + f"/api/lists/{P}/members", json={"user_id": ids[u], "role": role}).ok
assert A.put(B + f"/api/lists/{P}/members", json={"user_id": AG, "role": "edit"}).ok
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "github", "base_url": GH, "repo": "acme/app", "token": GHTOK})
check(r.status_code == 201, f"GitHub repository connected: {r.status_code} {r.text[:200]}")
GID = r.json().get("id")
check(r.json().get("issue_sync") is False and r.json().get("issue_create") is False, "the sync switches are there, off")


def imp(s, cid, **b):
    return s.post(B + f"/api/repos/{cid}/issues/import", json=b)


def ntasks(lid, live=True):
    return kt.dbx("SELECT COUNT(*) FROM tasks WHERE list_id=? AND tt_id LIKE 'git%'" + (" AND deleted_at IS NULL" if live else ""), (lid,))[0][0]


def nlinks(cid):
    return kt.dbx("SELECT COUNT(*) FROM git_issue_links WHERE conn_id=?", (cid,))[0][0]


# ---- rights
check(imp(Bo, GID, dry_run=True).status_code == 403, "a member without admin rights: 403")
check(imp(Ca, GID, dry_run=True).status_code == 404, "a stranger: 404")
r = requests.post(B + f"/api/repos/{GID}/issues/import", json={"dry_run": True}, timeout=60,
                  headers={"Authorization": "Bearer " + AGTOK, "X-Requested-With": "kalmido"})
check(r.status_code in (401, 403) and ntasks(P) == 0, f"an agent token: refused ({r.status_code})")
check(imp(A, GID, dry_run="yes").status_code == 400 and imp(A, GID, completed="maybe").status_code == 400, "invalid values: 400")
check(imp(A, GID, dry_run=True, target=5).status_code == 400, "an unknown field: 400")

# ---- preview
n0 = len(open(os.path.join(DATA, "git.log")).readlines())
r = imp(A, GID, dry_run=True)
j = r.json()
check(r.ok and j.get("dry_run") is True and j["created"]["tasks"] == 103 and j.get("pull_requests") == 1 and j.get("already") == 0,
      f"preview: 103 issues, the pull request skipped: {r.status_code} {r.text[:300]}")
check(j.get("comments") == 2 and j["created"]["done"] == 1 and j.get("source_name") == "GitHub Issues", f"preview: comments + closed counted: {j.get('comments')} {j['created']}")
check(j.get("samples") and j["samples"][0]["title"] == "Login fails", f"preview: the first titles {[x['title'] for x in j.get('samples') or []][:3]}")
check(ntasks(P, live=False) == 0 and nlinks(GID) == 0, "preview: nothing written")
lg = [json.loads(x) for x in open(os.path.join(DATA, "git.log")).readlines()[n0:]]
iss = [x for x in lg if "/issues?" in x["path"]]
check(len(iss) == 2 and "page=2" in iss[1]["path"] and all(x["auth"] == "Bearer " + GHTOK for x in iss), f"two pages of 100 with the token: {[x['path'] for x in iss]}")
check(not any("/comments" in x["path"] for x in lg), "preview: no comment requests (counted from the issues)")
r = imp(A, GID, dry_run=True, completed="skip")
check(r.ok and r.json()["created"]["tasks"] == 102, f"preview without the closed ones: {r.json().get('created')}")

# ---- the import
r = imp(A, GID)
j = r.json()
check(r.ok and j.get("import_id") and j["created"]["tasks"] == 103 and j.get("comments") == 2 and j["created"]["assigned"] == 1,
      f"imported: {r.status_code} {r.text[:300]}")
IID = j.get("import_id")
check(ntasks(P) == 103 and nlinks(GID) == 103, f"103 tasks and links: {ntasks(P)} {nlinks(GID)}")
t1 = kt.dbx("SELECT id, title, content, status, assignee_id, url FROM tasks WHERE tt_id=?", (f"github:{GID}:1",))
check(t1 and t1[0][1] == "Login fails" and "Steps **to** reproduce" in t1[0][2] and "acme/app#1" in t1[0][2]
      and "Assignee (GitHub Issues): ghost" in t1[0][2] and t1[0][3] == 0 and t1[0][4] == ids["octocat"] and t1[0][5] == f"{GH}/acme/app/issues/1",
      f"issue 1: title, text, reference, assignee matched, the other as text, link: {t1}")
T1 = t1[0][0] if t1 else 0
# 2.394.0 C (#3377): labels are the project tags now (shared, synced with the issue), no longer the importer's own tags
LTQ = "SELECT lt.name FROM obj_tag_links x JOIN obj_tags lt ON lt.id=x.tag_id WHERE x.kind='task' AND x.obj_id=?"  # 2.947.0 (#5275): the core's tags (obj_tags / obj_tag_links)
check(sorted(x[0] for x in kt.dbx(LTQ, (T1,))) == ["bug", "ui"] and not kt.dbx("SELECT 1 FROM (SELECT k.obj_id AS task_id, CAST(ot.scope_id AS BIGINT) AS user_id, ot.name AS tag FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id AND ot.scope_kind='user' WHERE k.kind='task') task_tags WHERE task_id=?", (T1,)), "labels = project tags")  # 2.955.0 (#5276): personal tags are rows of the core (obj_tags scope user), read as the old task_tags
cm = kt.dbx("SELECT body, created_at, user_id FROM comments WHERE task_id=? ORDER BY created_at", (T1,))
check(len(cm) == 2 and cm[0][0].startswith("@octocat on 2026-09-02:") and "I can reproduce" in cm[0][0] and cm[0][1].startswith("2026-09-02")
      and cm[1][0].startswith("@ghost on 2026-09-03:") and cm[0][2] == 1, f"comments with author line and their date: {cm}")
t2 = kt.dbx("SELECT status, completed_at FROM tasks WHERE tt_id=?", (f"github:{GID}:2",))
check(t2 and t2[0][0] == 2 and str(t2[0][1]).startswith("2026-09-04"), f"closed = done with its date: {t2}")
check(not kt.dbx("SELECT 1 FROM tasks WHERE tt_id=?", (f"github:{GID}:3",)), "the pull request did not become a task")
check(kt.dbx("SELECT remote_updated_at FROM git_issue_links WHERE conn_id=? AND issue_no=1", (GID,))[0][0].startswith("2026-09-05"), "link keeps the issue's update time")
hist = A.get(B + "/api/imports").json()["imports"]
check(hist and hist[0]["id"] == IID and hist[0]["source_name"] == "GitHub Issues" and hist[0]["can_undo"], f"import history: {hist[:1]}")

# ---- nothing twice
r = imp(A, GID, dry_run=True)
check(r.ok and r.json().get("already") == 103 and r.json()["created"]["tasks"] == 0, f"second preview: already 103: {r.text[:200]}")
r = imp(A, GID)
check(r.ok and r.json()["created"]["tasks"] == 0 and ntasks(P) == 103, "second run: nothing new")
STATE["8090"]["acme/app"]["issues"].insert(0, gh_issue(105, "Brand new"))
put_state()
r = imp(A, GID)
check(r.ok and r.json()["created"]["tasks"] == 1 and r.json().get("already") == 103 and ntasks(P) == 104, f"a new issue later: only it: {r.text[:200]}")
IID2 = r.json().get("import_id")

# ---- undo
r = A.post(B + f"/api/imports/{IID}/undo")
check(r.ok and r.json().get("tasks") == 103, f"undo: {r.status_code} {r.text[:200]}")
check(ntasks(P) == 1 and nlinks(GID) == 1, f"undo: the tasks and their links are gone, the later import stays: {ntasks(P)} {nlinks(GID)}")
r = imp(A, GID, dry_run=True)
check(r.ok and r.json()["created"]["tasks"] == 103 and r.json().get("already") == 1, f"after undo they import again: {r.text[:200]}")
check(A.post(B + f"/api/imports/{IID2}/undo").ok and nlinks(GID) == 0, "the second undo too")

# ---- GitLab
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "gitlab", "base_url": GL, "repo": "grp/app", "token": GLTOK})
check(r.status_code == 201, f"GitLab connected: {r.status_code} {r.text[:200]}")
LID = r.json().get("id")
r = imp(A, LID)
j = r.json()
check(r.ok and j["created"]["tasks"] == 2 and j.get("comments") == 1 and j.get("source_name") == "GitLab Issues", f"GitLab imported: {r.text[:300]}")
g1 = kt.dbx("SELECT id, content, assignee_id, status FROM tasks WHERE tt_id=?", (f"gitlab:{LID}:1",))
check(g1 and "Text from GitLab" in g1[0][1] and g1[0][2] == ids["octocat"] and g1[0][3] == 0, f"GitLab issue: text, assignee: {g1}")
G1 = g1[0][0] if g1 else 0
check(sorted(x[0] for x in kt.dbx(LTQ, (G1,))) == ["feature", "scope::x"], "GitLab labels = project tags")  # 2.394.0 C (#3377)
gc = kt.dbx("SELECT body FROM comments WHERE task_id=?", (G1,))
check(len(gc) == 1 and gc[0][0].startswith("@gdev on 2026-08-02:") and "GL note" in gc[0][0], f"GitLab: notes without system notes: {gc}")
g2 = kt.dbx("SELECT status, completed_at FROM tasks WHERE tt_id=?", (f"gitlab:{LID}:2",))
check(g2 and g2[0][0] == 2 and str(g2[0][1]).startswith("2026-08-02"), f"GitLab closed: {g2}")
lgl = [json.loads(x) for x in open(os.path.join(DATA, "git.log")) if '"port": 8092' in x and "/issues" in x]
check(lgl and all(x["ptok"] == GLTOK for x in lgl) and any("/issues/1/notes" in x["path"] for x in lgl), "GitLab: PRIVATE-TOKEN, notes of the issue")

# ---- clear messages
STATE["8090"]["acme/app"]["issues_denied"] = True
put_state()
r = imp(A, GID, dry_run=True)
check(r.status_code == 409 and "read access to the issues" in r.json().get("error", ""), f"no read access to issues: {r.status_code} {r.text[:200]}")
STATE["8090"]["acme/app"].pop("issues_denied")
STATE["8090"]["acme/app"]["issues_off"] = True
put_state()
r = imp(A, GID, dry_run=True)
check(r.status_code == 409 and "switched on" in r.json().get("error", ""), f"issues off: {r.status_code} {r.text[:200]}")
GT = kt.dbx("INSERT INTO git_conns(list_id, provider, base_url, owner, repo, next_at, created_by, created_at) "
            "VALUES(?, 'gitea', 'http://127.0.0.1:9', 'acme', 'tea', 9e12, 1, '2026-10-01T00:00:00Z') RETURNING id", (P,))[0][0]
r = imp(A, GT, dry_run=True)
check(r.status_code == 409 and "not available for this provider" in r.json().get("error", ""), f"Gitea: not yet: {r.status_code} {r.text[:200]}")
FR = kt.dbx("INSERT INTO git_conns(list_id, provider, base_url, owner, repo, next_at, created_by, created_at) "
            "VALUES(?, 'github', ?, 'acme', 'folder', 9e12, 1, '2026-10-01T00:00:00Z') RETURNING id", (P, GH))[0][0]
kt.dbx("INSERT INTO git_folders(conn_id, owner_id, folder, created_at) VALUES(?, 1, 'Work', '2026-10-01T00:00:00Z')", (FR,))
r = imp(A, FR, dry_run=True)
check(r.status_code == 409 and "folder" in r.json().get("error", ""), f"a folder repository: 409: {r.status_code} {r.text[:200]}")

# ---- a person without an organisation (freelancer-matrix: tasks)
FID, F = freelancer(B, A, "frida")
F.__class__ = S
FP = F.post(B + "/api/lists", json={"name": "Site", "kind": "project"}).json()["id"]
r = F.post(B + f"/api/lists/{FP}/repos", json={"provider": "github", "base_url": GH, "repo": "frida/site", "token": FTOK})
check(r.status_code == 201, f"freelancer: repository connected: {r.status_code} {r.text[:200]}")
FC = r.json().get("id")
r = F.post(B + f"/api/repos/{FC}/issues/import", json={"dry_run": True})
check(r.ok and r.json()["created"]["tasks"] == 1, f"freelancer: preview {r.text[:200]}")
r = F.post(B + f"/api/repos/{FC}/issues/import", json={})
check(r.ok and r.json().get("import_id") and ntasks(FP) == 1 and nlinks(FC) == 1, f"freelancer: imported into the own project {r.text[:200]}")
check(imp(A, FC, dry_run=True).status_code == 404, "someone else's project: 404 (also for the instance admin)")

# ---- no token anywhere
check(not any(t in x for x in SEEN for t in (GHTOK, GLTOK, FTOK)), "no access token in any answer")
log = subprocess.run(["docker", "logs", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
check(all(t not in log for t in (GHTOK, GLTOK, FTOK)) and "import github" in log, "no access token in the server's log (the import is logged)")

sys.exit(done("p2394_b_git_issues"))
