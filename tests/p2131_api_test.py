#!/usr/bin/env python3
"""2.13.1 API tests.
#465 files in the agent chat + agents read attachments:
 - a person sends images / files to an agent (multipart: body optional, task_id); the answer and the agent's chat event
   carry attachments (app address / REST address); the file comes back byte for byte with the sandbox CSP
 - only the two sides of a conversation fetch its files (another person, another agent: 404); only the sender removes one
   (a message left without text and files goes too)
 - limits: at most 10 files per message, the upload limit per file (TASKS_MAX_FILE_MB=1 in tests), no empty files, no
   empty message; a refused upload leaves no file on disk
 - the agent answers with files (multipart POST /api/v1/agent/chats/{uid}), the push names the files
 - GET /api/v1/tasks/{id}/attachments + GET /api/v1/attachments/{id}: an agent reads files of tasks it sees with their
   comments, never of lists it does not see, of tasks it does not see as a participant, of deleted comments or tasks in the
   trash; a person's token works the same way
 - POST /drop with to=agent: the files go into the chat with the agent (last chatted / id / username)
 - the admin storage check includes chat files (a damaged one: reported, 410)
 - OpenAPI documents the new paths and fields
#471 "Agent reads every comment":
 - listen_agent_ids on lists (web state + API v1); default = the tidy agent while tidying is on
 - a person's comment on a task the agent never touched -> 'comment' event for the listening agent; not for others, not
   for comments by agents, not for tasks the agent cannot see, a mention stays 'mention' (no double event)
 - PATCH (web / API v1): owner and list admins; agents 403, members 403, an agent that is not in the list 400
Starts its OWN container (start.sh).
usage: p2131_api_test.py <datadir>"""
import io
import os
import sqlite3
import subprocess
import sys
import time

import requests
from PIL import Image

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]


def legacy_agent(lid, aid, role):  # 2.26.0: one agent per list -- a second agent as in a list from before the update
    c_ = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c_.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')", (lid, aid, role, role))
    c_.commit()
    c_.close()


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


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=30, **k)


def png(color=(200, 30, 30)):
    b = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(b, "PNG")
    return b.getvalue()


def chat_dir_files():
    root = os.path.join(DATA, "attachments", "chat")
    return sorted(os.path.join(d, f) for d in (os.listdir(root) if os.path.isdir(root) else [])
                  for f in os.listdir(os.path.join(root, d)))


def events(api, since):
    r = api.req("GET", "/agent/events", params={"since": since, "limit": 500})
    assert r.ok, r.text
    j = r.json()
    return j["data"], j["cursor"]


r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ids = {"alice": 1}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for x in (A, Bo, Ca):
    x.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
AG, cl = r.json()["id"], Api(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "otto", "display_name": "Otto"})
AG2, ot = r.json()["id"], Api(r.json()["token"])
atok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()
alice_api = Api(atok.get("token") or atok.get("value"))

L1 = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]          # alice, bob (edit), claude (edit), otto (view)
L2 = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]       # alice only
L3 = A.post(B + "/api/lists", json={"name": "Shop"}).json()["id"]          # claude as participant
assert A.put(B + f"/api/lists/{L1}/members", json={"user_id": ids["bob"], "role": "edit"}).ok
assert A.put(B + f"/api/lists/{L1}/members", json={"user_id": AG, "role": "edit"}).ok
legacy_agent(L1, AG2, "view")
assert A.put(B + f"/api/lists/{L3}/members", json={"user_id": AG, "role": "participant"}).ok
assert A.put(B + f"/api/lists/{L3}/members", json={"user_id": ids["carol"], "role": "edit", "bridge_ok": True}).ok  # 2.30.0 (#919): Team + Shop differ
for lid in (L1, L3):  # 2.26.0: members may use the agents (list switch, default off)
    assert A.patch(B + f"/api/lists/{lid}", json={"agent_members": True, "agent_peers": True}).ok

# ================================================================== #465 chat files: person -> agent
_, cur = events(cl, 0)
P1, P2 = png(), png((20, 120, 40))
r = A.post(B + f"/api/agents/{AG}/chat", data={"body": "Look at this"},
           files=[("file", ("Screenshot 1.png", P1, "image/png")), ("file", ("notes.txt", b"line one\n", "text/plain"))])
check(r.status_code == 201, f"multipart chat message -> 201 ({r.status_code} {r.text[:200]})")
m1 = r.json()
att = m1.get("attachments") or []
check(m1["body"] == "Look at this" and [a["name"] for a in att] == ["Screenshot 1.png", "notes.txt"]
      and att[0]["mime"] == "image/png" and att[0]["size"] == len(P1) and att[0]["url"] == f"/api/chat-files/{att[0]['id']}",
      "answer: attachments with name / mime / size / app url")
F_IMG, F_TXT = att[0]["id"], att[1]["id"]
r = A.get(B + f"/api/chat-files/{F_IMG}?v={len(P1)}")
check(r.status_code == 200 and r.content == P1 and r.headers["Content-Type"] == "image/png"
      and "sandbox" in r.headers.get("Content-Security-Policy", "") and "max-age=86400" in r.headers.get("Cache-Control", ""),
      "person fetches the image: bytes, mime, sandbox CSP, versioned cache")
r = A.get(B + f"/api/chat-files/{F_TXT}?dl=1")
check(r.status_code == 200 and r.content == b"line one\n" and "attachment" in r.headers.get("Content-Disposition", ""), "?dl=1 -> download")
check(Bo.get(B + f"/api/chat-files/{F_IMG}").status_code == 404, "another person: 404")
evs, cur = events(cl, cur)
ch = [e for e in evs if e["event"] == "chat"]
check(len(ch) == 1 and [a["url"] for a in ch[0]["data"]["message"]["attachments"]] == [f"/api/v1/chat-attachments/{F_IMG}", f"/api/v1/chat-attachments/{F_TXT}"],
      "chat event: attachments with REST addresses")
r = cl.req("GET", f"/chat-attachments/{F_IMG}")
check(r.status_code == 200 and r.content == P1, "the agent of the conversation downloads the file")
check(ot.req("GET", f"/chat-attachments/{F_IMG}").status_code == 404, "another agent: 404")
check(alice_api.req("GET", f"/chat-attachments/{F_IMG}").status_code == 200, "the person's own token reads it too")
lst = cl.req("GET", "/agent/chats", params={"since": 0}).json()["data"]
check(any(m["id"] == m1["id"] and len(m["attachments"]) == 2 for m in lst), "GET /agent/chats carries attachments")
web = A.get(B + f"/api/agents/{AG}/chat").json()["messages"]
check(any(m["id"] == m1["id"] and m["attachments"][0]["url"].startswith("/api/chat-files/") for m in web), "the app's chat carries attachments")

# files only (empty body), task_id from the form
T1 = A.post(B + "/api/tasks", json={"title": "Login page", "list_id": L1}).json()["id"]
r = A.post(B + f"/api/agents/{AG}/chat", data={"task_id": str(T1)}, files=[("file", ("only.png", P2, "image/png"))])
check(r.status_code == 201 and r.json()["body"] == "" and r.json()["task_id"] == T1 and len(r.json()["attachments"]) == 1,
      "a message with only a file (empty body) and task_id from the form")
m2 = r.json()
# limits
n_disk = len(chat_dir_files())
r = A.post(B + f"/api/agents/{AG}/chat", data={"body": "x"}, files=[("file", (f"f{i}.txt", b"x", "text/plain")) for i in range(11)])
check(r.status_code == 400 and "10" in r.json().get("error", ""), "11 files -> 400")
r = A.post(B + f"/api/agents/{AG}/chat", data={"body": "big"}, files=[("file", ("ok.txt", b"ok", "text/plain")), ("file", ("big.bin", b"0" * (1024 * 1024 + 10), "application/octet-stream"))])
check(r.status_code == 400 and "big.bin" in r.json().get("error", ""), "a file over the limit -> 400")
check(len(chat_dir_files()) == n_disk, "a refused upload leaves no file on disk")
check(not any(m["body"] == "big" for m in A.get(B + f"/api/agents/{AG}/chat").json()["messages"]), "a refused upload leaves no message")
r = A.post(B + f"/api/agents/{AG}/chat", data={"body": "e"}, files=[("file", ("empty.txt", b"", "text/plain"))])
check(r.status_code == 400 or (r.status_code == 201 and not r.json()["attachments"]), "an empty file is refused (or dropped by the browser rules)")
r = A.post(B + f"/api/agents/{AG}/chat", data={"body": "  "})
check(r.status_code == 400, "no text and no files -> 400")
r = A.post(B + f"/api/agents/{AG}/chat", data={"body": "hi", "evil": "1"}, files=[("file", ("a.txt", b"a", "text/plain"))])
check(r.status_code == 400, "unknown form field -> 400")
check(A.post(B + f"/api/agents/{AG}/chat", json={"body": "plain json still works"}).status_code == 201, "JSON messages unchanged")

# ================================================================== agent -> person with files
_, cur = events(cl, cur)
r = cl.req("POST", f"/agent/chats/{ids['alice']}", data={"body": "Fixed, see after.png"}, files=[("file", ("after.png", P2, "image/png"))])
check(r.status_code == 201 and r.json()["from"] == "agent" and r.json()["attachments"][0]["url"].startswith("/api/v1/chat-attachments/"),
      "agent answers with a file (multipart)")
F_AG = r.json()["attachments"][0]["id"]
r = cl.req("POST", f"/agent/chats/{ids['alice']}", files=[("file", ("only.txt", b"log", "text/plain"))])
check(r.status_code == 201 and r.json()["body"] == "", "agent: files without text")
F_AG2, M_AG2 = r.json()["attachments"][0]["id"], r.json()["id"]
check(A.get(B + f"/api/chat-files/{F_AG}").content == P2, "the person sees the agent's file")
check(cl.req("POST", "/agent/chats/999", files=[("file", ("x.txt", b"x", "text/plain"))]).status_code == 404,
      "agent: files to an unknown person -> 404")
check(A.delete(B + f"/api/chat-files/{F_AG}").status_code == 403, "the person cannot remove the agent's file")
check(cl.req("DELETE", f"/chat-attachments/{F_IMG}").status_code == 403, "the agent cannot remove the person's file")
r = cl.req("DELETE", f"/chat-attachments/{F_AG2}")
check(r.status_code == 200 and r.json()["message"] is None, "the agent removes its own file; the empty message goes")
check(not any(m["id"] == M_AG2 for m in A.get(B + f"/api/agents/{AG}/chat").json()["messages"]), "that message is gone")
# the person removes own files
r = A.delete(B + f"/api/chat-files/{F_TXT}")
check(r.status_code == 200 and r.json()["message"]["id"] == m1["id"] and len(r.json()["message"]["attachments"]) == 1, "remove one of two files: message stays")
check(A.get(B + f"/api/chat-files/{F_TXT}").status_code == 404, "removed file: 404")
r = A.delete(B + f"/api/chat-files/{m2['attachments'][0]['id']}")
check(r.status_code == 200 and r.json()["message"] is None, "removing the only file of a message without text removes the message")

# ================================================================== task attachments for agents (#465)
T2 = A.post(B + "/api/tasks", json={"title": "Secret", "list_id": L2}).json()["id"]
T3a = A.post(B + "/api/tasks", json={"title": "Mine", "list_id": L3, "assignee_id": AG}).json()["id"]
T3b = A.post(B + "/api/tasks", json={"title": "Carols", "list_id": L3, "assignee_id": ids["carol"]}).json()["id"]


def upload(tid, name, data, mime):
    r = A.post(B + f"/api/tasks/{tid}/attachments", files=[("file", (name, data, mime))])
    assert r.ok, r.text
    return max(r.json()["attachments"], key=lambda a: a["id"])["id"]


A1 = upload(T1, "shot.png", P1, "image/png")
A2 = upload(T2, "private.png", P2, "image/png")
A3a = upload(T3a, "mine.txt", b"mine", "text/plain")
A3b = upload(T3b, "carol.txt", b"carol", "text/plain")
r = A.post(B + f"/api/tasks/{T1}/comments", data={"body": "with a file"}, files=[("file", ("c.txt", b"comment file", "text/plain"))])
assert r.ok, r.text
C1, AC1 = r.json()["id"], r.json()["attachments"][0]["id"]
r = cl.req("GET", f"/tasks/{T1}/attachments")
got = r.json().get("data", []) if r.ok else []
check(r.status_code == 200 and {a["id"] for a in got} == {A1, AC1}, "agent lists task + comment files")
check(any(a["id"] == AC1 and a["comment_id"] == C1 for a in got) and any(a["id"] == A1 and a["comment_id"] is None and a["url"] == f"/api/v1/attachments/{A1}" for a in got),
      "comment_id / url fields")
r = cl.req("GET", f"/attachments/{A1}")
check(r.status_code == 200 and r.content == P1 and r.headers["Content-Type"] == "image/png", "agent downloads a task file")
check(cl.req("GET", f"/attachments/{AC1}").content == b"comment file", "agent downloads a comment file")
# never lists it cannot see
check(cl.req("GET", f"/tasks/{T2}/attachments").status_code == 404, "agent: list of an unshared list's task -> 404")
check(cl.req("GET", f"/attachments/{A2}").status_code == 404, "agent: file of an unshared list -> 404")
check(ot.req("GET", f"/attachments/{A2}").status_code == 404, "other agent: file of an unshared list -> 404")
check(cl.req("GET", f"/chat-attachments/{A2}").status_code in (404, 403), "a task file id is no chat file")
# participant: only its own tasks
check(cl.req("GET", f"/attachments/{A3a}").status_code == 200, "participant agent: file of its own task")
check(cl.req("GET", f"/attachments/{A3b}").status_code == 404 and cl.req("GET", f"/tasks/{T3b}/attachments").status_code == 404,
      "participant agent: never files of other people's tasks")
# deleted comment, task in the trash
assert A.delete(B + f"/api/comments/{C1}").ok
check(cl.req("GET", f"/attachments/{AC1}").status_code == 404 and AC1 not in {a["id"] for a in cl.req("GET", f"/tasks/{T1}/attachments").json()["data"]},
      "file of a deleted comment: gone for the agent")
T4 = A.post(B + "/api/tasks", json={"title": "Trash", "list_id": L1}).json()["id"]
A4 = upload(T4, "t.txt", b"t", "text/plain")
assert A.delete(B + f"/api/tasks/{T4}").ok
check(cl.req("GET", f"/attachments/{A4}").status_code == 404 and cl.req("GET", f"/tasks/{T4}/attachments").status_code == 404, "task in the trash: 404")
check(alice_api.req("GET", f"/attachments/{A2}").content == P2, "a person's token reads files of own lists")
check(cl.req("GET", "/attachments/999999").status_code == 404, "unknown id: 404")
# view-only agent of the list sees files (with comments)
check(ot.req("GET", f"/attachments/{A1}").status_code == 200, "view-only agent of the list reads the file")

# ================================================================== /drop to=agent
dt = A.post(B + "/api/me/drop-token").json()["drop_token"]
r = requests.post(B + "/drop", headers={"Authorization": "Bearer " + dt}, data={"text": "from my phone", "to": "agent"},
                  files=[("file", ("phone.png", P1, "image/png"))])
check(r.status_code == 200 and "Claude" in r.text, f"/drop to=agent -> sent to the last chatted agent ({r.status_code} {r.text[:100]})")
last = A.get(B + f"/api/agents/{AG}/chat").json()["messages"][-1]
check(last["body"] == "from my phone" and last["attachments"][0]["name"] == "phone.png", "the drop landed in the chat")
r = requests.post(B + "/drop", headers={"Authorization": "Bearer " + dt}, data={"text": "x", "to": "nobody"})
check(r.status_code == 404, "/drop to an unknown agent -> 404")
r = requests.post(B + "/drop", headers={"Authorization": "Bearer " + dt}, data={"text": "to otto", "to": "otto"})
check(r.status_code == 200 and A.get(B + f"/api/agents/{AG2}/chat").json()["messages"][-1]["body"] == "to otto", "/drop to=<username>")
check(requests.post(B + "/drop", headers={"Authorization": "Bearer " + dt}, data={"text": "inbox"}).status_code == 200, "/drop without to: inbox as before")

# ================================================================== storage check, gc, OpenAPI
r = A.get(B + "/api/admin/storage-check").json()
check(r["checked"] >= 5 and not r["problems"], "storage check counts chat files, all fine")
con = sqlite3.connect(os.path.join(DATA, "tasks.db"))
path = con.execute("SELECT path FROM chat_files WHERE id=?", (F_IMG,)).fetchone()[0]
con.close()
with open(os.path.join(DATA, "attachments", path), "wb") as f:
    f.write(b"")
r = A.get(B + "/api/admin/storage-check").json()
check(any(p["kind"] == "chat_file" and p["id"] == F_IMG and p["problem"] == "empty" and p["where"] == "Claude" for p in r["problems"]),
      "storage check reports a damaged chat file")
check(A.get(B + f"/api/chat-files/{F_IMG}").status_code == 410, "damaged chat file: 410")
spec = requests.get(V + "/openapi.json").json()
check(all(p in spec["paths"] for p in ("/tasks/{id}/attachments", "/attachments/{id}", "/chat-attachments/{id}")), "OpenAPI: new paths")
check("multipart/form-data" in spec["paths"]["/agent/chats/{id}"]["post"]["requestBody"]["content"], "OpenAPI: chat answer as multipart")
check("attachments" in spec["components"]["schemas"]["ChatMessage"]["properties"], "OpenAPI: ChatMessage.attachments")
check("listen_agent_ids" in spec["components"]["schemas"]["List"]["properties"]
      and "listen_agent_ids" in spec["components"]["schemas"]["ListPatch"]["properties"], "OpenAPI: listen_agent_ids")

# ================================================================== #471 agent reads every comment
st = lambda s, lid: next(x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid)  # noqa: E731
check(st(A, L1)["listen_agent_ids"] == [], "default without tidy: nobody")
assert A.patch(B + f"/api/lists/{L1}", json={"agent_tidy": "suggest", "tidy_agent_id": AG}).ok
# 2.30.0 (#1034, intended change): tidying is its own switch, it no longer makes the tidy agent listen in
check(st(A, L1)["listen_agent_ids"] == [], "default with tidy on: still nobody (tidying is separate since 2.30)")
assert A.patch(B + f"/api/lists/{L1}", json={"listen_agent_ids": [AG]}).ok
check(alice_api.req("GET", f"/lists/{L1}").json().get("listen_agent_ids") == [AG], "API v1 list: listen_agent_ids")
T5 = A.post(B + "/api/tasks", json={"title": "Never touched by claude", "list_id": L1}).json()["id"]
_, cur = events(cl, 0)
_, cur2 = events(ot, 0)
assert Bo.post(B + f"/api/tasks/{T5}/comments", json={"body": "What about this?"}).ok
evs, cur = events(cl, cur)
ce = [e for e in evs if e["event"] == "comment" and e["data"]["task"]["id"] == T5]
check(len(ce) == 1 and ce[0]["data"]["comment"]["text"] == "What about this?", "listening agent gets the comment on a task it never touched")
evs2, cur2 = events(ot, cur2)
check(not [e for e in evs2 if e["event"] == "comment"], "a non-listening agent gets nothing")
# off
check(A.patch(B + f"/api/lists/{L1}", json={"listen_agent_ids": []}).ok and st(A, L1)["listen_agent_ids"] == [], "switched off (web)")
assert Bo.post(B + f"/api/tasks/{T5}/comments", json={"body": "Second"}).ok
evs, cur = events(cl, cur)
check(not [e for e in evs if e["event"] == "comment" and e["data"]["task"]["id"] == T5], "off: no event")
# rights
check(Bo.patch(B + f"/api/lists/{L1}", json={"listen_agent_ids": [AG]}).status_code == 403, "a member cannot change it")
check(cl.req("PATCH", f"/lists/{L1}", json={"listen_agent_ids": [AG]}).status_code == 403, "an agent token cannot change it")
check(alice_api.req("PATCH", f"/lists/{L1}", json={"listen_agent_ids": [ids["bob"]]}).status_code == 400, "a person is no agent -> 400")
check(alice_api.req("PATCH", f"/lists/{L1}", json={"listen_agent_ids": "3"}).status_code == 400, "wrong type -> 400")
r = alice_api.req("PATCH", f"/lists/{L1}", json={"listen_agent_ids": [AG, AG2]})
check(r.status_code == 200 and r.json()["listen_agent_ids"] == [AG, AG2], "owner token sets two agents (API v1)")
# both get it; an agent's comment triggers nothing; a mention stays one 'mention'
assert Bo.post(B + f"/api/tasks/{T5}/comments", json={"body": "Third"}).ok
evs, cur = events(cl, cur)
evs2, cur2 = events(ot, cur2)
check(len([e for e in evs if e["event"] == "comment"]) == 1 and len([e for e in evs2 if e["event"] == "comment"]) == 1, "both listening agents get it")
assert ot.req("POST", f"/tasks/{T5}/comments", json={"body": "agent note"}).status_code == 201
evs, cur = events(cl, cur)
check(not [e for e in evs if e["event"] == "comment"], "comments by agents trigger nothing")
assert Bo.post(B + f"/api/tasks/{T5}/comments", json={"body": f"<@{AG}> please look"}).ok
evs, cur = events(cl, cur)
kinds = [e["event"] for e in evs if e["event"] in ("comment", "mention")]
check(kinds == ["mention"], f"a mention stays one mention event ({kinds})")
# participant agent: only tasks it can see
assert A.patch(B + f"/api/lists/{L3}", json={"listen_agent_ids": [AG]}).ok
assert Ca.post(B + f"/api/tasks/{T3b}/comments", json={"body": "carol's own"}).ok
assert Ca.post(B + f"/api/tasks/{T3a}/comments", json={"body": "on claude's task"}).ok
evs, cur = events(cl, cur)
got = [e["data"]["task"]["id"] for e in evs if e["event"] == "comment"]
check(got == [T3a], f"participant listener: only the task it can see ({got})")
check(alice_api.req("PATCH", f"/lists/{L2}", json={"listen_agent_ids": [AG]}).status_code == 400, "an agent not in the list -> 400")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
subprocess.run(["docker", "rm", "-f", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)
sys.exit(1 if FAILS else 0)
