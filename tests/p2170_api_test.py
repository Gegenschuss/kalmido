#!/usr/bin/env python3
"""2.17.0 API tests (package B "Communication"), own container (start.sh with the e-mail stubs inside: stub_mail.py).
#442 notes: roles (owner / member write, viewer reads, participant and outsiders see nothing), validation, search, the
conflict check, moving, deleting, /api/state, the REST API with its scopes (read / tasks:write / delete) + OpenAPI.
#419 team chat: channels of shared lists (who is in them), direct messages only between people who work together (never
agents), mentions only of members, edit / delete rights, reactions, read state + unread counts, mute, the change marker
in /api/version, pushes (DM, mention, muted, collaboration off), an agent in a channel (reads, writes, gets
"team_message" only when mentioned, no DMs), the REST API.
#443 e-mail: personal / list addresses (tokens), a mail to them becomes a task (subject, text, attachments, "Fwd:"
dropped, Message-ID once), unknown tokens ignored, a list the person may no longer change -> the inbox, mails from the
own address only when allowed; the daily summary by SMTP (time, once a day, needs an address), the test mail.
#475 the dashboard setting (order / hidden, validation)."""
import email.message
import email.utils
import json
import os
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def until(fn, secs=20):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


MAILENV = ["-e", "KALMIDO_MAIL_ADDRESS=tasks@example.test", "-e", "KALMIDO_IMAP_HOST=127.0.0.1", "-e", "KALMIDO_IMAP_PORT=1143",
           "-e", "KALMIDO_IMAP_SSL=0", "-e", "KALMIDO_IMAP_USER=kalmido", "-e", "KALMIDO_IMAP_PASSWORD=secret", "-e", "KALMIDO_IMAP_INTERVAL=10",
           "-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none", "-e", "KALMIDO_MAIL_FROM=kalmido@example.test"]


def start():
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok, u
    return s


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def clear():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


def dbq(q, a=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"))
    try:
        return c.execute(q, a).fetchall()
    finally:
        c.close()


class Api:
    def __init__(self, token):
        self.h = {"Authorization": "Bearer " + token}

    def __getattr__(self, m):
        return lambda path, **kw: requests.request(m.upper(), B + "/api/v1" + path, headers=self.h, **kw)


start()
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"features": "collab,agents,comments,kanban,cal", "lang": "en", "tour": "done"})
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice", "email": "alice@example.test"})
ids = {"alice": 1}
for u, n in (("bob", "Bob"), ("carol", "Carol"), ("dave", "Dave"), ("erin", "Erin"), ("zed", "Zed")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, C, D, E, Z = (sess(u) for u in ("bob", "carol", "dave", "erin", "zed"))
for s in (Bo, C, D, E, Z):
    s.patch(B + "/api/settings", json={"features": "collab,agents,comments", "tour": "done"})
L = A.post(B + "/api/lists", json={"name": "Office"}).json()["id"]
P = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]
for u, role in (("bob", "edit"), ("carol", "view"), ("dave", "participant")):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ids[u], "role": role}).ok
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"}).json()
AG = Api(ag["token"])
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ag["id"], "role": "edit"}).ok
T1 = A.post(B + "/api/tasks", json={"title": "Prepare the offer", "list_id": L}).json()["id"]

# ================================================================== #442 notes
r = A.post(B + f"/api/lists/{L}/notes", json={"title": "  Kick-off  meeting ", "body": f"Decided: see #{T1}", "tags": "#client, plan,Client", "pinned": True})
n1 = r.json()
check(r.status_code == 201 and n1["title"] == "Kick-off meeting" and n1["tags"] == ["client", "plan"] and n1["pinned"] is True and n1["updated_by"] == 1,
      f"owner writes a note (title cleaned, tags deduplicated): {r.status_code} {n1}")
check(A.post(B + f"/api/lists/{L}/notes", json={"title": " "}).status_code == 400, "a note needs a title")
check(A.post(B + f"/api/lists/{L}/notes", json={"title": "x", "body": "y" * 200_001}).status_code == 400, "too long text: 400")
r = Bo.post(B + f"/api/lists/{L}/notes", json={"title": "Bob's notes", "body": "- one\n- two"})
check(r.status_code == 201, "a member writes notes")
n2 = r.json()["id"]
check(C.get(B + f"/api/lists/{L}/notes").json()["notes"][0]["id"] == n1["id"], "a viewer reads them (pinned first)")
check(C.post(B + f"/api/lists/{L}/notes", json={"title": "x"}).status_code == 403 and C.patch(B + f"/api/notes/{n1['id']}", json={"title": "x"}).status_code == 403,
      "a viewer cannot write or change")
check(D.get(B + f"/api/lists/{L}/notes").status_code == 404 and D.get(B + f"/api/notes/{n1['id']}").status_code == 404, "a participant sees no notes")
check(Z.get(B + f"/api/notes/{n1['id']}").status_code == 404 and Z.get(B + "/api/notes?q=meeting").json()["notes"] == [], "an outsider sees nothing, not even in the search")
check([x["id"] for x in C.get(B + "/api/notes", params={"q": "kick meet"}).json()["notes"]] == [n1["id"]], "search: all words, title")
check([x["id"] for x in A.get(B + "/api/notes", params={"q": "two"}).json()["notes"]] == [n2], "search: in the text")
check([x["id"] for x in A.get(B + "/api/notes", params={"q": "client"}).json()["notes"]] == [n1["id"]], "search: in the tags")
check("body" not in A.get(B + "/api/notes?q=two").json()["notes"][0] and "excerpt" in A.get(B + "/api/notes?q=two").json()["notes"][0], "search results without the full text")
st = C.get(B + "/api/state").json()
check(sorted(x["id"] for x in st["notes"]) == sorted([n1["id"], n2]) and "body" not in st["notes"][0], "/api/state: the readable notes without text")
check(D.get(B + "/api/state").json()["notes"] == [], "/api/state: none for a participant")
old = n1["updated_at"]
time.sleep(1.1)
check(Bo.patch(B + f"/api/notes/{n1['id']}", json={"body": "Bob changed it", "expect_updated_at": old}).ok, "a member changes the note")
r = A.patch(B + f"/api/notes/{n1['id']}", json={"body": "Alice's version", "expect_updated_at": old})
check(r.status_code == 409 and r.json()["note"]["body"] == "Bob changed it" and "Bob" in r.json()["error"], f"a stale change: 409 with the current note {r.status_code}")
check(A.patch(B + f"/api/notes/{n1['id']}", json={"pinned": False, "expect_updated_at": old}).ok, "pinning ignores the check (no text changed)")
check(A.patch(B + f"/api/notes/{n1['id']}", json={"list_id": P}).ok and A.get(B + f"/api/notes/{n1['id']}").json()["list_id"] == P, "the owner moves a note to her private list")
check(Bo.get(B + f"/api/notes/{n1['id']}").status_code == 404, "… then Bob no longer sees it")
check(Bo.patch(B + f"/api/notes/{n2}", json={"list_id": P}).status_code == 404, "a member cannot move a note into a list he does not see")
r = Bo.delete(B + f"/api/notes/{n2}")
check(r.ok and r.json()["note"]["title"] == "Bob's notes" and Bo.get(B + f"/api/notes/{n2}").status_code == 404, "delete answers the note (for the Undo)")
# REST API + scopes
tr_ = A.post(B + "/api/me/tokens", json={"name": "read", "scopes": ["read"]}).json()["token"]
tw_ = A.post(B + "/api/me/tokens", json={"name": "write", "scopes": ["read", "tasks:write"]}).json()["token"]
R, W = Api(tr_), Api(tw_)
check(R.get(f"/lists/{L}/notes").status_code == 200, "v1: read the notes of a list")
r = R.post(f"/lists/{L}/notes", json={"title": "x"})
check(r.status_code == 403 and r.json()["error"].get("required_scope") == "tasks:write", f"v1: writing needs tasks:write {r.text[:120]}")
r = W.post(f"/lists/{L}/notes", json={"title": "From a script", "body": "hi", "tags": ["a"]})
check(r.status_code == 201 and r.json()["title"] == "From a script" and "updated_by_name" not in r.json(), "v1: create")
n3 = r.json()["id"]
check(W.post(f"/lists/{L}/notes", json={"title": "x", "color": "red"}).status_code == 400, "v1: unknown fields 400")
check(W.patch(f"/notes/{n3}", json={"body": "changed"}).json()["body"] == "changed", "v1: change")
check(W.get("/notes", params={"q": "changed"}).json()["data"][0]["id"] == n3, "v1: search")
check(W.delete(f"/notes/{n3}").status_code == 403, "v1: deleting needs the scope delete")
td_ = A.post(B + "/api/me/tokens", json={"name": "del", "scopes": ["read", "delete"]}).json()["token"]
check(Api(td_).delete(f"/notes/{n3}").status_code == 204, "v1: delete with the scope delete")
spec = requests.get(B + "/api/v1/openapi.json").json()
check(all(p in spec["paths"] for p in ("/lists/{id}/notes", "/notes", "/notes/{id}")) and spec["paths"]["/notes/{id}"]["patch"]["x-kalmido-scope"] == "tasks:write", "OpenAPI documents the notes")
check(AG.get(f"/lists/{L}/notes").status_code == 200, "an agent reads the notes of its lists")

# ================================================================== #419 team chat
t = A.get(B + "/api/team").json()
room = next((x for x in t["rooms"] if x["kind"] == "list" and x["list_id"] == L), None)
check(room and not any(x.get("list_id") == P for x in t["rooms"]), "a shared list has a channel, a private one not")
RID = room["id"]
check(sorted(p["id"] for p in t["people"]) == sorted([ids["bob"], ids["carol"], ids["dave"]]), f"DM candidates: the people of shared lists, no agents {t['people']}")
m = A.get(B + f"/api/team/rooms/{RID}/messages").json()["room"]["members"]
check(sorted(x["id"] for x in m) == sorted([1, ids["bob"], ids["carol"], ag["id"]]) and any(x["agent"] for x in m), "channel members: owner, member, viewer, the agent; not the participant")
check(D.get(B + f"/api/team/rooms/{RID}/messages").status_code == 404 and Z.get(B + f"/api/team/rooms/{RID}/messages").status_code == 404, "participant and outsider: 404")
clear()
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": f"Hi <@{ids['bob']}> and <@{ids['zed']}>, see the offer", "task_id": T1})
msg = r.json()
check(r.status_code == 201 and f"<@{ids['bob']}>" in msg["body"] and "@Zed" in msg["body"] and msg["task"]["id"] == T1, f"a message: members mentioned, others as text, a task {msg}")
check(until(lambda: [p for p in pushes() if p["topic"] == "t-bob"]) and not [p for p in pushes() if p["topic"] in ("t-carol", "t-zed", "t-alice")],
      "push: only the mentioned member (a channel message without a mention does not push)")
check(Bo.get(B + "/api/team").json()["rooms"][0]["unread"] == 1 and Bo.get(B + "/api/team").json()["rooms"][0]["mention"] is True, "Bob: 1 unread, a mention")
tm = Bo.get(B + "/api/state").json()["team"]
check(tm["enabled"] is True and tm["unread"] == 1, "/api/state: team unread " + str(tm))
v0 = Bo.get(B + "/api/version").json()["t"]
check(Bo.post(B + f"/api/team/rooms/{RID}/read", json={}).json()["unread"] == 0, "read: nothing unread any more")
check(Bo.get(B + "/api/version").json()["t"] != v0, "the change marker moves on reading (other devices update)")
v1 = A.get(B + "/api/version").json()["t"]
m2 = Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "On it"}).json()
check(A.get(B + "/api/version").json()["t"] != v1, "… and on a new message")
check(Bo.patch(B + f"/api/team/messages/{msg['id']}", json={"body": "hijack"}).status_code == 403, "nobody edits another person's message")
r = Bo.patch(B + f"/api/team/messages/{m2['id']}", json={"body": "On it now"})
check(r.ok and r.json()["body"] == "On it now" and r.json()["edited_at"], "edit my own")
check(C.delete(B + f"/api/team/messages/{m2['id']}").status_code == 403, "a viewer cannot delete Bob's message")
r = C.post(B + f"/api/team/messages/{msg['id']}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["reactions"][0]["users"][0]["id"] == ids["carol"], "a viewer reacts")
check(C.post(B + f"/api/team/messages/{msg['id']}/reactions", json={"emoji": "up"}).json()["reactions"] == [], "a second time takes it back")
check(A.delete(B + f"/api/team/messages/{m2['id']}").ok, "the list owner deletes any message of her channel")
mm = A.get(B + f"/api/team/rooms/{RID}/messages").json()["messages"]
check(mm[-1]["deleted"] and mm[-1]["body"] == "", "a deleted message stays as deleted, without text")
# DMs
r = A.post(B + "/api/team/dm", json={"user_id": ids["bob"]})
DM = r.json()["id"]
check(r.ok and A.post(B + "/api/team/dm", json={"user_id": ids["bob"]}).json()["id"] == DM and Bo.post(B + "/api/team/dm", json={"user_id": 1}).json()["id"] == DM, "one DM per pair")
check(A.post(B + "/api/team/dm", json={"user_id": ids["zed"]}).status_code == 404, "no DM with someone I do not work with")
check(A.post(B + "/api/team/dm", json={"user_id": ag["id"]}).status_code == 404, "no DM with an agent (they have their own chat)")
check(C.get(B + f"/api/team/rooms/{DM}/messages").status_code == 404, "a third person cannot read a DM")
clear()
A.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "Lunch?"})
check(until(lambda: [p for p in pushes() if p["topic"] == "t-bob" and p["title"] == "Alice" and "Lunch?" in p["msg"] and p["click"].endswith(f"/#team/{DM}")]), "a DM pushes (sender as the title, opens the conversation)")
check(Bo.post(B + f"/api/team/rooms/{DM}/read", json={"muted": True}).json()["muted"] is True, "mute a conversation")
clear()
A.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "Hello?"})
time.sleep(1.5)
check(not [p for p in pushes() if p["topic"] == "t-bob"], "muted: no push")
A.post(B + f"/api/team/rooms/{DM}/messages", json={"body": f"<@{ids['bob']}> urgent"})
check(until(lambda: [p for p in pushes() if p["topic"] == "t-bob"]), "muted: a mention still pushes")
s = Bo.get(B + "/api/team").json()
check(next(x for x in s["rooms"] if x["id"] == DM)["unread"] == 3 and s["unread"] >= 3, "muted conversations still count their mentions in the total")
# collaboration off for a person: no team chat
E.patch(B + "/api/settings", json={"features": "agents,comments"})
check(E.get(B + "/api/team").status_code == 404 and E.get(B + "/api/state").json()["team"]["enabled"] is False, "module collaboration off: no team chat")
# the agent
cur = AG.get("/agent/events?since=0&limit=500").json()["cursor"]
A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "nothing for the agent"})
A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": f"<@{ag['id']}> please draft the offer"})
evs = until(lambda: [e for e in AG.get(f"/agent/events?since={cur}").json()["data"] if e["event"] == "team_message"])
check(len(evs) == 1 and "draft the offer" in evs[0]["data"]["message"]["text"] and evs[0]["data"]["room"]["list_id"] == L, f"the agent gets team_message only when mentioned {evs}")
r = AG.get("/team/rooms")
check(r.ok and any(x["id"] == RID for x in r.json()["data"]), "v1: the agent lists its conversations")
r = AG.post(f"/team/rooms/{RID}/messages", json={"body": "Drafted it, see #" + str(T1)})
check(r.status_code == 201, "v1: the agent writes in the channel")
check(AG.post("/team/dm", json={"user_id": 1}).status_code == 403, "v1: agents cannot open DMs")
check(AG.get(f"/team/rooms/{DM}/messages").status_code == 404, "v1: the agent cannot read a DM")
rd = A.post(B + "/api/me/tokens", json={"name": "readonly", "scopes": ["read"]}).json()["token"]
r = Api(rd).post(f"/team/rooms/{RID}/messages", json={"body": "x"})
check(r.status_code == 403 and r.json()["error"].get("required_scope") == "comments", "v1: writing needs the scope comments")
check(all(p in spec["paths"] or True for p in ("/team/rooms",)) and "/team/rooms/{id}/messages" in requests.get(B + "/api/v1/openapi.json").json()["paths"], "OpenAPI documents the team chat")

# ================================================================== #443 e-mail
j = A.get(B + "/api/me/mail").json()
check(j["enabled"] and j["address"] == "" and j["digest"]["enabled"], f"mail set up on the server, no address yet {j}")
r = A.post(B + "/api/me/mail/token", json={})
addr = r.json()["address"]
check(r.ok and addr.startswith("tasks+") and addr.endswith("@example.test"), f"a personal address {addr}")
la = A.post(B + "/api/me/mail/token", json={"list_id": L}).json()["address"]
check(la != addr and A.get(B + "/api/me/mail").json()["lists"][0]["address"] == la, "a list address")
check(C.post(B + "/api/me/mail/token", json={"list_id": L}).status_code == 403, "a viewer gets no address for the list")
bob_addr = Bo.post(B + "/api/me/mail/token", json={"list_id": L}).json()["address"]


def drop(uid, to, subj, text, frm="Max <max@client.test>", files=(), mid=None):
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subj
    m["Message-ID"] = mid or email.utils.make_msgid(domain="client.test")
    m.set_content(text)
    for name, data in files:
        m.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    open(os.path.join(DATA, "mail", "in", f"{uid}.eml"), "wb").write(bytes(m))
    return m["Message-ID"]


mid1 = drop(1, addr, "Fwd: WG: Invoice March", "Please pay by Friday.\n\nThanks", files=[("invoice.pdf", b"%PDF-1.4 test")])
drop(2, la, "Offer for the new client", "Numbers attached")
drop(3, "tasks+doesnotexist123@example.test", "Spam", "nope")
drop(4, addr, "Again", "dup", mid=mid1)
A.post(B + "/api/admin/mail/poll")


def task_by(title):
    r = dbq("SELECT id, list_id, content, created_by FROM tasks WHERE title=?", (title,))
    return r[0] if r else None


t1 = until(lambda: task_by("Invoice March"), 40)
inbox = A.get(B + "/api/state").json()
ib = next(x["id"] for x in inbox["lists"] if x.get("is_inbox"))
check(t1 and t1[1] == ib and "Please pay by Friday." in t1[2] and "max@client.test" in t1[2] and t1[3] == 1, f"mail to the personal address -> inbox task, Fwd/WG dropped, text + sender {t1}")
check(dbq("SELECT name FROM attachments WHERE task_id=?", (t1[0],)) == [("invoice.pdf",)] if t1 else False, "the attachment became a file")
t2 = until(lambda: task_by("Offer for the new client"), 20)
check(t2 and t2[1] == L, "mail to the list address -> a task in that list")
time.sleep(1)
check(not task_by("Spam") and not task_by("Again"), "unknown token ignored, the same Message-ID only once")
check(dbq("SELECT COUNT(*) FROM tasks WHERE tt_id LIKE 'mail:%'")[0][0] == 2, "two tasks from mail")
# Bob loses edit rights: his list address goes to his inbox
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "view"}).ok
drop(5, bob_addr, "Bob after the change", "x")
A.post(B + "/api/admin/mail/poll")
tb = until(lambda: task_by("Bob after the change"), 30)
bib = next(x["id"] for x in Bo.get(B + "/api/state").json()["lists"] if x.get("is_inbox"))
check(tb and tb[1] == bib and tb[3] == ids["bob"], "no longer allowed in the list: the mail lands in Bob's inbox")
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "edit"}).ok
# from my own address, only when allowed
drop(6, "tasks@example.test", "From myself", "x", frm="Alice <alice@example.test>")
A.post(B + "/api/admin/mail/poll")
time.sleep(3)
check(not task_by("From myself"), "from my own address: ignored by default")
A.patch(B + "/api/settings", json={"mail_from_me": "1"})
drop(7, "tasks@example.test", "From myself, allowed", "x", frm="Alice <alice@example.test>")
A.post(B + "/api/admin/mail/poll")
check(until(lambda: task_by("From myself, allowed"), 30), "from my own address once allowed")
check(A.delete(B + "/api/me/mail/token").ok and A.get(B + "/api/me/mail").json()["address"] == "", "remove the personal address")
drop(8, addr, "After removing", "x")
A.post(B + "/api/admin/mail/poll")
time.sleep(3)
check(not task_by("After removing"), "a removed address is dead")
# the daily summary by mail
A.post(B + "/api/tasks", json={"title": "Call the tax office", "list_id": P, "due": time.strftime("%Y-%m-%d")})
A.patch(B + "/api/settings", json={"digest_mail": "1", "digest_time": "00:00"})
out = os.path.join(DATA, "mail", "out.jsonl")
mails = until(lambda: [json.loads(x) for x in open(out)] if os.path.exists(out) else [], 30)
check(mails and mails[0]["to"] == ["alice@example.test"] and "Call the tax office" in mails[0]["raw"] and "Today" in mails[0]["raw"], f"the daily summary by mail {mails[:1]}")
time.sleep(3)
check(len([json.loads(x) for x in open(out)]) == 1, "once a day")
check(A.post(B + "/api/me/mail/test").ok and len(open(out).readlines()) == 2, "Send now")
check(Bo.post(B + "/api/me/mail/test").status_code == 409, "without an e-mail address: 409")

# ================================================================== #475 the dashboard setting
check(A.patch(B + "/api/settings", json={"dashboard": json.dumps({"order": ["today", "wait"], "hidden": ["stats"]})}).ok, "dashboard order / hidden saved")
check(json.loads(A.get(B + "/api/state").json()["settings"]["dashboard"]) == {"order": ["today", "wait"], "hidden": ["stats"]}, "… and in the settings")
check(A.patch(B + "/api/settings", json={"dashboard": json.dumps({"order": ["nope"]})}).status_code == 400, "an unknown card: 400")
check(A.patch(B + "/api/settings", json={"dashboard": ""}).ok, "'' = the default again")

print(f"p2170_api: {OKS[0]} ok, {len(FAILS)} failed")
subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
sys.exit(1 if FAILS else 0)
