#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.394.0 C (#3377): the two-way sync of GitHub / GitLab issues per repository connection (integrations/git_sync.py),
against the fake servers of tests/fake_git.py (GitHub :8090, GitLab :8092), never a real provider. Invented names only.
The git loop runs every second (KALMIDO_GIT_TICK=1), a connection polls only when the suite sets next_at = 0 (KALMIDO_GIT_POLL
3600), a collected change goes out when the suite sets push_due = 1 (KALMIDO_GIT_SYNC_PUSH stays 30 s); every wait is on a
real state (next_at / push_due / the fake's log), never a fixed time.
 - the switches: a member who is no admin 403, a stranger 404, an agent token refused, invalid values 400; on: write access
   checked (GitHub permissions.push); a token without write access: read only (shown), nothing goes out; a write refused
   later: read only from then on
 - pull: a new issue -> a task in "Backlog" with its link, labels as project tags, its comment; title / text / closed /
   labels / a new comment of a linked issue -> the task (history names the issue)
 - push: title / reopen / project tags / a comment of a linked task, collected (push_due ~30 s, nothing sent before), then
   one PATCH + the comment; no echo (the next round changes nothing, sends nothing)
 - conflict: both changed the title -> the newer one wins, the other in the history (git_sync_lost), both directions
 - never sent: a locked (private) note, personal tags; an end-to-end encrypted project: the switch is locked (409)
 - "create new tasks as issues": a new task -> POST issues, link, the task gets the issue's address; a subtask never
 - a deleted / moved task: link gone, never a task again; "fixes #<task id>" in a merged pull request completes nothing
   while the sync is on (#12 is the repository's issue there)
 - GitLab: iid, PUT with state_event, labels as a comma list, notes
 - a person without an organisation (freelancer-matrix: tasks); no token in any answer
 - review of part B: comments without a date keep the task's time, control / bidi characters out of comment texts, an issue
   linked while an import runs is not taken twice, the "only the newest" warning names the real number
 - 2.394.0 D (review of C): a write that worked is never repeated after a later error (new issue + failed close; comment A
   sent, B failed), a change noted while a send runs stays due, a conflict is decided by the field's own time (issue
   events) and logged once although the comments hit the rate limit, a long title goes out cut to 255, a link is given up
   after 5 equal errors (history), GitHub triage is no write access, a new token sent with the switch is the one checked
usage: p2394_c_git_sync_test.py <datadir>"""
import base64
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, done, until  # noqa: E402

GH, GL = "http://127.0.0.1:8090", "http://127.0.0.1:8092"
GHTOK, GLTOK, FTOK = "ghp_acmeSyncWrite0042", "glpat-acme-sync-77aa", "ghp_fridaSyncWrite0099"
KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()
SEEN = []
CLOCK = [datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=10)]


def tick():
    """The next remote time stamp: later than everything before (and than the server's clock)."""
    CLOCK[0] += timedelta(minutes=1)
    return CLOCK[0].strftime("%Y-%m-%dT%H:%M:%SZ")


def gh_issue(n, title, state="open", body="", labels=(), comments=0, created=None, updated=None, repo="acme/app"):
    return {"number": n, "title": title, "body": body, "state": state, "labels": [{"name": x} for x in labels], "assignees": [],
            "user": {"login": "reporter"}, "html_url": f"{GH}/{repo}/issues/{n}", "created_at": created or "2026-09-01T10:00:00Z",
            "updated_at": updated or "2026-09-05T10:00:00Z", "closed_at": None, "comments": comments}


STATE = {
    "8090": {"acme/app": {"token": GHTOK, "default_branch": "main", "issues": [gh_issue(1, "Old issue", body="Old text", labels=("bug",))]},
             "acme/ro": {"token": GHTOK, "default_branch": "main", "permissions": {"push": False, "pull": True},
                         "issues": [gh_issue(1, "RO issue", repo="acme/ro")]},
             "acme/e2e": {"token": GHTOK, "default_branch": "main"},
             "acme/rev": {"token": GHTOK, "default_branch": "main", "issues": [
                 gh_issue(1, "No date", comments=1, repo="acme/rev", created="2026-08-01T08:00:00Z"),
                 gh_issue(2, "Raced", comments=1, repo="acme/rev")],
                 "issue_comments": {"1": [{"id": 51, "user": {"login": "eve‮"}, "body": "Bidi ‮text​ here"}],
                                    "2": [{"id": 52, "user": {"login": "x"}, "body": "c", "created_at": "2026-09-02T08:00:00Z"}]}},
             "acme/prs": {"token": GHTOK, "default_branch": "main",
                          "issues": [gh_issue(n, f"Real {n}", repo="acme/prs") for n in range(1, 6)]
                          + [gh_issue(n, f"PR {n}", repo="acme/prs") | {"pull_request": {"url": "x"}} for n in range(10, 3010)]},
             "frida/site": {"token": FTOK, "default_branch": "main", "issues": []}},
    "8092": {"grp/app": {"token": GLTOK, "default_branch": "main", "issues": [
        {"iid": 1, "title": "GL one", "description": "GL text", "state": "opened", "labels": ["feature"], "assignees": [],
         "author": {"username": "gdev"}, "web_url": f"{GL}/grp/app/-/issues/1", "created_at": "2026-08-01T09:00:00Z",
         "updated_at": "2026-08-03T10:00:00Z", "closed_at": None, "user_notes_count": 0}]}},
}
GJ = os.path.join(DATA, "git.json")


def put_state():
    tmp = GJ + ".tmp"
    with open(tmp, "w") as f:
        json.dump(STATE, f)
    os.replace(tmp, GJ)


def edit(port, repo, fn):
    """Changes the fake's repository in place (re-read first: the fake writes its own changes into git.json)."""
    st = json.load(open(GJ))
    fn(st[str(port)][repo])
    tmp = GJ + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, GJ)


def remote(port, repo, no):
    k = "iid" if port == 8092 else "number"
    return next(x for x in json.load(open(GJ))[str(port)][repo]["issues"] if x[k] == no)


if kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_CALENDAR_ALLOW_HOSTS": "127.0.0.1", "KALMIDO_GIT_POLL": "3600",
                 "KALMIDO_GIT_TICK": "1"}, prefix="P2394C"):
    shutil.copy(os.path.join(N, "fake_git.py"), DATA)
    put_state()
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_git.py"])
kt.docker_logs_on_first_fail()
until(lambda: os.path.exists(os.path.join(DATA, "git.log")), 20)
LOGF = os.path.join(DATA, "git.log")


def loglen():
    return len(open(LOGF).readlines())


def log_from(n0):
    return [json.loads(x) for x in open(LOGF).readlines()[n0:]]


def writes(n0, port=8090):
    return [x for x in log_from(n0) if x.get("method") in ("PATCH", "PUT", "POST") and x["port"] == port]


class S(requests.Session):
    def request(self, *a, **k):
        r = super().request(*a, **k)
        SEEN.append(r.text)
        return r


A = kt.setup(lang="en")
A.__class__ = S
ids = {}
for u, dn in (("bob", "Bob"), ("carol", "Carol")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": dn, "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = kt.sess("bob", session_cls=S), kt.sess("carol", session_cls=S)
for x in (Bo, Ca):
    x.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
assert r.status_code == 201, r.text
AG, AGTOK = r.json()["id"], r.json()["token"]
P = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
assert A.put(B + f"/api/lists/{P}/members", json={"user_id": ids["bob"], "role": "edit"}).ok
assert A.put(B + f"/api/lists/{P}/members", json={"user_id": AG, "role": "edit"}).ok
for nm in ("Doing", "Backlog"):
    assert A.post(B + "/api/sections", json={"list_id": P, "name": nm}).ok
BACKLOG = kt.dbx("SELECT id FROM sections WHERE list_id=? AND name='Backlog'", (P,))[0][0]


def connect(s, lid, prov, base, repo, tok):
    r = s.post(B + f"/api/lists/{lid}/repos", json={"provider": prov, "base_url": base, "repo": repo, "token": tok})
    check(r.status_code == 201, f"{repo} connected: {r.status_code} {r.text[:200]}")
    return r.json().get("id")


def poll(cid):
    """One poll of connection cid by the git loop (next_at 0 -> it runs and sets next_at an hour ahead)."""
    kt.dbx("UPDATE git_conns SET next_at=0 WHERE id=?", (cid,))
    return until(lambda: kt.dbx("SELECT next_at FROM git_conns WHERE id=?", (cid,))[0][0] > 1000, 30)


def push(tid):
    """The collected changes of task tid go out now (push_due 1 -> the loop sends them and sets 0)."""
    kt.dbx("UPDATE git_issue_links SET push_due=1 WHERE task_id=? AND push_due>0", (tid,))
    return until(lambda: (lambda r: r and r[0][0] == 0)(kt.dbx("SELECT push_due FROM git_issue_links WHERE task_id=?", (tid,))), 30)


def task(tid):
    return A.get(B + f"/api/tasks/{tid}").json()


def acts(tid, kind):
    return [a for a in A.get(B + f"/api/tasks/{tid}/timeline").json()["activity"] if a["kind"] == kind]


def comments(tid):
    return [x[0] for x in kt.dbx("SELECT body FROM comments WHERE task_id=? AND deleted_at IS NULL ORDER BY id", (tid,))]


def link(tid):
    r = kt.dbx("SELECT conn_id, issue_no, push_due, snap FROM git_issue_links WHERE task_id=?", (tid,))
    return r[0] if r else None


def sync(s, cid, **b):
    return s.patch(B + f"/api/repos/{cid}", json=b)


GID = connect(A, P, "github", GH, "acme/app", GHTOK)
poll(GID)
r = A.post(B + f"/api/repos/{GID}/issues/import", json={})
check(r.ok and r.json()["created"]["tasks"] == 1, f"issue 1 imported (part B): {r.text[:200]}")
T1 = kt.dbx("SELECT task_id FROM git_issue_links WHERE conn_id=? AND issue_no=1", (GID,))[0][0]
check(task(T1).get("ltags") == ["bug"], f"the import's labels are project tags now: {task(T1).get('ltags')}")
check(json.loads(link(T1)[3]).get("title") == "Old issue", "the import stores the synced state")

# ---- the switches
check(sync(Bo, GID, issue_sync=True).status_code == 403, "a member without admin rights: 403")
check(sync(Ca, GID, issue_sync=True).status_code == 404, "a stranger: 404")
r = requests.patch(B + f"/api/repos/{GID}", json={"issue_sync": True}, timeout=60,
                   headers={"Authorization": "Bearer " + AGTOK, "X-Requested-With": "kalmido"})
check(r.status_code in (401, 403), f"an agent token: refused ({r.status_code})")
check(sync(A, GID, issue_sync="yes").status_code == 400 and sync(A, GID, issue_create=2).status_code == 400, "invalid values: 400")
check(not kt.dbx("SELECT issue_sync FROM git_conns WHERE id=?", (GID,))[0][0], "still off")
r = sync(A, GID, issue_sync=True)
st = r.json().get("issue_state") or {}
check(r.ok and r.json().get("issue_sync") is True and st.get("rw") == "write" and st.get("available") is True,
      f"switched on, the token may write: {r.status_code} {r.text[:300]}")
rl = A.get(B + f"/api/lists/{P}/repos").json()["repos"]
check(rl[0].get("issue_state", {}).get("rw") == "write", "the settings show the state")
check("issue_state" not in Bo.get(B + f"/api/lists/{P}/repos").json()["repos"][0], "a member who is no admin does not get it")

# ---- pull: a new issue -> a task in Backlog
cr = tick()


def new_issue(r):
    r["issues"].insert(0, gh_issue(2, "Fresh issue", body="Fresh text", labels=("ui", "p1"), comments=1, created=cr, updated=cr))
    r.setdefault("issue_comments", {})["2"] = [{"id": 701, "user": {"login": "octo"}, "body": "First!", "created_at": cr}]


edit(8090, "acme/app", new_issue)
poll(GID)
t2 = kt.dbx("SELECT task_id FROM git_issue_links WHERE conn_id=? AND issue_no=2", (GID,))
check(t2, "a new issue became a task with its link")
T2 = t2[0][0] if t2 else 0
x = task(T2) if T2 else {}
check(x.get("title") == "Fresh issue" and x.get("section_id") == BACKLOG and "Fresh text" in (x.get("content") or "")
      and "acme/app#2" in (x.get("content") or "") and x.get("url") == f"{GH}/acme/app/issues/2",
      f"title, section Backlog, text, reference, link: {[x.get(k) for k in ('title', 'section_id', 'content', 'url')]}")
check(sorted(x.get("ltags") or []) == ["p1", "ui"], f"labels -> project tags: {x.get('ltags')}")
check(any(c.startswith("@octo on ") and "First!" in c for c in comments(T2)), f"its comment: {comments(T2)}")
check(acts(T2, "created") and acts(T2, "created")[0]["data"].get("gsy") == "acme/app#2", "the history names the issue")

# ---- pull: changes of a linked issue
up = tick()


def changed_issue(r):
    next(i for i in r["issues"] if i["number"] == 1).update(title="Old issue v2", body="New text", state="closed", closed_at=up,
                                                           labels=[{"name": "bug"}, {"name": "p2"}], updated_at=up, comments=1)
    r.setdefault("issue_comments", {})["1"] = [{"id": 702, "user": {"login": "octo"}, "body": "Repo says hi", "created_at": up}]


edit(8090, "acme/app", changed_issue)
poll(GID)
x = task(T1)
check(x.get("title") == "Old issue v2" and x.get("status") == 2 and sorted(x.get("ltags") or []) == ["bug", "p2"],
      f"title, closed, labels taken: {[x.get(k) for k in ('title', 'status', 'ltags')]}")
check((x.get("content") or "").startswith("New text") and "acme/app#1" in (x.get("content") or ""), f"text taken, the reference stays: {x.get('content')!r}")
check(any("Repo says hi" in c for c in comments(T1)), "the new comment")
check(acts(T1, "complete") and acts(T1, "complete")[-1]["data"].get("gsy") == "acme/app#1", "history: completed by the issue")

# ---- push: collected, then one write; no echo
n0 = loglen()
assert Bo.patch(B + f"/api/tasks/{T1}", json={"title": "Local title", "ltags": ["bug", "p2", "here"]}).ok
assert Bo.post(B + f"/api/tasks/{T1}/reopen").ok
r = Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "Hello from Kalmido"})
check(r.ok, f"comment: {r.status_code}")
due = link(T1)[2]
now = datetime.now(timezone.utc).timestamp()
check(now + 15 < due < now + 45, f"collected: push_due about 30 s ahead ({due - now:.0f} s)")
check(not writes(n0), "nothing sent before it is due")
check(kt.dbx("SELECT COUNT(*) FROM git_issue_comments WHERE remote_id IS NULL")[0][0] == 1, "the comment waits to be sent")
edit(8090, "acme/app", lambda r: r.update(write_ts=tick()))
check(push(T1), "sent")
w = writes(n0)
pt = [x for x in w if x["method"] == "PATCH"]
check(len(pt) == 1 and pt[0]["path"].endswith("/repos/acme/app/issues/1") and pt[0]["body"].get("title") == "Local title"
      and pt[0]["body"].get("state") == "open" and sorted(pt[0]["body"].get("labels") or []) == ["bug", "here", "p2"] and "body" not in pt[0]["body"],
      f"one PATCH with title, state, labels (the text unchanged: not sent): {pt}")
pc = [x for x in w if x["method"] == "POST"]
check(len(pc) == 1 and pc[0]["path"].endswith("/issues/1/comments") and pc[0]["body"]["body"] == "Bob (Kalmido):\n\nHello from Kalmido",
      f"the comment with its author: {pc}")
check(all(x["auth"] == "Bearer " + GHTOK for x in w), "with the connection's token")
check(remote(8090, "acme/app", 1)["title"] == "Local title", "the issue has it")
na, nc = len(A.get(B + f"/api/tasks/{T1}/timeline").json()["activity"]), len(comments(T1))
n1 = loglen()
poll(GID)
check(len(A.get(B + f"/api/tasks/{T1}/timeline").json()["activity"]) == na and len(comments(T1)) == nc, "no echo: the next round changes nothing")
kt.dbx("UPDATE git_issue_links SET push_due=1 WHERE task_id=?", (T1,))
push(T1)
check(not writes(n1), "and sends nothing again")

# ---- conflict: the repository is newer
assert Bo.patch(B + f"/api/tasks/{T1}", json={"title": "Here A"}).ok
edit(8090, "acme/app", lambda r: next(i for i in r["issues"] if i["number"] == 1).update(title="Repo B", updated_at=tick()))
n2 = loglen()
poll(GID)
check(task(T1)["title"] == "Repo B", "the newer change (the repository's) wins")
lost = acts(T1, "git_sync_lost")
# 2.394.0 D (#3377 review 3): + both times (no issue events in the fake here: the issue's updated_at counts)
check(lost and {k: lost[-1]["data"].get(k) for k in ("field", "value", "side", "gsy")} == {"field": "title", "value": "Here A", "side": "here", "gsy": "acme/app#1"}
      and lost[-1]["data"].get("at_here") and lost[-1]["data"].get("at_repo") and lost[-1]["data"].get("repo_by") == "issue", f"the version here is in the history: {lost}")
push(T1)
check(not [x for x in writes(n2) if x["method"] == "PATCH"], "nothing to send afterwards")

# ---- conflict: the change here is newer (the issue was changed earlier, read when sending)
edit(8090, "acme/app", lambda r: next(i for i in r["issues"] if i["number"] == 1).update(title="Repo C", updated_at="2026-01-01T00:00:00Z"))
assert Bo.patch(B + f"/api/tasks/{T1}", json={"title": "Here D"}).ok
n3 = loglen()
push(T1)
pt = [x for x in writes(n3) if x["method"] == "PATCH"]
check(task(T1)["title"] == "Here D" and pt and pt[0]["body"].get("title") == "Here D", f"the change here wins and goes out: {pt}")
lost = acts(T1, "git_sync_lost")
check(lost and lost[-1]["data"].get("value") == "Repo C" and lost[-1]["data"].get("side") == "repo", f"the repository's version is in the history: {lost[-1:]}")

# ---- never sent: a locked note, personal tags
kt.dbx("INSERT INTO task_note_locks(task_id, user_id, body, updated_at) VALUES(?, 1, '{}', '2026-10-01T00:00:00Z')", (T2,))
kt.dbx("UPDATE tasks SET content='' WHERE id=?", (T2,))
assert A.patch(B + f"/api/tasks/{T2}", json={"title": "Fresh renamed", "tags": ["secret"]}).ok
n4 = loglen()
push(T2)
pt = [x for x in writes(n4) if x["method"] == "PATCH"]
check(pt and pt[0]["body"].get("title") == "Fresh renamed" and "body" not in pt[0]["body"] and "secret" not in (pt[0]["body"].get("labels") or []),
      f"title out; the locked note and personal tags never: {pt}")
check(remote(8090, "acme/app", 2)["body"] == "Fresh text", "the issue keeps its text")

# ---- "create new tasks as issues"
check(sync(A, GID, issue_create=True).json().get("issue_create") is True, "issue_create on")
r = Bo.post(B + "/api/tasks", json={"list_id": P, "title": "Made here", "content": "Some notes"})
T3 = r.json()["id"]
sub = Bo.post(B + "/api/tasks", json={"list_id": P, "title": "A subtask", "parent_id": T3}).json()["id"]
check(link(T3) and link(T3)[1] == -T3 and not link(sub), "a new main task is queued, a subtask never")
n5 = loglen()
push(T3)
pc = [x for x in writes(n5) if x["method"] == "POST"]
check(pc and pc[0]["path"].endswith("/repos/acme/app/issues") and pc[0]["body"] == {"title": "Made here", "body": "Some notes", "labels": []},
      f"POST issues: {pc}")
L3 = link(T3)
x = task(T3)
check(L3 and L3[1] > 2 and x.get("url", "").endswith(f"/acme/app/issues/{L3[1]}") and f"acme/app#{L3[1]}" in x.get("content", ""),
      f"the link has its number, the task its address + reference: {L3} {x.get('url')} {x.get('content')!r}")
check(sync(A, GID, issue_create=False).json().get("issue_create") is False, "issue_create off again")

# ---- a deleted / moved task: the link goes, never a task again
assert A.delete(B + f"/api/tasks/{T3}").ok
check(not link(T3) and kt.dbx("SELECT 1 FROM git_issue_gone WHERE conn_id=? AND issue_no=?", (GID, L3[1])), "deleted: unlinked, remembered")
P2 = A.post(B + "/api/lists", json={"name": "Other", "kind": "project"}).json()["id"]
assert A.patch(B + f"/api/tasks/{T2}", json={"list_id": P2}).ok
check(not link(T2), "moved to another project: unlinked")
edit(8090, "acme/app", lambda r: [i.update(title=i["title"] + " again", updated_at=tick()) for i in r["issues"] if i["number"] in (2, L3[1])])
nt = kt.dbx("SELECT COUNT(*) FROM tasks WHERE list_id=?", (P,))[0][0]
poll(GID)
check(kt.dbx("SELECT COUNT(*) FROM tasks WHERE list_id=?", (P,))[0][0] == nt and task(T2)["title"] == "Fresh renamed", "their issues never become tasks again")

# ---- "#<task id>" in a merged pull request completes nothing while the sync is on
def merged_pr(no, tid, repo):
    return lambda r: r.update(pulls=[{"number": no, "title": f"fixes #{tid}", "body": "", "state": "closed", "merged_at": tick(),
                                      "user": {"login": "dev"}, "html_url": f"{GH}/{repo}/pull/{no}", "updated_at": tick(),
                                      "head": {"ref": "x", "sha": f"abc{no}"}, "merge_commit_sha": f"abc{no}"}])


T4 = Bo.post(B + "/api/tasks", json={"list_id": P, "title": "Must stay open"}).json()["id"]
edit(8090, "acme/app", merged_pr(77, T4, "acme/app"))
n8 = loglen()
poll(GID)
check(any(x["path"].startswith("/api/v3/repos/acme/app/pulls") and x["status"] == 200 for x in log_from(n8)) and task(T4)["status"] == 0,
      "fixes #<task id> in a merged pull request: the task stays open (#<n> there is an issue number)")

# ---- a token without write access: read only
RO = connect(A, P, "github", GH, "acme/ro", GHTOK)
r = A.post(B + f"/api/repos/{RO}/issues/import", json={})
TR = kt.dbx("SELECT task_id FROM git_issue_links WHERE conn_id=?", (RO,))[0][0]
r = sync(A, RO, issue_sync=True)
st = r.json().get("issue_state") or {}
check(r.ok and st.get("rw") == "read" and "cannot write issues" in st.get("error", ""), f"read only, with the reason: {st}")
n6 = loglen()
assert Bo.patch(B + f"/api/tasks/{TR}", json={"title": "Not going out"}).ok
check(link(TR)[2] == 0, "read only: nothing is queued")
edit(8090, "acme/ro", lambda r: r["issues"][0].update(state="closed", updated_at=tick()))
poll(RO)
check(task(TR)["status"] == 2 and not writes(n6), "it still reads (closed in the repository -> done), writes nothing")
edit(8090, "acme/app", lambda r: r.update(write_denied=True))
assert Bo.patch(B + f"/api/tasks/{T1}", json={"title": "Refused"}).ok
push(T1)
st = A.get(B + f"/api/lists/{P}/repos").json()["repos"][0]["issue_state"]
check(st.get("rw") == "read" and "cannot write" in st.get("error", ""), f"a write refused later: read only from then on: {st}")
edit(8090, "acme/app", lambda r: r.pop("write_denied"))

# ---- an end-to-end encrypted project: the switch is locked
P3 = A.post(B + "/api/lists", json={"name": "Locked", "kind": "project"}).json()["id"]
EC = connect(A, P3, "github", GH, "acme/e2e", GHTOK)
kt.dbx("UPDATE lists SET e2e='on' WHERE id=?", (P3,))
r = sync(A, EC, issue_sync=True)
check(r.status_code == 409 and "end-to-end" in r.json().get("error", ""), f"locked: 409 {r.text[:200]}")
st = A.get(B + f"/api/lists/{P3}/repos").json()["repos"][0].get("issue_state") or {}
check(st.get("available") is False and st.get("block") == "e2e", f"the settings say why: {st}")

# ---- GitLab
GLC = connect(A, P, "gitlab", GL, "grp/app", GLTOK)
assert A.post(B + f"/api/repos/{GLC}/issues/import", json={}).ok
TG = kt.dbx("SELECT task_id FROM git_issue_links WHERE conn_id=? AND issue_no=1", (GLC,))[0][0]
r = sync(A, GLC, issue_sync=True)
check(r.ok and (r.json().get("issue_state") or {}).get("rw") == "write", f"GitLab: on, Developer may write: {r.text[:200]}")
edit(8092, "grp/app", lambda r: r["issues"][0].update(title="GL renamed", state="closed", labels=["feature", "x"], updated_at=tick()))
poll(GLC)
x = task(TG)
check(x["title"] == "GL renamed" and x["status"] == 2 and sorted(x.get("ltags") or []) == ["feature", "x"], f"GitLab pulled: {[x['title'], x['status'], x.get('ltags')]}")
n7 = loglen()
assert Bo.post(B + f"/api/tasks/{TG}/reopen").ok
assert Bo.patch(B + f"/api/tasks/{TG}", json={"ltags": ["feature", "y"]}).ok
assert Bo.post(B + f"/api/tasks/{TG}/comments", json={"body": "GL from here"}).ok
push(TG)
w = writes(n7, 8092)
pu = [x for x in w if x["method"] == "PUT"]
check(pu and pu[0]["body"].get("state_event") == "reopen" and pu[0]["body"].get("labels") == "feature,y" and pu[0]["ptok"] == GLTOK,
      f"GitLab: PUT with state_event and labels as a list of names: {pu}")
check([x for x in w if x["method"] == "POST" and x["path"].endswith("/issues/1/notes")], "GitLab: the comment as a note")

# ---- a person without an organisation
FID, F = freelancer(B, A, "frida")
F.__class__ = S
FP = F.post(B + "/api/lists", json={"name": "Site", "kind": "project"}).json()["id"]
FC = connect(F, FP, "github", GH, "frida/site", FTOK)
r = sync(F, FC, issue_sync=True)
check(r.ok and r.json().get("issue_sync") is True, f"freelancer: the sync on in the own project: {r.text[:200]}")
cr = tick()
edit(8090, "frida/site", lambda r: r["issues"].append(gh_issue(3, "Contact form", created=cr, updated=cr, repo="frida/site")))
poll(FC)
check(kt.dbx("SELECT COUNT(*) FROM git_issue_links l JOIN tasks t ON t.id=l.task_id WHERE l.conn_id=? AND t.list_id=?", (FC, FP))[0][0] == 1,
      "freelancer: the new issue is a task of the own project")
check(sync(A, FC, issue_sync=False).status_code == 404, "someone else's project: 404 (also for the instance admin)")

# ---- review of part B: dates, clean texts, nothing twice while an import runs, the real number in the warning
RV = connect(A, P2, "github", GH, "acme/rev", GHTOK)
poll(RV)


def slow(v):
    st = json.load(open(GJ))
    st.pop("slow", None)
    st.update({"slow": v} if v else {})
    with open(GJ + ".tmp", "w") as f:
        json.dump(st, f)
    os.replace(GJ + ".tmp", GJ)


slow(1.5)
res, nr = {}, loglen()
th = threading.Thread(target=lambda: res.update(r=A.post(B + f"/api/repos/{RV}/issues/import", json={})))
th.start()
until(lambda: any("/repos/acme/rev/issues?" in x["path"] for x in log_from(nr)), 30)  # the listing is read: the comments come next
dummy = kt.dbx("INSERT INTO tasks(list_id, title, created_at, updated_at) VALUES(?, 'linked meanwhile', '2026-10-01T00:00:00Z', "
               "'2026-10-01T00:00:00Z') RETURNING id", (P2,))[0][0]
kt.dbx("INSERT INTO git_issue_links(conn_id, issue_no, task_id, created_at) VALUES(?, 2, ?, '2026-10-01T00:00:00Z')", (RV, dummy))
th.join(120)
slow(0)
j = res["r"].json() if res.get("r") is not None else {}
check(j.get("created", {}).get("tasks") == 1 and j.get("already") == 1, f"an issue linked meanwhile is not taken twice: {str(j)[:300]}")
TV = kt.dbx("SELECT task_id FROM git_issue_links WHERE conn_id=? AND issue_no=1", (RV,))
cm = kt.dbx("SELECT c.body, c.created_at, t.created_at FROM comments c JOIN tasks t ON t.id=c.task_id WHERE c.task_id=?", (TV[0][0] if TV else 0,))
check(cm and cm[0][1][:19] == cm[0][2][:19] and cm[0][1].startswith("2026-08-01"), f"a comment without a date keeps the task's time: {cm}")
check(cm and "‮" not in cm[0][0] and "​" not in cm[0][0] and "Bidi text here" in cm[0][0] and cm[0][0].startswith("@eve on"),
      f"control / bidi characters out: {cm and cm[0][0]!r}")
# the counter-check of "#<task id>": a connection without the sync still completes by it
edit(8090, "acme/rev", merged_pr(78, dummy, "acme/rev"))
poll(RV)
check(kt.dbx("SELECT status FROM tasks WHERE id=?", (dummy,))[0][0] == 2, "without the sync, fixes #<task id> completes the task (counter-check)")
RP = connect(A, P2, "github", GH, "acme/prs", GHTOK)
r = A.post(B + f"/api/repos/{RP}/issues/import", json={"dry_run": True})
w = [x for x in r.json().get("warnings", []) if x["text"].startswith("Only the newest")]
check(r.ok and r.json()["created"]["tasks"] == 5 and w and w[0]["text"] == "Only the newest 5 issues were imported", f"the warning names 5: {w}")

# ---- 2.394.0 D (#3377): review of C
kt.dbx("UPDATE git_conns SET issue_rw=1, issue_error='' WHERE id=?", (GID,))  # the "refused later" above made it read only
STARTF = os.path.join(DATA, "git.start")


def top(**kv):
    """Sets (None: removes) top-level keys of git.json."""
    st = json.load(open(GJ))
    for k, v in kv.items():
        st.pop(k, None) if v is None else st.update({k: v})
    with open(GJ + ".tmp", "w") as f:
        json.dump(st, f)
    os.replace(GJ + ".tmp", GJ)


def due_at(tid, v):
    """push_due = v; waits until the loop took it (another value: sent = 0, failed = later)."""
    kt.dbx("UPDATE git_issue_links SET push_due=? WHERE task_id=?", (v, tid))
    return until(lambda: (link(tid) or (0, 0, v))[2] != v, 30)


# review 1: a new issue whose closing fails -> its number is stored, the next try closes it, never a second issue
check(sync(A, GID, issue_create=True).json().get("issue_create") is True, "D: issue_create on")
T5 = Bo.post(B + "/api/tasks", json={"list_id": P, "title": "Made closed"}).json()["id"]
assert Bo.post(B + f"/api/tasks/{T5}/complete").ok
edit(8090, "acme/app", lambda r: r.update(write_fail={"skip": 1, "times": 1, "status": 422}))
n9 = loglen()
due_at(T5, 1)
L5 = link(T5)
check(L5 and L5[1] > 0 and L5[2] > 1000, f"D1: the POST worked, the close failed: the issue number is kept, tried again later: {L5}")
push(T5)
posts = [x for x in writes(n9) if x["method"] == "POST" and x["path"].endswith("/repos/acme/app/issues")]
check(len(posts) == 1 and L5 and remote(8090, "acme/app", link(T5)[1])["state"] == "closed",
      f"D1: one issue only, closed with the next try: {len(posts)} POST")
check(sync(A, GID, issue_create=False).json().get("issue_create") is False, "D: issue_create off again")
# review 1: comment A sent, B failed -> the next try sends B only (what is still collected for T1 goes out first)
due_at(T1, 1)
edit(8090, "acme/app", lambda r: r.update(write_fail={"skip": 1, "times": 1, "status": 500}))
n10 = loglen()
assert Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "D one"}).ok
assert Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "D two"}).ok
due_at(T1, 1)
push(T1)
sent = [x["body"]["body"] for x in writes(n10) if x["method"] == "POST" and x["status"] == 201]
check(sent.count("Bob (Kalmido):\n\nD one") == 1 and sent.count("Bob (Kalmido):\n\nD two") == 1, f"D1: each comment exactly once: {sent}")
check(not [x for x in writes(n10) if x["method"] == "PATCH"], "D1: (only the comments were sent)")

# review 2: a change noted while a send runs stays due (the write is slowed down, the change comes during it)
open(STARTF, "w").close()
top(slow_write=3)
assert Bo.patch(B + f"/api/tasks/{T1}", json={"title": "Race A"}).ok
kt.dbx("UPDATE git_issue_links SET push_due=1 WHERE task_id=?", (T1,))
until(lambda: any(x.startswith("PATCH ") and x.rstrip().endswith("/repos/acme/app/issues/1") for x in open(STARTF)), 30)
tags = sorted(set((task(T1).get("ltags") or []) + ["race"]))
assert Bo.patch(B + f"/api/tasks/{T1}", json={"ltags": tags}).ok
until(lambda: link(T1)[2] != 1, 30)
top(slow_write=None)
dl = json.loads(kt.dbx("SELECT dirty FROM git_issue_links WHERE task_id=?", (T1,))[0][0] or "{}")
check(link(T1)[2] > 0 and "labels" in dl, f"D2: the change noted meanwhile stays due: push_due {link(T1)[2]}, dirty {dl}")
push(T1)
check("race" in [x["name"] for x in remote(8090, "acme/app", 1)["labels"]] and remote(8090, "acme/app", 1)["title"] == "Race A",
      "D2: and goes out with the next send")

# review 3 + 5: the field's own time decides; logged once although the comments hit the rate limit
assert Bo.patch(B + f"/api/tasks/{T1}", json={"title": "Here E"}).ok
up = tick()


def renamed_long_ago(r):
    i = next(i for i in r["issues"] if i["number"] == 1)
    i.update(title="Repo F", updated_at=up, comments=(i.get("comments") or 0) + 1)
    r.setdefault("issue_comments", {}).setdefault("1", []).append({"id": 801, "user": {"login": "octo"}, "body": "Late comment", "created_at": up})
    r.update(events={"1": [{"event": "renamed", "created_at": "2026-01-02T00:00:00Z"}, {"event": "commented", "created_at": up}]},
             comments_rate=True)


edit(8090, "acme/app", renamed_long_ago)
n11 = loglen()
poll(GID)
lost = [a for a in acts(T1, "git_sync_lost") if a["data"].get("value") == "Repo F"]
check(task(T1)["title"] == "Here E" and len(lost) == 1 and lost[0]["data"].get("side") == "repo" and lost[0]["data"].get("repo_by") == "field"
      and lost[0]["data"].get("at_repo", "").startswith("2026-01-02"),
      f"D3: renamed long ago, only a later comment made the issue newer: the change here wins: {task(T1)['title']} {lost}")
check(len([x for x in log_from(n11) if "/repos/acme/app/issues/1/events" in x["path"]]) == 1, "D3: one extra request for the field times")
edit(8090, "acme/app", lambda r: r.pop("comments_rate"))
poll(GID)
lost = [a for a in acts(T1, "git_sync_lost") if a["data"].get("value") == "Repo F"]
check(any("Late comment" in c for c in comments(T1)) and len(lost) == 1, f"D5: the comment came with the next round, the conflict is logged once: {len(lost)}")
push(T1)
check(remote(8090, "acme/app", 1)["title"] == "Here E", "D3: the winner goes out")

# review 4: a long title goes out cut; a link is given up after 5 equal errors
long_t = "L" * 300
assert Bo.patch(B + f"/api/tasks/{T1}", json={"title": long_t}).ok
n12 = loglen()
check(push(T1), "D4: a 300 character title is sent (not refused again and again)")
pt = [x for x in writes(n12) if x["method"] == "PATCH"]
check(pt and len(pt[0]["body"].get("title", "")) == 255 and pt[0]["status"] == 200 and remote(8090, "acme/app", 1)["title"] == "L" * 255,
      f"D4: cut to 255: {[(len(x['body'].get('title', '')), x['status']) for x in pt]}")
poll(GID)
check(task(T1)["title"] == long_t, "D4: the cut title in the repository does not come back")
edit(8090, "acme/app", lambda r: r.update(write_fail={"skip": 0, "times": 5, "status": 422}))
assert Bo.patch(B + f"/api/tasks/{T1}", json={"title": "Given up"}).ok
n13 = loglen()
for i in range(1, 6):
    due_at(T1, 1)
f = acts(T1, "git_sync_fail")
check(link(T1)[2] == 0 and f and f[-1]["data"].get("error") == "http:422" and f[-1]["data"].get("gsy") == "acme/app#1",
      f"D4: after 5 equal errors given up, in the history: push_due {link(T1)[2]} {f[-1:]}")
check(len([x for x in writes(n13) if x["status"] == 422]) == 5, "D4: exactly 5 tries")
st = A.get(B + f"/api/lists/{P}/repos").json()["repos"][0]["issue_state"]
check("422" in st.get("error", ""), f"D4: the settings show the error: {st.get('error')}")
edit(8090, "acme/app", lambda r: r.pop("write_fail"))

# review 6 + 8: GitHub triage is no write access; a new token sent with the switch is the one checked
TOK_TRI, TOK_RW = "ghp_acmeTriageOnly0011", "ghp_acmeTriageNowRw0012"
st = json.load(open(GJ))
st["8090"]["acme/tok"] = {"default_branch": "main", "issues": [], "perm_by_token": {
    TOK_TRI: {"admin": False, "maintain": False, "push": False, "triage": True, "pull": True}, TOK_RW: {"push": True, "pull": True}}}
with open(GJ + ".tmp", "w") as fh:
    json.dump(st, fh)
os.replace(GJ + ".tmp", GJ)
TK = connect(A, P2, "github", GH, "acme/tok", TOK_TRI)
r = sync(A, TK, issue_sync=True)
check(r.ok and (r.json().get("issue_state") or {}).get("rw") == "read", f"D8: triage only: read only: {r.text[:200]}")
check(sync(A, TK, issue_sync=False).ok, "D8: off")
r = sync(A, TK, token=TOK_RW, issue_sync=True)
check(r.ok and (r.json().get("issue_state") or {}).get("rw") == "write", f"D6: the new token is checked: {r.text[:200]}")

# ---- 2.506.1 (CI red of 2.506.0, signin_ui): a restore while the git loop runs every second. The loop read git_conns / lists
# and then waited at the gate for the restore with that read still open; pg_restore --clean waited for its locks and the
# server stayed in maintenance (503) for good. Two rounds: the loop meets the restore's window in each (tick 1 s).
def manual():
    return [x for x in A.get(B + "/api/admin/backups").json().get("items", []) if x["kind"] == "manual"]


for rnd in (1, 2):
    n0 = len(manual())
    r = A.post(B + "/api/admin/backups")
    check(r.status_code == 202, f"restore {rnd}: back up now {r.text[:100]}")
    # the backup of this round is written and nothing runs any more (else the restore answers "busy")
    bk = until(lambda: len(manual()) > n0 and not A.get(B + "/api/admin/backups").json().get("running") and manual(), 30) or [{"name": ""}]
    try:
        r = A.post(B + "/api/admin/backups/restore", json={"password": "password123", "confirm": "RESTORE", "name": bk[0]["name"]}, timeout=120)
        ok = r.ok and r.json().get("ok")
    except requests.RequestException as e:
        r, ok = None, False
        print("restore", rnd, type(e).__name__)
    check(ok, f"restore {rnd}: done while the git loop runs (no wait on its locks): {r.text[:200] if r is not None else 'no answer in 120 s'}")
    check(until(lambda: A.get(B + "/api/state").status_code == 200, 20), f"restore {rnd}: the server answers again (no 503)")

# ---- no token anywhere
check(not any(t in x for x in SEEN for t in (GHTOK, GLTOK, FTOK, TOK_TRI, TOK_RW)), "no access token in any answer")
log = subprocess.run(["docker", "logs", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
check(all(t not in log for t in (GHTOK, GLTOK, FTOK, TOK_TRI, TOK_RW)), "no access token in the server's log")
check("git loop error" not in log and "Traceback" not in log, "no error in the git loop")

sys.exit(done("p2394_c_git_sync"))
