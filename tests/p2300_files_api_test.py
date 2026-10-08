#!/usr/bin/env python3
"""2.30.0 API tests (files): agents write text files (#380), the file viewer's server side (#1035).
 - POST /api/v1/tasks/{id}/attachments/text {name, content}: a text file on a task (Markdown, HTML, code ...), 201 with
   version / replaces / url; the content comes back byte for byte; the right MIME type
 - the same name again = a new version next to the old one ("report (v2).md", then v3), the old file stays
 - endings that are not text (.sh .ps1 .bat .exe, none at all) get ".txt" (text/plain)
 - limits: at most 1 MB, not empty, name + content strings, no unknown fields
 - rights: only tasks the agent may change (a list shared with it with edit; view / not shared / deleted: refused), the scope
   attachments:write (a read-only agent: 403); the OpenAPI document names the route and its scope
 - "Created by agent": the task's attachments carry agent (the agent's name) in the app's state, a person's file does not;
   the activity names the agent as the one who added the file
 - an agent's multipart upload and an agent's chat file never keep an executable ending either; a person's upload does
 - delivery stays safe: HTML / SVG / Markdown / scripts are never served as text/html or inline (octet-stream, attachment,
   nosniff, sandbox CSP), images and PDFs still inline
Starts its OWN container (start.sh).
usage: p2300_files_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


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


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=30, **k)


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
assert r.ok, r.text
BOB = r.json()["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "attachments:read", "attachments:write"],
                                          "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
AG, cl = r.json()["id"], Api(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "reader", "display_name": "Reader"})
AR, rd = r.json()["id"], Api(r.json()["token"])

L1 = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]      # claude edit
L2 = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]   # alice only
L3 = A.post(B + "/api/lists", json={"name": "Read"}).json()["id"]      # reader edit (no file scope)
assert A.put(B + f"/api/lists/{L1}/members", json={"user_id": AG, "role": "edit"}).ok
assert A.put(B + f"/api/lists/{L1}/members", json={"user_id": BOB, "role": "view"}).ok
assert A.put(B + f"/api/lists/{L3}/members", json={"user_id": AR, "role": "edit"}).ok
for lid in (L1, L3):
    A.patch(B + f"/api/lists/{lid}", json={"agent_members": True, "agent_peers": True})
T1 = A.post(B + "/api/tasks", json={"title": "Review", "list_id": L1}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Secret", "list_id": L2}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"title": "Reader task", "list_id": L3}).json()["id"]
T4 = A.post(B + "/api/tasks", json={"title": "Gone soon", "list_id": L1}).json()["id"]

MD = "# Gutachten\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nUmlaute: äöü ß, emoji-free.\n<script>alert(1)</script>\n"


def text(tid, name, content, api=cl, **extra):
    return api.req("POST", f"/tasks/{tid}/attachments/text", json={"name": name, "content": content, **extra})


# ================================================================== #380 create
r = text(T1, "report.md", MD)
check(r.status_code == 201, f"#380: text file -> 201 ({r.status_code} {r.text[:200]})")
j = r.json() if r.ok else {}
R1 = j.get("id")
check(j.get("name") == "report.md" and j.get("mime") == "text/markdown" and j.get("size") == len(MD.encode())
      and j.get("version") == 1 and j.get("replaces") is None and j.get("task_id") == T1 and j.get("url") == f"/api/v1/attachments/{R1}",
      f"#380: the answer: name, text/markdown, size in UTF-8 bytes, version 1, url ({j})")
r = cl.req("GET", f"/attachments/{R1}")
check(r.status_code == 200 and r.content == MD.encode(), "#380: the content comes back byte for byte (UTF-8)")
check(any(a["id"] == R1 for a in cl.req("GET", f"/tasks/{T1}/attachments").json()["data"]), "#380: ... and is listed on the task")

# versions
r2 = text(T1, "report.md", MD + "\nv2\n").json()
check(r2.get("name") == "report (v2).md" and r2.get("version") == 2 and r2.get("replaces") == R1, f"#380: same name -> report (v2).md, replaces the first ({r2})")
r3 = text(T1, "report.md", MD + "\nv3\n").json()
check(r3.get("name") == "report (v3).md" and r3.get("version") == 3 and r3.get("replaces") == r2.get("id"), f"#380: ... then v3 after the highest ({r3})")
r4 = text(T1, "report (v2).md", "again").json()
check(r4.get("name") == "report (v4).md" and r4.get("version") == 4, f"#380: a name with a version counts as the same file ({r4})")
names = [a["name"] for a in cl.req("GET", f"/tasks/{T1}/attachments").json()["data"]]
check(names.count("report.md") == 1 and "report (v2).md" in names and "report (v3).md" in names, f"#380: the old versions stay ({names})")
check(cl.req("GET", f"/attachments/{R1}").content == MD.encode(), "#380: ... unchanged")
check(text(T1, "other.md", "x").json().get("version") == 1, "#380: another name starts at version 1")
check(text(T1, "REPORT.txt", "x").json().get("name") == "REPORT.txt", "#380: another ending is another file")

# endings
for nm, want, mime in (("deploy.sh", "deploy.sh.txt", "text/plain"), ("fix.ps1", "fix.ps1.txt", "text/plain"), ("run.bat", "run.bat.txt", "text/plain"),
                       ("tool.exe", "tool.exe.txt", "text/plain"), ("notes", "notes.txt", "text/plain"), ("x.command", "x.command.txt", "text/plain"),
                       ("page.html", "page.html", "text/html"), ("style.css", "style.css", "text/css"), ("app.js", "app.js", "text/javascript"),
                       ("data.json", "data.json", "application/json"), ("t.csv", "t.csv", "text/csv"), ("main.py", "main.py", "text/plain"),
                       ("../../etc/passwd", "passwd.txt", "text/plain")):
    j = text(T1, nm, "echo hi\n").json()
    check(j.get("name") == want and j.get("mime") == mime, f"#380: {nm} -> {want} ({mime}): {j.get('name')} {j.get('mime')}")

# limits + input
check(text(T1, "big.md", "x" * (1024 * 1024 + 1)).status_code == 400, "#380: more than 1 MB -> 400")
check(text(T1, "full.md", "x" * (1024 * 1024)).status_code == 201, "#380: exactly 1 MB is fine")
check(text(T1, "big2.md", "ä" * (512 * 1024 + 1)).status_code == 400, "#380: the limit counts UTF-8 bytes")
check(text(T1, "empty.md", "").status_code == 400, "#380: empty content -> 400")
check(text(T1, "   ", "x").status_code == 400, "#380: an empty name -> 400")
check(cl.req("POST", f"/tasks/{T1}/attachments/text", json={"name": "a.md"}).status_code == 400, "#380: content missing -> 400")
check(cl.req("POST", f"/tasks/{T1}/attachments/text", json={"name": "a.md", "content": 5}).status_code == 400, "#380: content not a string -> 400")
r = cl.req("POST", f"/tasks/{T1}/attachments/text", json={"name": "a.md", "content": "x", "mime": "text/html"})
check(r.status_code == 400 and r.json().get("error", {}).get("code") == "unknown_field", "#380: unknown field -> 400 unknown_field")

# rights
check(text(T2, "x.md", "x").status_code == 404, "#380: a task in a list not shared with the agent -> 404")
check(text(T3, "x.md", "x", api=rd).status_code == 403, "#380: without attachments:write -> 403")
check(text(T1, "x.md", "x", api=rd).status_code in (403, 404), "#380: the read-only agent on another list -> refused")
assert A.delete(B + f"/api/tasks/{T4}").ok
check(text(T4, "x.md", "x").status_code == 404, "#380: a deleted task -> 404")
assert A.put(B + f"/api/lists/{L1}/members", json={"user_id": AG, "role": "view"}).ok
check(text(T1, "view.md", "x").status_code in (403, 404), "#380: a list the agent may only view -> refused")
assert A.put(B + f"/api/lists/{L1}/members", json={"user_id": AG, "role": "edit"}).ok
spec = requests.get(V + "/openapi.json").json()
op = spec["paths"].get("/tasks/{id}/attachments/text", {}).get("post", {})
check(op.get("x-kalmido-scope") == "attachments:write" and op.get("requestBody"), "#380: OpenAPI documents the route with its scope")

# "Created by agent" + activity
st = {t["id"]: t for t in A.get(B + "/api/state").json()["tasks"]}
atts = {a["name"]: a for a in st[T1]["attachments"]}
check(atts.get("report.md", {}).get("agent") == "Claude", f"#380: the app's task carries agent = Claude ({atts.get('report.md')})")
r = A.post(B + f"/api/tasks/{T1}/attachments", files=[("file", ("mine.sh", b"echo me", "text/x-sh"))])
check(r.ok and any(a["name"] == "mine.sh" and "agent" not in a for a in r.json()["attachments"]), "#380: a person's upload keeps .sh and has no agent mark")
acts = dbx("SELECT user_id, data FROM activity WHERE task_id=? AND kind='attach' ORDER BY id", (T1,))
check(any(u == AG and "report.md" in d for u, d in acts), f"#380: the activity names the agent as the one who added it ({acts[:2]})")
check(any(u == AG and "report (v2).md" in d for u, d in acts), "#380: ... a new version too")

# agent multipart + chat files: no executable ending either
r = cl.req("POST", f"/tasks/{T1}/attachments", files=[("file", ("evil.sh", b"rm -rf ~", "text/x-sh")), ("file", ("pic.png", PNG, "image/png"))])
nm = [a["name"] for a in r.json().get("data", [])] if r.ok else r.text
check(r.status_code == 201 and nm == ["evil.sh.txt", "pic.png"], f"#380: an agent's upload: evil.sh -> evil.sh.txt, a picture stays ({nm})")
acts = dbx("SELECT data FROM activity WHERE task_id=? AND kind='attach' AND user_id=? ORDER BY id DESC LIMIT 1", (T1, AG))
check(acts and "evil.sh.txt" in acts[0][0], "#380: ... the activity shows the stored name")
r = A.post(B + f"/api/agents/{AG}/chat", data={"body": "hi"})
check(r.status_code == 201, f"chat opened ({r.status_code} {r.text[:120]})")
r = cl.req("POST", f"/agent/chats/{1}", data={"body": "script"}, files=[("file", ("fix.ps1", b"Remove-Item", "text/plain"))])
cf = r.json().get("attachments", []) if r.ok else []
check(r.status_code == 201 and [a["name"] for a in cf] == ["fix.ps1.txt"] and cf[0]["mime"] == "text/plain", f"#380: an agent's chat file: fix.ps1 -> fix.ps1.txt ({r.status_code} {cf})")

# ================================================================== #1035 delivery stays safe
files = [("file", ("page.html", b"<script>alert(1)</script>", "text/html")), ("file", ("pic.svg", b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>", "image/svg+xml")),
         ("file", ("note.md", b"# hi <img src=x onerror=alert(1)>", "text/markdown")), ("file", ("doc.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")),
         ("file", ("p.png", PNG, "image/png"))]
r = A.post(B + f"/api/tasks/{T1}/attachments", files=files)
assert r.ok, r.text
by = {a["name"]: a for a in r.json()["attachments"]}
for nm in ("page.html", "pic.svg", "note.md"):
    for q in ("", "?dl=1"):
        h = A.get(B + f"/api/attachments/{by[nm]['id']}{q}").headers
        ct, cd = h.get("Content-Type", ""), h.get("Content-Disposition", "")
        check(ct.startswith("application/octet-stream") and cd.startswith("attachment") and h.get("X-Content-Type-Options") == "nosniff"
              and "sandbox" in h.get("Content-Security-Policy", ""), f"#1035: {nm}{q}: a download, never rendered ({ct} | {cd})")
h = cl.req("GET", f"/attachments/{by['page.html']['id']}").headers
check(h.get("Content-Type", "").startswith("application/octet-stream") and h.get("X-Content-Type-Options") == "nosniff", "#1035: ... through the API too")
h = A.get(B + f"/api/attachments/{by['p.png']['id']}").headers
check(h.get("Content-Type") == "image/png" and not h.get("Content-Disposition", "").startswith("attachment") and "sandbox" in h.get("Content-Security-Policy", ""),
      "#1035: images stay inline (sandboxed)")
h = A.get(B + f"/api/attachments/{by['doc.pdf']['id']}").headers
check(h.get("Content-Type") == "application/pdf", "#1035: PDFs stay inline")
cid = cf[0]["id"] if cf else 0
h = A.get(B + f"/api/chat-files/{cid}?dl=1").headers
check(h.get("Content-Type", "").startswith("application/octet-stream") and h.get("X-Content-Type-Options") == "nosniff", "#1035: chat text files: a download with nosniff")
check(A.get(B + f"/api/attachments/{R1}?dl=1").content == MD.encode(), "#1035: the viewer's fetch (dl=1) gets the text")
check(sess("bob").get(B + f"/api/attachments/{R1}?dl=1").status_code == 200, "#1035: a viewer of the list reads it too")

print(f"p2300_files_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
