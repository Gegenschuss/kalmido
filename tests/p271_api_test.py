#!/usr/bin/env python3
"""2.7.1 API (#410), own container (start.sh, with the fake Paperless of fake_services.py):
the overview of a project list: GET /api/lists/<id>/overview (only project lists: 409 otherwise; who may read it per role,
participants see only the files of their own tasks), the description (Markdown, owner / list admin / member, never a viewer
or participant, length limit), key links (http / https only, title from the address, order, limit), milestones (date, done,
in /api/state with the list for the timeline), project files (upload with the attachment rules: size limit, safe file
names, html / svg never inline, sandbox CSP; download per role; delete; removed with the list), Paperless documents of the
list (hidden for users without access), task files gathered read-only, members + status history + time; the token API
(/api/v1/lists/<id>/overview, links, milestones, files; scopes; unknown fields) and the OpenAPI document.
usage: p271_api_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": "password123"})
    assert r.ok, r.text
    return s


env = dict(os.environ, EXTRA="-e PAPERLESS_TOKEN=pl-legacy-env-token -e PAPERLESS_API=http://127.0.0.1:8082 "
                             "-e PAPERLESS_PUBLIC_URL=https://paperless.example.test")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["cp", os.path.join(N, "fake_services.py"), DATA], check=True)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_services.py"], check=True)
time.sleep(0.8)

requests.post(B + "/api/auth/setup", headers=H, json={"username": "alice", "display_name": "Alice", "password": "password123"})
A = sess("alice")
ids = {}
for u in ("bob", "vic", "pat", "zoe"):
    ids[u] = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"}).json()["id"]
Bo, Vi, Pa, Zo = sess("bob"), sess("vic"), sess("pat"), sess("zoe")
for x in (A, Bo, Vi, Pa, Zo):
    x.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

P = A.post(B + "/api/lists", json={"name": "Website relaunch", "kind": "project"}).json()["id"]
PL = A.post(B + "/api/lists", json={"name": "Groceries"}).json()["id"]
for u, role in (("bob", "edit"), ("vic", "view"), ("pat", "participant")):
    check(A.put(B + f"/api/lists/{P}/members", json={"user_id": ids[u], "role": role}).ok, f"share with {u} as {role}")

# ================================================================== reading
o = A.get(B + f"/api/lists/{P}/overview")
check(o.ok, f"owner reads the overview: {o.status_code}")
o = o.json()
check(o["description"] == "" and o["links"] == [] and o["milestones"] == [] and o["files"] == [] and o["can_edit"] is True,
      "empty overview, owner can edit")
check({m["role"] for m in o["members"]} == {"owner", "edit", "view", "participant"}, f"members with roles: {o['members']}")
check(o["time"] is not None and o["time"]["day_hours"] == 8 and o["time"]["seconds"] == 0, f"time: {o['time']}")
check(A.get(B + f"/api/lists/{PL}/overview").status_code == 409, "a plain list has no overview (409)")
check(Zo.get(B + f"/api/lists/{P}/overview").status_code == 404, "a stranger: 404")
check(Vi.get(B + f"/api/lists/{P}/overview").json()["can_edit"] is False, "viewer reads, cannot edit")
check(Pa.get(B + f"/api/lists/{P}/overview").json()["can_edit"] is False, "participant reads, cannot edit")

# ================================================================== description
check(Bo.patch(B + f"/api/lists/{P}/overview", json={"description": "## Goal\nNew **site** by June"}).json()["description"]
      == "## Goal\nNew **site** by June", "member (edit) sets the description")
check(Vi.patch(B + f"/api/lists/{P}/overview", json={"description": "x"}).status_code == 403, "viewer: 403")
check(Pa.patch(B + f"/api/lists/{P}/overview", json={"description": "x"}).status_code == 403, "participant: 403")
check(A.patch(B + f"/api/lists/{P}/overview", json={"description": "x" * 20001}).status_code == 400, "description over 20000: 400")
check(A.patch(B + f"/api/lists/{P}/overview", json={"description": 5}).status_code == 400, "description not text: 400")
check(A.patch(B + f"/api/lists/{PL}/overview", json={"description": "x"}).status_code == 409, "plain list: 409")
r = A.patch(B + f"/api/lists/{P}/overview", json={"description": "## Goal\nNew **site** by June", "colour": "x"})
check(r.ok and "colour" in r.headers.get("X-Kalmido-Unknown-Fields", ""), "unknown web field: named in the header")
st = A.get(B + "/api/state").json()
check(next(x for x in st["lists"] if x["id"] == P)["description"].startswith("## Goal"), "description in /api/state")

# ================================================================== key links
r = Bo.post(B + f"/api/lists/{P}/links", json={"url": "https://github.com/acme/site"})
check(r.ok and r.json()["title"] == "github.com/acme/site", f"link without title: title from the address {r.text[:120]}")
L1 = r.json()["id"]
L2 = A.post(B + f"/api/lists/{P}/links", json={"title": "Designs", "url": "https://www.figma.com/file/abc"}).json()["id"]
for bad in ("javascript:alert(1)", "ftp://x.example", "", "https://", "data:text/html,x"):
    check(A.post(B + f"/api/lists/{P}/links", json={"url": bad}).status_code == 400, f"link {bad!r}: 400")
check(Vi.post(B + f"/api/lists/{P}/links", json={"url": "https://x.example"}).status_code == 403, "viewer cannot add a link")
check(A.patch(B + f"/api/lists/{P}/links/{L1}", json={"title": "Repository"}).json()["title"] == "Repository", "rename a link")
check(A.patch(B + f"/api/lists/{P}/links/{L1}", json={"url": "javascript:x"}).status_code == 400, "change to a bad address: 400")
check(A.patch(B + f"/api/lists/{PL}/links/{L1}", json={"title": "x"}).status_code == 409, "link of another list via a plain list: 409")
r = A.put(B + f"/api/lists/{P}/links/order", json={"ids": [L2, L1]})
check(r.ok and [x["id"] for x in r.json()["data"]] == [L2, L1], "reorder")
check(A.put(B + f"/api/lists/{P}/links/order", json={"ids": [L2]}).status_code == 400, "reorder with a missing id: 400")
check(A.put(B + f"/api/lists/{P}/links/order", json={"ids": [L2, L1, 999]}).status_code == 400, "reorder with a foreign id: 400")
check([x["id"] for x in A.get(B + f"/api/lists/{P}/overview").json()["links"]] == [L2, L1], "order kept")
L3 = A.post(B + f"/api/lists/{P}/links", json={"url": "https://x.example/3"}).json()["id"]
check(A.delete(B + f"/api/lists/{P}/links/{L3}").ok, "delete a link")
check(A.delete(B + f"/api/lists/{P}/links/{L3}").status_code == 404, "deleted link: 404")
for i in range(48):
    A.post(B + f"/api/lists/{P}/links", json={"url": f"https://x.example/{i}"})
check(A.post(B + f"/api/lists/{P}/links", json={"url": "https://x.example/51"}).status_code == 409, "51st link: 409")
for x in A.get(B + f"/api/lists/{P}/overview").json()["links"]:
    if x["id"] not in (L1, L2):
        A.delete(B + f"/api/lists/{P}/links/{x['id']}")

# ================================================================== milestones
r = Bo.post(B + f"/api/lists/{P}/milestones", json={"name": "Launch", "day": "2026-12-01"})
check(r.ok and r.json()["day"] == "2026-12-01" and r.json()["done"] is False, f"add a milestone {r.text[:100]}")
M1 = r.json()["id"]
M0 = A.post(B + f"/api/lists/{P}/milestones", json={"name": "Kick-off", "day": "2026-10-05", "done": True}).json()["id"]
for bad in ({"name": "", "day": "2026-12-01"}, {"name": "x", "day": "2026-13-01"}, {"name": "x", "day": "tomorrow"}, {"name": "x"},
            {"name": "x", "day": "2026-12-01", "done": "yes"}):
    check(A.post(B + f"/api/lists/{P}/milestones", json=bad).status_code == 400, f"bad milestone {bad}: 400")
check(Vi.post(B + f"/api/lists/{P}/milestones", json={"name": "x", "day": "2026-12-01"}).status_code == 403, "viewer: 403")
check(A.patch(B + f"/api/lists/{P}/milestones/{M1}", json={"done": True}).json()["done"] is True, "tick a milestone")
check(A.patch(B + f"/api/lists/{P}/milestones/{M1}", json={"done": False, "day": "2026-12-02"}).json()["day"] == "2026-12-02", "move a milestone")
check([m["id"] for m in A.get(B + f"/api/lists/{P}/overview").json()["milestones"]] == [M0, M1], "milestones by day")
lst = next(x for x in Vi.get(B + "/api/state").json()["lists"] if x["id"] == P)
check([m["name"] for m in lst["milestones"]] == ["Kick-off", "Launch"], "milestones with the list in /api/state (viewer too)")
check(next(x for x in A.get(B + "/api/state").json()["lists"] if x["id"] == PL)["milestones"] == [], "plain list: no milestones")

# ================================================================== project files
r = Bo.post(B + f"/api/lists/{P}/files", files=[("file", ("brief.pdf", b"%PDF-1.4 x", "application/pdf")),
                                                  ("file", ("../../evil<x>.html", b"<script>alert(1)</script>", "text/html"))])
check(r.ok and len(r.json()["files"]) == 2, f"member uploads 2 files {r.text[:120]}")
fs = {f["name"]: f for f in r.json()["files"]}
check("evil_x_.html" in fs and all("/" not in n for n in fs), f"safe file names: {list(fs)}")
check(fs["brief.pdf"]["user_name"] == "Bob", "who uploaded")
fh, fp = fs["evil_x_.html"]["id"], fs["brief.pdf"]["id"]
g = Vi.get(B + f"/api/list-files/{fh}")
check(g.ok and g.headers["Content-Type"].startswith("application/octet-stream") and "attachment" in g.headers.get("Content-Disposition", "")
      and "sandbox" in g.headers.get("Content-Security-Policy", "") and g.headers.get("X-Content-Type-Options") == "nosniff",
      f"html is a download with a sandbox CSP: {g.headers}")
g = Pa.get(B + f"/api/list-files/{fp}")
check(g.ok and g.headers["Content-Type"] == "application/pdf" and g.content.startswith(b"%PDF"), "pdf inline (participant may read)")
check(Zo.get(B + f"/api/list-files/{fp}").status_code == 404, "stranger: 404")
check(Vi.post(B + f"/api/lists/{P}/files", files={"file": ("a.txt", b"x")}).status_code == 403, "viewer cannot upload")
check(Pa.delete(B + f"/api/list-files/{fp}").status_code == 403, "participant cannot delete")
big = A.post(B + f"/api/lists/{P}/files", files={"file": ("big.bin", b"0" * (1024 * 1024 + 10))})
check(big.status_code in (400, 413), f"over the size limit (1 MB in the tests): {big.status_code}")
check(not any(f["name"] == "big.bin" for f in A.get(B + f"/api/lists/{P}/overview").json()["files"]), "too large: nothing stored")
check(A.post(B + f"/api/lists/{PL}/files", files={"file": ("a.txt", b"x")}).status_code == 409, "plain list: 409")
check(A.delete(B + f"/api/list-files/{fh}").ok and A.get(B + f"/api/list-files/{fh}").status_code == 404, "delete a project file")
on_disk = subprocess.run(["docker", "exec", CT, "sh", "-c", f"ls /data/attachments/lists/{P}/"], capture_output=True, text=True).stdout.split()
check(len(on_disk) == 1 and on_disk[0].endswith("brief.pdf"), f"files below attachments/lists/<id>/, the deleted one gone: {on_disk}")

# ================================================================== task files (read-only, per role) + Paperless
T1 = A.post(B + "/api/tasks", json={"title": "Wireframes", "list_id": P}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Pat's copy", "list_id": P, "assignee_id": ids["pat"]}).json()["id"]
A.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("wire.png", b"\x89PNG\r\n\x1a\nx", "image/png")})
A.post(B + f"/api/tasks/{T2}/attachments", files={"file": ("copy.txt", b"hello", "text/plain")})
o = Vi.get(B + f"/api/lists/{P}/overview").json()
check({(f["name"], f["task_title"]) for f in o["task_files"]} == {("wire.png", "Wireframes"), ("copy.txt", "Pat's copy")},
      f"task files with their task: {o['task_files']}")
o = Pa.get(B + f"/api/lists/{P}/overview").json()
check([f["name"] for f in o["task_files"]] == ["copy.txt"], f"participant: only files of their tasks {o['task_files']}")
A.delete(B + f"/api/tasks/{T1}")
check([f["name"] for f in A.get(B + f"/api/lists/{P}/overview").json()["task_files"]] == ["copy.txt"], "trash: not listed")

r = A.post(B + f"/api/lists/{P}/paperless", json={"doc_id": 42, "conn": 0})
check(r.ok and r.json()["paperless"][0]["title"] == "Secret doc 42", f"admin links a Paperless document to the list {r.text[:150]}")
again = A.post(B + f"/api/lists/{P}/paperless", json={"doc_id": 42, "conn": 0}).json()["paperless"]
check(len(again) == 1, "linking twice: once")
p = Bo.get(B + f"/api/lists/{P}/overview").json()["paperless"][0]
check(p.get("hidden") is True and p["doc_id"] is None and "Secret" not in p["title"], f"no Paperless access: hidden {p}")
check(Bo.post(B + f"/api/lists/{P}/paperless", json={"doc_id": 1, "conn": 0}).status_code == 403, "no access: cannot link")
check(Vi.delete(B + f"/api/lists/{P}/paperless/{p['id']}").status_code == 403, "viewer cannot unlink")
check(A.delete(B + f"/api/lists/{P}/paperless/{p['id']}").json()["paperless"] == [], "unlink")

# status history + time in the overview
A.post(B + f"/api/lists/{P}/status", json={"status": "at_risk", "note": "Copy late"})
o = Vi.get(B + f"/api/lists/{P}/overview").json()
check(o["status"]["current"] == "at_risk" and o["status"]["history"][0]["note"] == "Copy late", f"status in the overview {o['status']}")
A.patch(B + f"/api/lists/{P}", json={"day_hours": 6})
check(A.get(B + f"/api/lists/{P}/overview").json()["time"]["day_hours"] == 6, "the list's hours per day")

# ================================================================== token API + OpenAPI
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
rtok = A.post(B + "/api/me/tokens", json={"name": "r", "scopes": ["read", "attachments:read"]}).json()["token"]  # 2.15.0: files need attachments:read
T = {"Authorization": "Bearer " + tok}
R = {"Authorization": "Bearer " + rtok}
j = requests.get(V + f"/lists/{P}/overview", headers=R).json()
check(j["description"].startswith("## Goal") and len(j["links"]) == 2 and len(j["milestones"]) == 2, "v1: overview")
check(requests.patch(V + f"/lists/{P}/overview", headers=R, json={"description": "x"}).status_code == 403, "v1: read token cannot change")
r = requests.patch(V + f"/lists/{P}/overview", headers=T, json={"description": "From the API", "nope": 1})
check(r.status_code == 400 and r.json()["error"].get("fields") == ["nope"], f"v1: unknown field {r.text[:120]}")
check(requests.patch(V + f"/lists/{P}/overview", headers=T, json={"description": "From the API"}).json()["description"] == "From the API", "v1: description")
r = requests.post(V + f"/lists/{P}/links", headers=T, json={"title": "Docs", "url": "https://docs.example/x"})
check(r.status_code == 201 and r.json()["title"] == "Docs", f"v1: add a link {r.status_code}")
LV = r.json()["id"]
check(requests.patch(V + f"/lists/{P}/links/{LV}", headers=T, json={"title": "Docs 2"}).json()["title"] == "Docs 2", "v1: change a link")
check([x["id"] for x in requests.get(V + f"/lists/{P}/links", headers=R).json()["data"]][-1] == LV, "v1: links")
r = requests.put(V + f"/lists/{P}/links/order", headers=T, json={"ids": [LV, L2, L1]})
check(r.ok and r.json()["data"][0]["id"] == LV, "v1: reorder")
check(requests.delete(V + f"/lists/{P}/links/{LV}", headers=T).status_code == 204, "v1: delete a link")
check(requests.delete(V + f"/lists/{P}/links/abc", headers=T).status_code == 400, "v1: bad link id 400")
r = requests.post(V + f"/lists/{P}/milestones", headers=T, json={"name": "Beta", "day": "2026-11-01"})
check(r.status_code == 201, "v1: add a milestone")
MV = r.json()["id"]
check(requests.patch(V + f"/lists/{P}/milestones/{MV}", headers=T, json={"done": True}).json()["done"] is True, "v1: tick")
check([m["name"] for m in requests.get(V + f"/lists/{P}/milestones", headers=R).json()["data"]] == ["Kick-off", "Beta", "Launch"], "v1: milestones by day")
check(requests.delete(V + f"/lists/{P}/milestones/{MV}", headers=T).status_code == 204, "v1: delete a milestone")
r = requests.post(V + f"/lists/{P}/files", headers=T, files={"file": ("plan.txt", b"plan", "text/plain")})
check(r.status_code == 201 and any(f["name"] == "plan.txt" for f in r.json()["data"]), f"v1: upload {r.status_code} {r.text[:120]}")
FV = next(f["id"] for f in r.json()["data"] if f["name"] == "plan.txt")
check(requests.post(V + f"/lists/{P}/files", headers=R, files={"file": ("x.txt", b"x")}).status_code == 403, "v1: read token cannot upload")
g = requests.get(V + f"/lists/{P}/files/{FV}", headers=R)
check(g.ok and g.content == b"plan" and "attachment" in g.headers.get("Content-Disposition", ""), "v1: download")
check(requests.get(V + f"/lists/{PL}/files/{FV}", headers=R).status_code == 404, "v1: file through another list 404")
check(any(f["id"] == FV for f in requests.get(V + f"/lists/{P}/files", headers=R).json()["data"]), "v1: files")
check(requests.delete(V + f"/lists/{P}/files/{FV}", headers=T).status_code == 204, "v1: delete a file")
check(requests.get(V + f"/lists/{PL}/overview", headers=R).status_code == 409, "v1: plain list 409")
spec = requests.get(V + "/openapi.json").json()
for pth in ("/lists/{id}/overview", "/lists/{id}/links", "/lists/{id}/links/order", "/lists/{id}/links/{link_id}", "/lists/{id}/milestones",
            "/lists/{id}/milestones/{milestone_id}", "/lists/{id}/files", "/lists/{id}/files/{file_id}"):
    check(pth in spec["paths"], f"OpenAPI: {pth}")
check("ProjectOverview" in spec["components"]["schemas"], "OpenAPI: ProjectOverview schema")

# ================================================================== the list goes for good: its files go too
A.patch(B + f"/api/lists/{P}", json={"archived": 1})
check(A.delete(B + f"/api/lists/{P}").ok, "delete the archived project")
left = subprocess.run(["docker", "exec", CT, "sh", "-c", f"ls /data/attachments/lists/{P}/ 2>/dev/null | wc -l"], capture_output=True, text=True).stdout.strip()
check(left == "0", f"project files removed with the list: {left}")
check(A.get(B + f"/api/list-files/{fp}").status_code == 404, "file id gone")

print(f"p271_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
