#!/usr/bin/env python3
"""2.113.1 API tests, part B (#2059): team chat channels anyone may open, group conversations, files in team chat messages.
Invented names only.
 - channels: open (every person of the organisation reads / joins) vs. invited only; rename / archive / restore / members by the
   creator or an organisation admin only; no person or agent of another organisation; an archived channel takes no messages
 - groups: three or more people who all work with each other; a person who does not work with every member is refused; leave
 - files: multipart messages (also files only), attachments with their address, served to whoever sees the conversation
   (404 for others), at most 10 per message, empty files refused, deleting the message takes them off the disk; agents
   (members only) read and send them through the REST API; an end-to-end encrypted DM refuses files
 - search, reply quotes, "save as task" and pushes keep working in the new rooms; agents cannot open channels / groups
 - a person without an organisation: a private channel with the people they work with (freelancer-matrix: team)
usage: p2113b_b_api_test.py <datadir>      (a fresh container; P2113BB_NOSTART=1 = the server already runs)"""
import base64
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


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


if not os.environ.get("P2113BB_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta"}).json()["id"]
ids = {}
for u, o in (("bob", ORG), ("carol", ORG), ("dave", ORG), ("eve", BETA)):
    r = A.post(B + "/api/users", json={"orgs": [o], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, EVE = ids["bob"], ids["carol"], ids["dave"], ids["eve"]
Bo, Ca, Da, Ev = sess("bob"), sess("carol"), sess("dave"), sess("eve")
for x in (A, Bo, Ca, Da, Ev):
    x.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude", "org_id": ORG})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "otto", "display_name": "Otto", "org_id": BETA})
OT, OTH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
# alice, bob and carol work together (a shared list); dave is in the organisation but shares nothing with them
TEAM = A.post(B + "/api/lists", json={"name": "Team", "org_id": ORG}).json()["id"]
for uid in (BOB, CAROL):
    assert A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": uid, "role": "edit"}).ok


def j(r):
    try:
        return r.json()
    except ValueError:
        return {}


def msgs(s, rid):
    return s.get(B + f"/api/team/rooms/{rid}/messages").json()["messages"]


def files_post(s, rid, files, body=None, url=None):
    data = {"body": body} if body is not None else {}
    return s.post(url or (B + f"/api/team/rooms/{rid}/messages"), data=data, files=[("file", f) for f in files])


# ================================================================== channels
r = A.post(B + "/api/team/channels", json={"name": "  General  ", "org_id": ORG, "open": True, "members": [BOB]})
check(r.status_code == 201 and r.json()["kind"] == "channel" and r.json()["name"] == "General" and r.json()["open"] is True
      and r.json()["members"] == 2 and r.json()["manage"] is True, "channel: created open in the organisation " + r.text[:300])
GEN = j(r).get("id")
check(A.post(B + "/api/team/channels", json={"name": "", "org_id": ORG}).status_code == 400, "channel: a name is needed")
check(Bo.post(B + "/api/team/channels", json={"name": "X", "org_id": BETA}).status_code == 400, "channel: not in an organisation I am not in")
check(A.post(B + "/api/team/channels", json={"name": "X", "open": True}).status_code == 400, "channel: a private channel cannot be open")
check(Ev.post(B + "/api/team/channels", json={"name": "X", "org_id": ORG}).status_code == 400, "channel: eve (Beta) cannot open one in Alpha")
r = A.post(B + "/api/team/channels", json={"name": "Mixed", "org_id": ORG, "members": [EVE]})
check(r.status_code == 400 and "not in the organisation" in r.text, "channel: a person of another organisation cannot be invited " + r.text[:200])
check(not any(x["name"] == "Mixed" for x in A.get(B + "/api/team/channels").json()["channels"]), "channel: a refused create leaves nothing behind")
rooms = {x["id"]: x for x in Bo.get(B + "/api/team").json()["rooms"]}
check(GEN in rooms and rooms[GEN]["kind"] == "channel" and rooms[GEN]["name"] == "General", "channel: in bob's conversations (no message yet) " + str(rooms.get(GEN))[:200])
# an open channel: carol (not invited) sees it, reads it, writing joins her
ch = Ca.get(B + "/api/team/channels").json()
cg = next((x for x in ch["channels"] if x["id"] == GEN), None)
check(cg is not None and cg["joined"] is False and cg["manage"] is False, "open channel: listed for carol, not joined " + str(cg)[:200])
check(ORG in [o["id"] for o in ch["orgs"]] and DAVE in next(o for o in ch["orgs"] if o["id"] == ORG)["people"], "channels: whom I may add (organisation people)")
check(Ca.get(B + f"/api/team/rooms/{GEN}/messages").status_code == 200, "open channel: carol reads it")
check(GEN not in {x["id"] for x in Ca.get(B + "/api/team").json()["rooms"]}, "open channel: not in carol's conversations before she joins")
r = Ca.post(B + f"/api/team/rooms/{GEN}/messages", json={"body": "Hello all"})
check(r.status_code == 201, "open channel: carol writes " + r.text[:200])
check(GEN in {x["id"] for x in Ca.get(B + "/api/team").json()["rooms"]}, "open channel: writing joined carol")
for s, who in ((Ev, "eve (Beta)"),):
    check(s.get(B + f"/api/team/rooms/{GEN}/messages").status_code == 404, f"open channel: {who} cannot read it")
    check(s.post(B + f"/api/team/rooms/{GEN}/messages", json={"body": "x"}).status_code == 404, f"open channel: {who} cannot write")
    check(not any(x["id"] == GEN for x in s.get(B + "/api/team/channels").json()["channels"]), f"open channel: not listed for {who}")
check(Ev.post(B + f"/api/team/rooms/{GEN}/members", json={"user_id": EVE}).status_code == 404, "open channel: eve cannot join")
# invited only
r = Bo.post(B + "/api/team/channels", json={"name": "Secret", "org_id": ORG, "members": [CAROL]})
SEC = j(r).get("id")
check(r.status_code == 201 and r.json()["open"] is False, "closed channel: bob opens it with carol")
check(Da.get(B + f"/api/team/rooms/{SEC}/messages").status_code == 404, "closed channel: dave (same organisation, not invited) cannot read it")
check(not any(x["id"] == SEC for x in Da.get(B + "/api/team/channels").json()["channels"]), "closed channel: not listed for dave")
check(Da.post(B + f"/api/team/rooms/{SEC}/members", json={"user_id": DAVE}).status_code == 404, "closed channel: dave cannot join")
check(Ca.post(B + f"/api/team/rooms/{SEC}/members", json={"user_id": DAVE}).status_code == 403, "closed channel: carol (member) cannot invite")
check(Ca.patch(B + f"/api/team/rooms/{SEC}", json={"name": "Mine"}).status_code == 403, "closed channel: carol cannot rename")
check(Ca.patch(B + f"/api/team/rooms/{SEC}", json={"archived": True}).status_code == 403, "closed channel: carol cannot archive")
r = Bo.patch(B + f"/api/team/rooms/{SEC}", json={"name": "Secret plans"})
check(r.ok and r.json()["name"] == "Secret plans", "closed channel: bob (creator) renames it")
r = Bo.post(B + f"/api/team/rooms/{SEC}/members", json={"user_id": DAVE})
check(r.ok and r.json()["members"] == 3, "closed channel: bob invites dave " + r.text[:200])
check(Da.get(B + f"/api/team/rooms/{SEC}/messages").status_code == 200, "closed channel: dave reads it once invited")
check(Bo.post(B + f"/api/team/rooms/{SEC}/members", json={"user_id": EVE}).status_code == 400, "closed channel: no person of Beta")
r = A.patch(B + f"/api/team/rooms/{SEC}", json={"open": True})
check(r.ok and r.json()["open"] is True, "an organisation admin (alice) manages bob's channel " + r.text[:200])
A.patch(B + f"/api/team/rooms/{SEC}", json={"open": False})
r = Bo.delete(B + f"/api/team/rooms/{SEC}/members/{DAVE}")
check(r.ok and Da.get(B + f"/api/team/rooms/{SEC}/messages").status_code == 404, "closed channel: bob removes dave, dave reads nothing")
check(Ca.delete(B + f"/api/team/rooms/{SEC}/members/{BOB}").status_code == 403, "closed channel: carol cannot remove bob")
# archive / restore
r = Bo.patch(B + f"/api/team/rooms/{SEC}", json={"archived": True})
check(r.ok and r.json()["archived"] is True, "archive: bob archives his channel")
check(Ca.post(B + f"/api/team/rooms/{SEC}/messages", json={"body": "x"}).status_code == 409, "archive: no new messages")
check(SEC not in {x["id"] for x in Ca.get(B + "/api/team").json()["rooms"]}, "archive: gone from the conversations")
check(Ca.get(B + f"/api/team/rooms/{SEC}/messages").status_code == 200, "archive: the members still read it")
check(any(x["id"] == SEC and x["archived"] for x in Bo.get(B + "/api/team/channels").json()["channels"]), "archive: listed for bob (restore)")
r = Bo.patch(B + f"/api/team/rooms/{SEC}", json={"archived": False})
check(r.ok and r.json()["archived"] is False and SEC in {x["id"] for x in Ca.get(B + "/api/team").json()["rooms"]}, "archive: restored (undo)")

# ================================================================== files
r = files_post(Bo, GEN, [("pic.png", PNG, "image/png"), ("notes.txt", b"plain notes", "text/plain")], body="Two files")
check(r.status_code == 201 and len(j(r).get("attachments") or []) == 2, "files: a message with two files " + r.text[:300])
M1 = j(r)
F1, F2 = [a["id"] for a in M1.get("attachments") or [0, 0]] if len(M1.get("attachments") or []) == 2 else (0, 0)
check(all(a["url"] == f"/api/team/files/{a['id']}" for a in M1.get("attachments") or [{"url": ""}]), "files: the app's address")
m = next((x for x in msgs(Ca, GEN) if x["id"] == M1.get("id")), {})
check([a["name"] for a in m.get("attachments", [])] == ["pic.png", "notes.txt"] and m["attachments"][0]["mime"] == "image/png",
      "files: carol sees both in the conversation " + str(m.get("attachments"))[:200])
r = Ca.get(B + f"/api/team/files/{F2}")
check(r.status_code == 200 and r.content == b"plain notes", "files: carol fetches the text file")
check(Ca.get(B + f"/api/team/files/{F1}").content == PNG, "files: the image comes back unchanged")
check(Da.get(B + f"/api/team/files/{F1}").status_code == 200, "files: dave (open channel of his organisation) may fetch it")
check(Ev.get(B + f"/api/team/files/{F1}").status_code == 404, "files: eve (Beta) gets 404")
r = files_post(Bo, GEN, [("only.txt", b"just a file", "text/plain")])
check(r.status_code == 201 and j(r).get("body") == "" and len(j(r).get("attachments") or []) == 1, "files: a message with files only " + r.text[:200])
MF = j(r).get("id")
last = next((x for x in Ca.get(B + "/api/team").json()["rooms"] if x["id"] == GEN), {}).get("last") or {}
check(last.get("text") == "only.txt", "files: the conversation list shows the file name of a files-only message " + str(last)[:200])
r = Ca.post(B + f"/api/team/rooms/{GEN}/messages", json={"body": "Got it", "reply_to": MF})
check(r.status_code == 201 and (j(r).get("reply") or {}).get("text") == "only.txt", "files: the quote of a files-only message names the file")
check(files_post(Bo, GEN, [(f"f{i}.txt", b"x", "text/plain") for i in range(11)]).status_code == 400, "files: at most 10 per message")
check(files_post(Bo, GEN, [("empty.txt", b"", "text/plain")]).status_code == 400, "files: an empty file is refused")
r = files_post(Bo, SEC, [("secret.txt", b"secret", "text/plain")])
FS = (j(r).get("attachments") or [{}])[0].get("id")
check(r.status_code == 201 and Da.get(B + f"/api/team/files/{FS}").status_code == 404, "files: a closed channel's file is not for dave")
# save as task takes the files along
r = Ca.post(B + "/api/chat-save", json={"kind": "team", "msg_id": M1.get("id")})
check(r.status_code in (200, 201), "save as task: a message with files " + r.text[:200])
tid = j(r).get("task_id") or (j(r).get("task") or {}).get("id")
if tid:
    t = Ca.get(B + f"/api/tasks/{tid}").json()
    check(len(t.get("attachments") or []) == 2, "save as task: the files are on the task " + str(t.get("attachments"))[:200])
# search finds the channel's messages
r = Ca.get(B + "/api/search/messages", params={"q": "Two files"})
hit = next((h for h in j(r).get("hits", []) if h.get("room_id") == GEN), None)
check(hit is not None and hit["chat_type"] == "channel" and hit.get("chat_name") == "General", "search: a channel hit " + r.text[:300])
check(not any(h.get("room_id") == GEN for h in Ev.get(B + "/api/search/messages", params={"q": "Two files"}).json().get("hits", [])), "search: not for eve")
# deleting the message removes its files (rows and disk)
disk = os.path.join(DATA, "attachments", "tchat", str(GEN)) if DATA else ""
before = set(os.listdir(disk)) if disk and os.path.isdir(disk) else None
check(Bo.delete(B + f"/api/team/messages/{M1.get('id')}").ok, "files: bob deletes the message")
check(Ca.get(B + f"/api/team/files/{F1}").status_code == 404 and Ca.get(B + f"/api/team/files/{F2}").status_code == 404, "files: gone with the message")
if before is not None:
    after = set(os.listdir(disk))
    check(len(before - after) == 2, f"files: both left the disk ({len(before)} -> {len(after)})")
else:
    print("note: data dir not readable here, disk check skipped", flush=True)

# ================================================================== agents
check(requests.get(V + f"/team/rooms/{GEN}/messages", headers=CLH).status_code == 404, "agent: not a member yet -> 404")
check(Bo.post(B + f"/api/team/rooms/{GEN}/members", json={"user_id": CL}).status_code == 403, "agent: bob (no manager) cannot add it")
check(A.post(B + f"/api/team/rooms/{GEN}/members", json={"user_id": OT}).status_code == 400, "agent: an agent of Beta cannot be added")
r = A.post(B + f"/api/team/rooms/{GEN}/members", json={"user_id": CL})
check(r.ok, "agent: the organisation admin adds the organisation's agent " + r.text[:200])
rr = requests.get(V + "/team/rooms", headers=CLH).json()["data"]
check(any(x["id"] == GEN and x["kind"] == "channel" for x in rr), "agent: the channel in its rooms")
r = requests.post(V + f"/team/rooms/{GEN}/messages", headers=CLH, data={"body": "Report attached"}, files=[("file", ("report.md", b"# Report", "text/markdown"))])
check(r.status_code == 201 and len(j(r).get("attachments") or []) == 1, "agent: sends a file through the REST API " + r.text[:300])
FA = (j(r).get("attachments") or [{}])[0]
check(FA.get("url") == f"/api/v1/team/files/{FA.get('id')}", "agent: the REST address of the file")
check(requests.get(V + f"/team/files/{FA.get('id')}", headers=CLH).content == b"# Report", "agent: reads the file through the REST API")
check(Bo.get(B + f"/api/team/files/{FA.get('id')}").content == b"# Report", "agent: bob fetches the agent's file")
check(requests.get(V + f"/team/files/{FA.get('id')}", headers=OTH).status_code == 404, "agent: otto (Beta) gets 404")
check(requests.get(V + f"/team/rooms/{GEN}/messages", headers=OTH).status_code == 404, "agent: otto cannot read the channel")
check(requests.post(V + "/team/channels", headers=CLH, json={"name": "Bots"}).status_code == 403, "agent: cannot open a channel")
check(requests.post(V + "/team/groups", headers=CLH, json={"members": [BOB, CAROL]}).status_code == 403, "agent: cannot open a group")
r = requests.get(V + "/team/channels", headers=CLH)
check(r.ok and any(x["id"] == GEN for x in r.json()["data"]), "agent: lists its channels through the REST API")
r = requests.delete(V + f"/team/rooms/{GEN}/members/{CL}", headers=CLH)
check(r.status_code == 204 and requests.get(V + f"/team/rooms/{GEN}/messages", headers=CLH).status_code == 404, "agent: leaves the channel")
# REST API for people (token-less session also reaches v1 through the app? use the app routes; v1 create through a person token)
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "comments"]})
if tok.ok and tok.json().get("token"):
    AH = {"Authorization": "Bearer " + tok.json()["token"]}
    r = requests.post(V + "/team/channels", headers=AH, json={"name": "Via API", "org_id": ORG})
    check(r.status_code == 201, "REST: a person opens a channel " + r.text[:200])
    r = requests.patch(V + f"/team/rooms/{j(r).get('id')}", headers=AH, json={"archived": True})
    check(r.ok and r.json()["archived"] is True, "REST: and archives it")

# ================================================================== groups
r = A.post(B + "/api/team/groups", json={"members": [BOB, CAROL]})
check(r.status_code == 201 and r.json()["kind"] == "group" and r.json()["members"] == 3 and r.json()["name"] in ("Bob, Carol", "Carol, Bob"),
      "group: alice, bob and carol " + r.text[:300])
GRP = j(r).get("id")
check(A.post(B + "/api/team/groups", json={"members": [BOB]}).status_code == 400, "group: at least two others")
r = A.post(B + "/api/team/groups", json={"members": [BOB, DAVE]})
check(r.status_code == 400 and "does not work with" in r.text, "group: dave does not work with alice / bob " + r.text[:200])
check(A.post(B + "/api/team/groups", json={"members": [BOB, EVE]}).status_code == 400, "group: no person of Beta")
check(A.post(B + f"/api/team/rooms/{GRP}/members", json={"user_id": DAVE}).status_code == 400, "group: dave cannot be added")
check(A.post(B + f"/api/team/rooms/{GRP}/members", json={"user_id": CL}).status_code == 400, "group: no agents")
check(Da.get(B + f"/api/team/rooms/{GRP}/messages").status_code == 404, "group: dave cannot read it")
r = Bo.post(B + f"/api/team/rooms/{GRP}/messages", json={"body": "Lunch?"})
check(r.status_code == 201, "group: bob writes")
rc = next((x for x in Ca.get(B + "/api/team").json()["rooms"] if x["id"] == GRP), {})
check(rc.get("unread") == 1 and rc.get("kind") == "group", "group: unread for carol " + str(rc)[:200])
r = files_post(Ca, GRP, [("menu.txt", b"soup", "text/plain")], body="Menu")
check(r.status_code == 201 and len(j(r).get("attachments") or []) == 1, "group: files too")
r = Ca.patch(B + f"/api/team/rooms/{GRP}", json={"name": "Lunch crew"})
check(r.ok and r.json()["name"] == "Lunch crew", "group: a member names it")
check(Ca.patch(B + f"/api/team/rooms/{GRP}", json={"archived": True}).status_code == 400, "group: is not archived (members leave)")
check(Ca.delete(B + f"/api/team/rooms/{GRP}/members/{BOB}").status_code == 403, "group: nobody removes another person")
check(Bo.delete(B + f"/api/team/rooms/{GRP}/members/{BOB}").ok, "group: bob leaves")
check(Bo.get(B + f"/api/team/rooms/{GRP}/messages").status_code == 404 and GRP not in {x["id"] for x in Bo.get(B + "/api/team").json()["rooms"]},
      "group: bob reads it no more")
check(Ev.get(B + f"/api/team/rooms/{GRP}/messages").status_code == 404, "group: eve never")

# ================================================================== end-to-end encrypted DM refuses files


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def keys():
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}


assert A.put(B + "/api/e2e/keys", json=keys()).ok and Bo.put(B + "/api/e2e/keys", json=keys()).ok
DM = A.post(B + "/api/team/dm", json={"user_id": BOB}).json()["id"]
r = A.post(B + f"/api/team/rooms/{DM}/e2e", json={"on": True})
check(r.ok, "e2e: the DM is encrypted " + r.text[:200])
r = files_post(A, DM, [("x.txt", b"plain", "text/plain")])
check(r.status_code == 409, "e2e: an encrypted DM refuses files " + r.text[:200])
A.post(B + f"/api/team/rooms/{DM}/e2e", json={"on": False})
r = files_post(A, DM, [("x.txt", b"plain", "text/plain")], body="Plain again")
check(r.status_code == 201 and len(j(r).get("attachments") or []) == 1, "e2e: the plain DM takes files")

# ================================================================== a person without an organisation
# freelancer-matrix: team
FID, Fr = freelancer(B, A)
FIO, Fi = freelancer(B, A, "fiona")  # a second freelancer: they work together through a group of the instance
import dbx  # noqa: E402  (no route links two freelancers without the mail confirmation of the discovery: a group row)
DBC = dbx.connect(DATA)
DBC.execute("INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES(?,?,?,?)", ("Freelance pool", "", "2026-10-19T08:00:00", ALICE))
GID = DBC.execute("SELECT id FROM groups WHERE name=?", ("Freelance pool",)).fetchone()[0]
for x in (FID, FIO):
    DBC.execute("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (GID, x, "2026-10-19T08:00:00"))
ch = Fr.get(B + "/api/team/channels")
check(ch.ok and ch.json()["orgs"] == [] and FIO in ch.json()["people"], "freelancer: whom I may add (people I work with) " + ch.text[:200])
check(Fr.post(B + "/api/team/channels", json={"name": "Club", "open": True}).status_code == 400, "freelancer: a private channel is never open")
check(Fr.post(B + "/api/team/channels", json={"name": "Club", "org_id": ORG}).status_code == 400, "freelancer: no organisation")
check(Fr.post(B + "/api/team/channels", json={"name": "Club", "members": [BOB]}).status_code == 400, "freelancer: only people I work with")
r = Fr.post(B + "/api/team/channels", json={"name": "Club", "members": [FIO]})
check(r.status_code == 201 and r.json()["org_id"] is None and r.json()["open"] is False and r.json()["manage"] is True, "freelancer: own channel " + r.text[:200])
FCH = j(r).get("id")
r = files_post(Fr, FCH, [("plan.txt", b"plan", "text/plain")], body="Plan")
FF = (j(r).get("attachments") or [{}])[0].get("id")
check(r.status_code == 201 and Fi.get(B + f"/api/team/files/{FF}").content == b"plan", "freelancer: a file in the own channel, fiona reads it")
check(Bo.get(B + f"/api/team/files/{FF}").status_code == 404 and Bo.get(B + f"/api/team/rooms/{FCH}/messages").status_code == 404, "freelancer: bob sees nothing")
r = Fr.patch(B + f"/api/team/rooms/{FCH}", json={"name": "Club 2", "archived": True})
check(r.ok and r.json()["name"] == "Club 2" and r.json()["archived"] is True, "freelancer: renames and archives (own admin)")
check(Fr.patch(B + f"/api/team/rooms/{FCH}", json={"archived": False}).ok, "freelancer: restores")
check(Fi.patch(B + f"/api/team/rooms/{FCH}", json={"name": "Taken"}).status_code == 403, "freelancer: fiona (member) does not manage it")
check(A.get(B + f"/api/team/rooms/{FCH}/messages").status_code == 404, "freelancer: alice (instance admin, not a member) reads nothing")
r = Fr.post(B + "/api/team/groups", json={"members": [FIO, BOB]})
check(r.status_code == 400, "freelancer: a group only with people who work with me")
check(Fi.delete(B + f"/api/team/rooms/{FCH}/members/{FIO}").ok, "freelancer: fiona leaves")
rr = Fr.get(B + "/api/team")
check(rr.ok and any(x["id"] == FCH for x in rr.json()["rooms"]), "freelancer: the channel in the own conversations")

print(f"{OKS[0]} ok, {len(FAILS)} failed", flush=True)
if FAILS:
    sys.exit(1)
print("ALL P2113B B API CHECKS PASSED")
