#!/usr/bin/env python3
"""2.0.2: own list icons (presets + upload: square PNG, no metadata, served only to people who see the list, the file goes
with a new picture / the list), POST /drop/drop as an alias of /drop (a shortcut that appends /drop twice), the task an
agent reports it works on (PUT /api/v1/agent/status {task_id}: shown only to people who see that task, cleared with idle)
and the tasks of its running jobs.
Runs against a fresh test container (start.sh). usage: p202_api_test.py <datadir>"""
import io
import os
import sys

import requests

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": "password123"})
        assert r.ok, (user, r.text)
    return s


def png_bytes(w=300, h=200, meta=True):
    from PIL import Image, PngImagePlugin
    im = Image.new("RGBA", (w, h), (255, 0, 0, 128))
    info = PngImagePlugin.PngInfo()
    if meta:
        info.add_text("Comment", "secret location 52.5,13.4")
    out = io.BytesIO()
    im.save(out, "PNG", pnginfo=info)
    return out.getvalue()


def lst(s, lid):
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
bob = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
carl = A.post(B + "/api/users", json={"username": "carl", "display_name": "Carl", "password": "password123"}).json()["id"]
Bo, C = sess("bob"), sess("carl")
for s_ in (A, Bo, C):
    s_.patch(B + "/api/settings", json={"lang": "en", "features": "collab,agents"})

# ================================================================== list icons
L = A.post(B + "/api/lists", json={"name": "Film"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": bob, "role": "edit"})
check(lst(A, L)["icon"] == "", "no icon by default")
r = A.put(B + f"/api/lists/{L}/icon", json={"preset": "kalmido"})
check(r.ok and r.json()["icon"] == "/static/icon.svg", "preset: the app icon " + r.text[:100])
check(lst(A, L)["icon"] == "/static/icon.svg" and lst(Bo, L)["icon"] == "/static/icon.svg", "state: owner and member see the icon")
r = A.put(B + f"/api/lists/{L}/icon", json={"preset": "robot"})
check(r.ok and r.json()["icon"] == "/static/avatars/robot.svg", "preset: a profile picture")
check(A.put(B + f"/api/lists/{L}/icon", json={"preset": "../../etc/passwd"}).status_code == 400, "unknown preset refused")
check(Bo.put(B + f"/api/lists/{L}/icon", json={"preset": "robot"}).status_code == 403, "a member cannot change the icon (owner only)")
check(C.put(B + f"/api/lists/{L}/icon", json={"preset": "robot"}).status_code == 404, "a stranger does not even see the list")
r = A.post(B + f"/api/lists/{L}/icon", files={"file": ("x.png", png_bytes(), "image/png")})
url = r.json().get("icon", "")
check(r.ok and url.startswith(f"/api/list-icon/{L}/") and url.endswith(".png"), "upload: own picture " + r.text[:120])
g = A.get(B + url)
check(g.ok and g.headers["content-type"] == "image/png" and "immutable" in g.headers.get("cache-control", ""), "owner fetches the picture")
from PIL import Image  # noqa: E402
im = Image.open(io.BytesIO(g.content))
check(im.size == (128, 128) and im.mode == "RGBA", f"square 128 px, transparency kept: {im.size} {im.mode}")
check(b"secret location" not in g.content and not im.info.get("Comment"), "no metadata carried over")
check(Bo.get(B + url).ok, "a member fetches the picture")
check(C.get(B + url).status_code == 404, "a stranger gets 404 for the picture")
check(requests.get(B + url).status_code in (401, 403, 302), "no login, no picture")
fname = f"l{L}-{url.rsplit('/', 1)[1]}"
path = os.path.join(DATA, "attachments", "listicons", fname)
check(os.path.isfile(path), "stored below attachments/listicons (in backups)")
check(A.post(B + f"/api/lists/{L}/icon", files={"file": ("x.png", b"not a picture", "image/png")}).status_code == 400, "garbage refused")
check(Bo.post(B + f"/api/lists/{L}/icon", files={"file": ("x.png", png_bytes(), "image/png")}).status_code == 403, "member cannot upload")
r = A.put(B + f"/api/lists/{L}/icon", json={"preset": "coffee"})
check(r.ok and not os.path.exists(path), "a new icon removes the old file")
check(A.get(B + url).status_code == 404, "the old URL is gone")
r = A.delete(B + f"/api/lists/{L}/icon")
check(r.ok and r.json()["icon"] == "" and lst(A, L)["icon"] == "", "remove the icon")
# v1 API shows it too
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
A.put(B + f"/api/lists/{L}/icon", json={"preset": "plant"})
v = requests.get(V + f"/lists/{L}", headers={"Authorization": "Bearer " + tok}).json()
check(v.get("icon") == "/static/avatars/plant.svg", "v1 list has icon " + str(v.get("icon")))
spec = requests.get(V + "/openapi.json").json()
check("icon" in spec["components"]["schemas"]["List"]["properties"], "spec documents list.icon")
# deleting the list (from the archive) removes its picture file
L2 = A.post(B + "/api/lists", json={"name": "Tmp"}).json()["id"]
u2 = A.post(B + f"/api/lists/{L2}/icon", files={"file": ("x.png", png_bytes(40, 40), "image/png")}).json()["icon"]
p2 = os.path.join(DATA, "attachments", "listicons", f"l{L2}-{u2.rsplit('/', 1)[1]}")
A.patch(B + f"/api/lists/{L2}", json={"archived": 1})
check(os.path.isfile(p2) and A.delete(B + f"/api/lists/{L2}").ok and not os.path.exists(p2), "list deleted for good: icon file gone")

# ================================================================== /drop and /drop/drop
dt = A.get(B + "/api/me").json()["drop_token"]
for path_ in ("/drop", "/drop/drop"):
    r = requests.post(B + path_, headers={"Authorization": "Bearer " + dt}, data={"text": "Shared via " + path_})
    check(r.ok and "Shared via" in r.text, f"POST {path_} with the token: {r.status_code} {r.text[:60]}")
    check(requests.post(B + path_, headers={"Authorization": "Bearer wrong"}, data={"text": "x"}).status_code == 403, f"{path_}: wrong token 403")
titles = [t["title"] for t in A.get(B + "/api/state").json()["tasks"]]
check("Shared via /drop" in titles and "Shared via /drop/drop" in titles, "both landed in the inbox")
r = requests.post(B + "/drop/drop/drop", headers={"Authorization": "Bearer " + dt}, data={"text": "x"}, allow_redirects=False)
check(r.status_code != 200 and "Kalmido:" not in r.text, "no deeper alias")

# ================================================================== agent status task
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"}).json()
AT, CL = ag["token"], ag["id"]
ah = {"Authorization": "Bearer " + AT}
A.put(B + f"/api/lists/{L}/members", json={"user_id": CL, "role": "edit"})
T1 = A.post(B + "/api/tasks", json={"title": "Cut trailer", "list_id": L}).json()["id"]
LP = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]
TP = A.post(B + "/api/tasks", json={"title": "Private", "list_id": LP}).json()["id"]
r = requests.put(V + "/agent/status", headers=ah, json={"status": "working", "text": "Answering", "task_id": T1})
check(r.ok and r.json().get("status_task") == T1, "status with task_id " + r.text[:120])
a_ = next(x for x in A.get(B + "/api/agents").json()["agents"] if x["id"] == CL)
check(a_["status"] == "working" and a_["status_task"] == T1 and a_["job_tasks"] == [], "people see the task the agent works on")
check(requests.put(V + "/agent/status", headers=ah, json={"status": "working", "task_id": TP}).status_code == 400, "a task the agent cannot see: 400")
check(requests.put(V + "/agent/status", headers=ah, json={"status": "working", "task_id": "x"}).status_code == 400, "task_id must be a number")
check(requests.put(V + "/agent/status", headers=ah, json={"status": "working", "task_id": True}).status_code == 400, "task_id true refused")
# Carl does not share the list -> does not see the agent at all; Bob sees it
check(not [x for x in C.get(B + "/api/agents").json()["agents"] if x["id"] == CL], "carl does not see the agent")
check(next(x for x in Bo.get(B + "/api/agents").json()["agents"] if x["id"] == CL)["status_task"] == T1, "bob sees the status task")
# a task in a list bob cannot see: hidden for bob, visible for alice
L3 = A.post(B + "/api/lists", json={"name": "Agent only"}).json()["id"]
A.put(B + f"/api/lists/{L3}/members", json={"user_id": CL, "role": "edit"})
T3 = A.post(B + "/api/tasks", json={"title": "Secret", "list_id": L3}).json()["id"]
requests.put(V + "/agent/status", headers=ah, json={"status": "working", "task_id": T3})
check(next(x for x in Bo.get(B + "/api/agents").json()["agents"] if x["id"] == CL)["status_task"] is None, "bob: a task he cannot see is not named")
check(next(x for x in A.get(B + "/api/agents").json()["agents"] if x["id"] == CL)["status_task"] == T3, "alice: named")
r = requests.put(V + "/agent/status", headers=ah, json={"status": "idle", "task_id": T1})
check(r.ok and r.json()["status_task"] is None, "idle clears the task")
requests.put(V + "/agent/status", headers=ah, json={"status": "working", "text": "x"})
check(next(x for x in A.get(B + "/api/agents").json()["agents"] if x["id"] == CL)["status_task"] is None, "working without task_id: no task")
# running jobs
j = requests.post(V + "/agent/jobs", headers=ah, json={"title": "Rough cut", "task_id": T1, "state": "running"})
check(j.status_code in (200, 201), "job created")
a_ = next(x for x in Bo.get(B + "/api/agents").json()["agents"] if x["id"] == CL)
check(a_["job_tasks"] == [T1], "job_tasks lists the task of a running job " + str(a_.get("job_tasks")))
check(requests.get(V + "/agent", headers=ah).json().get("job_tasks") == [T1], "the agent sees it too")
check("status_task" in spec["components"]["schemas"]["Agent"]["properties"], "spec documents status_task")
body = spec["paths"]["/agent/status"]["put"]["requestBody"]["content"]["application/json"]["schema"]
check("task_id" in body["properties"], "spec: status body has task_id")

print(f"p202_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
