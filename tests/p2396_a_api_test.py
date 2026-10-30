#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.396.0 A (#3386): the git author for AI commits, own container (start.sh). Invented people and addresses only.
freelancer-matrix: tasks
 - the agent's runtime: git_author_name / git_author_email / git_coauthor (defaults '' / '' / false), the derived git_author
   "Name <mail>" always filled in (Kalmido / noreply@kalmido.com per empty part); an invalid mail, a name with <, > or a
   line break, a too long name, a non-bool git_coauthor: 400 and nothing stored; runtime_changed carries it
 - the project level: PATCH /api/repos/{id} {author_name, author_email} (owner / list admins; never an agent, a stranger
   404), GET /api/lists/{id}/repos + the state's repos carry it; a task's repo.git_author / git_coauthor / git_author_source
   in GET /api/v1/tasks/{id} and in the agent's task event (assigned): project override per part, else the agent's value
 - tenant boundary: an agent the project is not shared with sees neither the task nor the repository (404)
 - a person without an organisation: her personal agent's git author (PATCH /api/my/agents/{id}) and her own project
 - the reference launcher agent_launcher.sh (and .ps1 with pwsh): --once sets GIT_AUTHOR_* / GIT_COMMITTER_* from
   runtime.git_author and KALMIDO_GIT_COAUTHOR, nothing without git_author (an older server)
usage: p2396_a_api_test.py <datadir>"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402
from kt import check, B, H, DATA, done, nostart  # noqa: E402

V = B + "/api/v1"
MCP = os.path.join(N, "..", "mcp")
DEFAULT = "Kalmido <noreply@kalmido.com>"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


if not nostart("P2396A"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123",
                                   "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = login(B, "bob")
for s in (A, Bo):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"}).ok
FID, Fr = freelancer(B, A)  # freelancer-matrix: tasks
CUR = {}


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": name, "display_name": name.title()})
    assert r.ok, r.text
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


def events(hdr, key):
    r = requests.get(V + f"/agent/events?since={CUR.get(key, 0)}", headers=hdr)
    assert r.ok, r.text
    CUR[key] = r.json()["cursor"]
    return r.json()["data"]


def runtime(hdr):
    r = requests.get(V + "/agent", headers=hdr)
    assert r.ok, r.text
    return r.json()["runtime"]


def git_conn(lid, repo, by):
    """A repository row straight into the database (never polled; the API would ask the provider)."""
    return dbx("INSERT INTO git_conns(list_id, provider, base_url, owner, repo, next_at, created_by, created_at) "
               "VALUES(?, 'gitea', 'http://127.0.0.1:9', 'acme', ?, 9e12, ?, '2026-10-01T00:00:00Z') RETURNING id",
               (lid, repo, by), write=True)[0][0]


CL, CLH = agent("claude")
CX, CXH = agent("codex")
events(CLH, "cl")

# ================================================================ the agent's runtime
rt = runtime(CLH)
check(rt.get("git_author") == DEFAULT and rt.get("git_author_name") == "" and rt.get("git_author_email") == ""
      and rt.get("git_coauthor") is False, f"default: {DEFAULT}, no co-author line {rt}")
for bad, what in (({"git_author_email": "not-a-mail"}, "an invalid mail"), ({"git_author_email": "a b@example.com"}, "a mail with a space"),
                  ({"git_author_email": "Bot <bot@example.com>"}, "a mail with <>"), ({"git_author_name": "Bot <x>"}, "a name with <>"),
                  ({"git_author_name": "Bot\nCo-Authored-By: x"}, "a name with a line break"), ({"git_author_name": "Bot\x1b[31m"}, "a name with a control character (review 2.396)"), ({"git_author_name": "x" * 101}, "a name of 101"),
                  ({"git_coauthor": "yes"}, "git_coauthor not a bool"), ({"git_author_email": 5}, "a mail not a string")):
    r = A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": bad})
    check(r.status_code == 400, f"{what}: 400 ({r.status_code} {r.text[:100]})")
r = A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"git_author_email": "nope"}})
check("valid email" in r.text, f"the invalid mail says so: {r.text[:120]}")
check(runtime(CLH)["git_author"] == DEFAULT, "nothing stored after the refused values")
r = A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"git_author_name": "Acme Bot"}})
check(r.ok and runtime(CLH)["git_author"] == "Acme Bot <noreply@kalmido.com>", f"only the name: the default mail {r.text[:120]}")
r = A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"git_author_email": " bot@example.com ", "git_coauthor": True}})
rt = runtime(CLH)
check(r.ok and rt["git_author"] == "Acme Bot <bot@example.com>" and rt["git_author_email"] == "bot@example.com"
      and rt["git_coauthor"] is True, f"name + mail (trimmed) + co-author: {rt}")
check(rt.get("rotate_size") == "medium" and rt.get("model") == "", "the other runtime keys stay as they were")
ev = [e for e in events(CLH, "cl") if e["event"] == "runtime_changed"]
check(ev and ev[-1]["data"]["runtime"].get("git_author") == "Acme Bot <bot@example.com>"
      and ev[-1]["data"]["runtime"].get("git_coauthor") is True, f"runtime_changed carries git_author {str(ev[-1:])[:200]}")
ag = next((x for x in A.get(B + "/api/admin/agents").json().get("agents", []) if x["id"] == CL), None)
check(ag and ag["runtime"].get("git_author_name") == "Acme Bot", "the admin's agent list carries it (the dialog's values)")
check(Bo.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"git_author_name": "Mallory"}}).status_code in (403, 404),
      "a member cannot change it")
check(requests.patch(V + "/agent", headers=CLH, json={"runtime": {"git_author_name": "Self"}}).status_code in (400, 403, 404, 405),
      "the agent cannot change its own git author")
check(runtime(CLH)["git_author_name"] == "Acme Bot", "... still Acme Bot")
check(runtime(CXH)["git_author"] == DEFAULT, "another agent keeps the default")

# ================================================================ the project level
P = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
check(A.put(B + f"/api/lists/{P}/members", json={"user_id": CL, "role": "edit"}).ok, "setup: App shared with claude")
check(A.put(B + f"/api/lists/{P}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: App shared with bob (no admin)")
CID = git_conn(P, "app", 1)
T = A.post(B + "/api/tasks", json={"title": "Fix the login", "list_id": P}).json()["id"]


def repo_of(hdr):
    r = requests.get(V + f"/tasks/{T}", headers=hdr)
    return r.status_code, (r.json().get("repo") or {}) if r.ok else {}


code, rp = repo_of(CLH)
check(code == 200 and rp.get("git_author") == "Acme Bot <bot@example.com>" and rp.get("git_author_source") == "agent"
      and rp.get("git_coauthor") is True, f"no override: the agent's own author in repo {code} {rp.get('git_author')} {rp.get('git_author_source')}")
r = A.get(B + f"/api/lists/{P}/repos")
check(r.ok and r.json()["repos"][0].get("author_name") == "" and r.json()["repos"][0].get("author_email") == "", "the repository: no override yet")
r = A.patch(B + f"/api/repos/{CID}", json={"author_name": "App Bot", "author_email": "not a mail"})
check(r.status_code == 400 and "valid email" in r.text, f"an invalid mail at the repository: 400 {r.status_code} {r.text[:100]}")
check(dbx("SELECT author_name, author_email FROM git_conns WHERE id=?", (CID,)) == [("", "")], "... nothing stored")
check(A.patch(B + f"/api/repos/{CID}", json={"author_name": "App <Bot>"}).status_code == 400, "a name with <>: 400")
check(Bo.patch(B + f"/api/repos/{CID}", json={"author_name": "Bob Bot"}).status_code == 403, "a member who does not manage the project: 403")
check(requests.patch(B + f"/api/repos/{CID}", headers=CLH, json={"author_name": "Self"}).status_code in (401, 403, 404),
      "the agent cannot set the project's author")
check(Fr.patch(B + f"/api/repos/{CID}", json={"author_name": "Frida"}).status_code == 404, "a stranger: 404")
r = A.patch(B + f"/api/repos/{CID}", json={"author_email": "app@example.com"})
check(r.ok and r.json().get("author_email") == "app@example.com" and r.json().get("author_name") == "", f"only the mail {r.text[:160]}")
code, rp = repo_of(CLH)
check(rp.get("git_author") == "Acme Bot <app@example.com>" and rp.get("git_author_source") == "project",
      f"the project's mail, the agent's name: {rp.get('git_author')} {rp.get('git_author_source')}")
r = A.patch(B + f"/api/repos/{CID}", json={"author_name": "App Bot"})
check(r.ok and r.json().get("author_email") == "app@example.com", "the name alone keeps the mail")
code, rp = repo_of(CLH)
check(rp.get("git_author") == "App Bot <app@example.com>", f"the project's author wins: {rp.get('git_author')}")
r = A.get(B + f"/api/lists/{P}/repos")
check(r.ok and r.json()["repos"][0].get("author_name") == "App Bot", "GET /api/lists/{id}/repos carries the override")
lst = next(x for x in Bo.get(B + "/api/state").json()["lists"] if x["id"] == P)
check(lst["repos"] and lst["repos"][0].get("author_email") == "app@example.com", f"the state's repos carry it {lst.get('repos')}")
# the assigned event goes to the agent from alice's request: the author is the agent's, not the caller's
events(CLH, "cl")
check(A.patch(B + f"/api/tasks/{T}", json={"assignee_id": CL}).ok, "setup: claude assigned")
ev = [e for e in events(CLH, "cl") if e["event"] == "assigned"]
check(ev and (ev[-1]["data"].get("repo") or {}).get("git_author") == "App Bot <app@example.com>"
      and ev[-1]["data"]["repo"].get("git_coauthor") is True and ev[-1]["data"]["repo"].get("git_author_source") == "project",
      f"the assigned event carries the project's author + the agent's co-author flag {str(ev[-1:])[:300]}")
check(A.patch(B + f"/api/repos/{CID}", json={"author_name": "", "author_email": ""}).ok, "the override emptied")
code, rp = repo_of(CLH)
check(rp.get("git_author") == "Acme Bot <bot@example.com>" and rp.get("git_author_source") == "agent", "empty again: the agent's own")
check(A.patch(B + f"/api/repos/{CID}", json={"author_name": "App Bot", "author_email": "app@example.com"}).ok, "setup: override again")

# ================================================================ tenant boundary
code, rp = repo_of(CXH)
check(code == 404 and not rp, f"an agent the project is not shared with: no task, no author ({code})")
r = requests.get(V + f"/lists/{P}/repos", headers=CXH)
check(r.status_code in (403, 404) and "App Bot" not in r.text, f"... nor its repositories ({r.status_code})")
check("app@example.com" not in requests.get(V + "/agent", headers=CXH).text, "... nor in its own GET /agent")
lst = [x for x in Fr.get(B + "/api/state").json()["lists"] if x["id"] == P]
check(not lst, "a person outside the project does not see the list")

# ================================================================ a person without an organisation
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2}).ok
ag = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]}).json()
check("id" in ag, f"setup: frida's personal agent {str(ag)[:120]}")
FA, FAH = ag["id"], {"Authorization": "Bearer " + ag["token"]}
check(runtime(FAH)["git_author"] == DEFAULT, "frida's agent: the default")
r = Fr.patch(B + f"/api/my/agents/{FA}", json={"runtime": {"git_author_email": "frida@"}})
check(r.status_code == 400, f"frida: an invalid mail 400 ({r.status_code})")
r = Fr.patch(B + f"/api/my/agents/{FA}", json={"runtime": {"git_author_name": "Frida's Bot", "git_author_email": "bot@frida.example.com"}})
check(r.ok and runtime(FAH)["git_author"] == "Frida's Bot <bot@frida.example.com>", f"frida sets her agent's author {r.text[:120]}")
check(A.patch(B + f"/api/my/agents/{FA}", json={"runtime": {"git_author_name": "Alice"}}).status_code in (403, 404),
      "another person cannot change it through /api/my/agents")
FP = Fr.post(B + "/api/lists", json={"name": "Frida's app", "kind": "project"}).json()["id"]
check(Fr.put(B + f"/api/lists/{FP}/members", json={"user_id": FA, "role": "edit"}).ok, "setup: frida shares her project with her agent")
FC = git_conn(FP, "frida-app", FID)
FT = Fr.post(B + "/api/tasks", json={"title": "Her task", "list_id": FP}).json()["id"]
r = requests.get(V + f"/tasks/{FT}", headers=FAH)
check(r.ok and r.json()["repo"]["git_author"] == "Frida's Bot <bot@frida.example.com>", f"frida's task: her agent's author {r.text[:160]}")
check(Fr.patch(B + f"/api/repos/{FC}", json={"author_name": "Studio", "author_email": "studio@example.com"}).ok, "frida sets her project's author")
r = requests.get(V + f"/tasks/{FT}", headers=FAH)
check(r.ok and r.json()["repo"]["git_author"] == "Studio <studio@example.com>", "... and her agent gets it")
check(A.patch(B + f"/api/repos/{FC}", json={"author_name": "Alice"}).status_code in (403, 404) or
      dbx("SELECT author_name FROM git_conns WHERE id=?", (FC,)) == [("Studio",)], "the instance admin does not rewrite it unseen")
check(requests.get(V + f"/tasks/{FT}", headers=CLH).status_code == 404, "claude does not see frida's task")

# ================================================================ the reference launchers (stub API, no container)
TOKEN = "abk_secret_test_token_2396"
STUB = {"runtime": {"reset_seq": 0, "timezone": "UTC", "git_author": "Acme Bot <bot@example.com>", "git_coauthor": True}}


class Hd(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"id": 9, "enabled": True, "runtime": STUB["runtime"]}).encode()
        self.send_response(200 if self.path == "/api/v1/agent" else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Hd)
threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = tempfile.mkdtemp(prefix="kalmido-p2396a-")
envf = os.path.join(tmp, "agent.env")
with open(envf, "w") as f:
    f.write(f"KALMIDO_URL=http://127.0.0.1:{srv.server_address[1]}\nKALMIDO_TOKEN={TOKEN}\n")
launchers = [("sh", ["bash", os.path.join(MCP, "agent_launcher.sh")])]
PWSH = os.environ.get("PWSH") or shutil.which("pwsh")
if PWSH:
    launchers.append(("ps1", [PWSH, "-NoProfile", "-NonInteractive", "-File", os.path.join(MCP, "agent_launcher.ps1")]))
else:
    print("p2396_a: ps1 part SKIP (no pwsh)")
for name, cmd in launchers:
    STUB["runtime"] = {"reset_seq": 0, "timezone": "UTC", "git_author": "Acme Bot <bot@example.com>", "git_coauthor": True}
    out = subprocess.run(cmd + ["-e", envf, "--once", "--", "true"], capture_output=True, text=True, timeout=60).stdout
    check("GIT_AUTHOR_NAME=Acme Bot" in out and "GIT_AUTHOR_EMAIL=bot@example.com" in out and "GIT_COMMITTER_NAME=Acme Bot" in out
          and "GIT_COMMITTER_EMAIL=bot@example.com" in out and "KALMIDO_GIT_COAUTHOR=1" in out, f"{name}: --once sets the git author {out[-300:]}")
    check(TOKEN not in out, f"{name}: the token is never printed")
    STUB["runtime"] = {"reset_seq": 0, "timezone": "UTC"}
    out = subprocess.run(cmd + ["-e", envf, "--once", "--", "true"], capture_output=True, text=True, timeout=60).stdout
    check("GIT_AUTHOR" not in out and "KALMIDO_GIT_COAUTHOR" not in out and "true" in out, f"{name}: an older server: nothing set {out[-200:]}")
srv.shutdown()
shutil.rmtree(tmp, ignore_errors=True)

sys.exit(done("p2396_a_api"))
