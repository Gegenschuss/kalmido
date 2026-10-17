#!/usr/bin/env python3
"""2.86.0 API tests, part D (files and inputs, hardening). Invented names only. The test server takes 1 MB per file
(TASKS_MAX_FILE_MB=1); this suite starts it with KALMIDO_FORM_FILES_MB_HOUR=2.
 - N22: an upload stops right after the per-file limit: a task file, a file-store upload and a new version above 1 MB are
   refused as before ("larger than 1 MB") and leave nothing on disk; a version upload whose body is clearly longer than
   one file is refused with 413 before it is read; files below the limit keep their full size
 - N23: an inline PDF (task file, file store) is served with a sandbox CSP, an image keeps its CSP
 - N24: the public form takes at most KALMIDO_FORM_FILES_MB_HOUR of anonymous file bytes per form and hour; then the
   report is refused with a "try later" page (429) and no task; a body longer than one form file is refused (413)
 - N25: deleting a file for good from the trash removes its stored file (after the commit) and its rows
 - N28: the job history still finds the person's messages addressed to the job by its first name (escaped ILIKE)
usage: p286_d_api_test.py <datadir>      (a fresh container; P286D_NOSTART=1 = the server already runs)"""
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
MB = 1024 * 1024
STARTED = not os.environ.get("P286D_NOSTART")


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def stored_files():
    """Every stored file below the data folder's attachments (None when the folder is not reachable from here)."""
    root = os.path.join(DATA, "attachments")
    if not DATA or not os.path.isdir(root):
        return None
    out = set()
    for d, _dirs, fs in os.walk(root):
        out |= {os.path.join(d, f) for f in fs}
    return out


def stamp_of(text):
    m = re.search(r'name="stamp" value="([^"]+)"', text)
    return m.group(1) if m else ""


if STARTED:
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_FORM_FILES_MB_HOUR=2")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "comments,agents,forms"})
A.patch(B + "/api/admin/settings", json={"public_links": True})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
W = A.post(B + "/api/lists", json={"name": "Garden", "org_id": ORG}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Plant beans", "list_id": W}).json()["id"]

# ================================================================== N22: uploads stop at the limit
before = stored_files()
r = A.post(B + f"/api/tasks/{T}/attachments", files=[("file", ("big.bin", os.urandom(MB + 300 * 1024), "application/octet-stream"))])
check(r.status_code == 400 and "larger than 1 MB" in r.text, f"N22: a task file above 1 MB refused as before ({r.status_code} {r.text[:160]})")
check(before is None or stored_files() == before, "N22: the refused task file left nothing on disk")
small = os.urandom(600 * 1024)
r = A.post(B + f"/api/tasks/{T}/attachments", files=[("file", ("small.bin", small, "application/octet-stream"))])
att = [a for a in (r.json().get("attachments") or []) if a["name"] == "small.bin"] if r.ok else []
check(r.ok and att and att[0]["size"] == len(small), f"N22: a task file below the limit keeps its full size {r.status_code} {att}")
if att:
    g = A.get(B + f"/api/attachments/{att[0]['id']}?dl=1")
    check(g.ok and g.content == small, "N22: ... and comes back byte for byte")

before = stored_files()
r = A.post(B + "/api/files/upload", data={"space": "private", "replace": "0"}, files={"file": ("big.bin", os.urandom(MB + 300 * 1024), "application/octet-stream")})
check(r.status_code == 400 and "larger than 1 MB" in r.text, f"N22: a file-store upload above 1 MB refused as before ({r.status_code} {r.text[:160]})")
check(before is None or stored_files() == before, "N22: the refused file-store upload left nothing on disk")
r = A.post(B + "/api/files/upload", data={"space": "private", "replace": "0"}, files={"file": ("notes.bin", small, "application/octet-stream")})
check(r.status_code == 201, f"N22: a file-store upload below the limit {r.status_code} {r.text[:160]}")
NF = r.json()["items"][0]["id"] if r.status_code == 201 else 0
check(NF and A.get(B + f"/api/files/nodes/{NF}/content").content == small, "N22: ... stored in full")
r = A.post(B + f"/api/files/nodes/{NF}/versions", files={"file": ("notes.bin", os.urandom(MB + 300 * 1024), "application/octet-stream")})
check(r.status_code == 400 and "larger than 1 MB" in r.text, f"N22: a new version above 1 MB refused as before ({r.status_code} {r.text[:160]})")
r = A.post(B + f"/api/files/nodes/{NF}/versions", files={"file": ("notes.bin", os.urandom(3 * MB), "application/octet-stream")})
check(r.status_code == 413 and "1 MB" in r.text, f"N22: a version upload far above one file: 413 before it is read ({r.status_code} {r.text[:160]})")
small2 = os.urandom(700 * 1024)
r = A.post(B + f"/api/files/nodes/{NF}/versions", files={"file": ("notes.bin", small2, "application/octet-stream")})
check(r.ok and A.get(B + f"/api/files/nodes/{NF}/content").content == small2, f"N22: a version below the limit still works {r.status_code}")

# ================================================================== N23: PDFs with a sandbox CSP
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
r = A.post(B + f"/api/tasks/{T}/attachments", files=[("file", ("plan.pdf", PDF, "application/pdf"))])
pa = [a for a in (r.json().get("attachments") or []) if a["name"] == "plan.pdf"] if r.ok else []
check(bool(pa), "setup: a PDF on the task " + r.text[:160])
if pa:
    h = A.get(B + f"/api/attachments/{pa[0]['id']}").headers
    check(h.get("Content-Type") == "application/pdf" and "sandbox" in h.get("Content-Security-Policy", "")
          and not h.get("Content-Disposition", "").startswith("attachment"), f"N23: a task PDF inline with a sandbox CSP {dict(h)}")
r = A.post(B + "/api/files/upload", data={"space": "private", "replace": "0"}, files={"file": ("plan.pdf", PDF, "application/pdf")})
NP = r.json()["items"][0]["id"] if r.status_code == 201 else 0
h = A.get(B + f"/api/files/nodes/{NP}/content").headers if NP else {}
check(NP and h.get("Content-Type") == "application/pdf" and "sandbox" in h.get("Content-Security-Policy", ""), f"N23: a file-store PDF with a sandbox CSP {dict(h)}")

# ================================================================== N25: purge unlinks after the commit
r = A.post(B + "/api/files/upload", data={"space": "private", "replace": "0"}, files={"file": ("gone.bin", os.urandom(4096), "application/octet-stream")})
NG = r.json()["items"][0]["id"] if r.status_code == 201 else 0
before = stored_files()
check(NG and A.delete(B + f"/api/files/nodes/{NG}").ok, "setup: a file into the trash")
check(before is None or stored_files() == before, "N25: in the trash the stored file stays")
r = A.delete(B + f"/api/files/nodes/{NG}?purge=1")
check(r.ok, f"N25: deleted for good {r.status_code} {r.text[:160]}")
after = stored_files()
check(after is None or (len(before - after) == 1 and not after - before), f"N25: exactly its stored file is gone ({None if after is None else len(before - after)})")
check(A.get(B + f"/api/files/nodes/{NG}").status_code == 404, "N25: the node is gone")

# ================================================================== N24: the form's byte budget
r = A.post(B + f"/api/lists/{W}/forms", json={"title": "Report", "access": "public", "ttype": "bug", "files": True, "ask_email": False})
check(r.status_code == 201, "setup: a public form with a file " + r.text[:200])
tok = r.json()["url"].rsplit("/", 1)[1] if r.status_code == 201 else "-"
anon = sess()


def send(subject, data):
    p = anon.get(B + "/f/" + tok)
    st = stamp_of(p.text)
    time.sleep(3.2)
    return anon.post(B + "/f/" + tok, data={"subject": subject, "stamp": st}, files={"file": ("photo.bin", data, "application/octet-stream")})


def task_titled(title):
    return [t for t in A.get(B + "/api/state").json()["tasks"] if t["title"] == title]


p = send("First report", os.urandom(900 * 1024))
check(p.ok and task_titled("First report"), f"N24: a report with a file within the budget {p.status_code}")
p = send("Second report", os.urandom(900 * 1024))
check(p.ok and task_titled("Second report"), f"N24: a second one still fits (2 MB per hour in this test) {p.status_code}")
if STARTED:
    p = send("Third report", os.urandom(900 * 1024))
    check(p.status_code == 429 and "no more files" in p.text and not task_titled("Third report"),
          f"N24: the budget used up: refused, no task {p.status_code} {p.text[-300:]}")
p = anon.post(B + "/f/" + tok, data={"subject": "Huge"}, files={"file": ("x.bin", b"x" * (11 * MB), "application/octet-stream")})
check(p.status_code == 413 and not task_titled("Huge"), f"N22/N24: a body above one form file refused before it is read {p.status_code}")

# ================================================================== N28: job history (escaped prefix match)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
A.patch(B + f"/api/admin/agents/{CL}", json={"org_id": ORG})
A.put(B + f"/api/lists/{W}/members", json={"user_id": CL, "role": "edit"})
r = requests.post(V + "/agent/jobs", headers=CLH, json={"title": "Clara: weeding", "task_id": T})
check(r.status_code in (200, 201), "setup: a job " + r.text[:200])
JC = r.json().get("id") if r.ok else 0
m1 = A.post(B + f"/api/agents/{CL}/chat", json={"body": "Clara: please start with the beans"}).json().get("id")
m2 = A.post(B + f"/api/agents/{CL}/chat", json={"body": "Clarabelle: not for her"}).json().get("id")
m3 = A.post(B + f"/api/agents/{CL}/chat", json={"body": f"Job {JC}: and the roses"}).json().get("id")
r = A.get(B + f"/api/agents/{CL}/chat?job={JC}")
got = [m["id"] for m in r.json().get("messages", [])] if r.ok else []
check(r.ok and m1 in got and m3 in got and m2 not in got, f"N28: the job's history finds the addressed messages only {got} ({m1}, {m3} in, {m2} out)")

print(f"p286_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
