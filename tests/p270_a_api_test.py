#!/usr/bin/env python3
"""2.70.0 API tests, part A (#1354): a meeting becomes tasks (the proposal kind "extract" with photos). Invented names only.
 - POST /api/agents/{id}/meeting-images: images only (1..4), stored as the person's message in their chat with that agent,
   no 'chat' event; refused for an agent the person may not ask (404), for a person who cannot chat with it (404), for an
   agent token
 - POST /api/proposals kind extract: text OR image_ids (neither = 400); image_ids only the person's own image files of
   their chat with THAT agent (another chat, another person, the agent's own file, a non-image, duplicates, more than 4 =
   400); a health list = 400; the job input carries images [{id, name, mime, size, url}]; the agent reads the job's image
   (200), another agent cannot (404)
 - GET /api/agents/{id}/meeting-proposals: only the person's own ready proposals (the chat's cards); apply with a part
   selection creates only the ticked tasks as the person (assignee, due, created_by), one undo step (undo / redo), apply
   twice 409, the agent cannot apply its own proposal; discard removes the card
 - a freelancer without an organisation (own list, own agent) has the same flow
usage: p270_a_api_test.py <datadir>      (a fresh container; P270A_NOSTART=1 = the server already runs)"""
import os
import struct
import subprocess
import sys
import zlib

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def dbx(q, a=()):
    con = dbxm.connect(os.path.join(DATA, "tasks.db"))
    try:
        return con.execute(q, a).fetchall()
    finally:
        con.close()


def png(rgb=(120, 60, 200)):
    """A tiny valid PNG (8 x 8, one colour) without any library."""
    raw = b"".join(b"\x00" + bytes(rgb) * 8 for _ in range(8))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=30, **k)


def agent(name, org=None):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": name, "display_name": name.title()})
    assert r.ok, r.text
    aid = r.json()["id"]
    if org:
        A.patch(B + f"/api/admin/agents/{aid}", json={"org_id": org})
    return aid, Api(r.json()["token"])


def share(s, lid, uid, role="edit"):
    r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": role})
    if not r.ok:  # a second agent in a list, or a person who may not share agents: as a list from before the update
        dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')",
            (lid, uid, role, role))
    s.patch(B + f"/api/lists/{lid}", json={"agent_members": True, "agent_peers": True})


def upload(s, aid, *files):
    return s.post(B + f"/api/agents/{aid}/meeting-images", files=[("file", f) for f in files])


def ask(s, **b):
    return s.post(B + "/api/proposals", json={"kind": "extract", **b})


def events(api, since=0):
    r = api.req("GET", "/agent/events", params={"since": since, "limit": 500})
    assert r.ok, r.text
    return r.json()["data"], r.json()["cursor"]


def cards(s, aid):
    r = s.get(B + f"/api/agents/{aid}/meeting-proposals")
    assert r.ok, r.text
    return r.json()["proposals"]


if not os.environ.get("P270A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/users", json={"username": "fred", "display_name": "Fred", "password": "password123", "email": "fred@example.com"})
assert r.ok, r.text
FRED = r.json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
Bo, Ca, Fr = sess("bob"), sess("carol"), sess("fred")
for x in (Bo, Ca, Fr):
    x.patch(B + "/api/settings", json={"lang": "en"})

CL, cl = agent("claude", ORG)
OT, ot = agent("otto", ORG)
TEAM = A.post(B + "/api/lists", json={"name": "Shoot", "org_id": ORG}).json()["id"]
share(A, TEAM, BOB)
share(A, TEAM, CL)
SEC = A.post(B + "/api/sections", json={"list_id": TEAM, "name": "Prep"}).json()["id"]
OTL = A.post(B + "/api/lists", json={"name": "Otto's", "org_id": ORG}).json()["id"]
share(A, OTL, OT)
HL = A.post(B + "/api/lists", json={"name": "Doctor"}).json()["id"]
dbx("UPDATE lists SET life='health' WHERE id=?", (HL,))

P1, P2 = png(), png((20, 160, 60))

# ================================================================== uploading the photos
_, cur0 = events(cl)
r = upload(A, CL, ("whiteboard.png", P1, "image/png"), ("minutes.png", P2, "image/png"))
check(r.status_code == 201 and len(r.json()["images"]) == 2, "upload: two images 201 " + r.text[:200])
IMG = [x["id"] for x in r.json()["images"]]
MID = r.json()["message_id"]
ev, _ = events(cl, cur0)
check(not [e for e in ev if e["event"] == "chat"], "upload: no 'chat' event for the agent (it gets the images with the job)")
msg = [m for m in A.get(B + f"/api/agents/{CL}/chat").json()["messages"] if m["id"] == MID]
check(msg and len(msg[0].get("attachments") or []) == 2 and msg[0]["from"] != "agent", "upload: my message with both images in my chat")
check(upload(A, CL, ("notes.txt", b"hello", "text/plain")).status_code == 400, "upload: a text file 400")
check(upload(A, CL, *[(f"p{i}.png", P1, "image/png") for i in range(5)]).status_code == 400, "upload: five images 400")
check(A.post(B + f"/api/agents/{CL}/meeting-images").status_code == 400, "upload: no file 400")
check(upload(Ca, CL, ("x.png", P1, "image/png")).status_code == 404, "upload: carol shares nothing with claude 404")
r = requests.post(B + f"/api/agents/{CL}/meeting-images", headers={**cl.h, **H}, files=[("file", ("x.png", P1, "image/png"))])
check(r.status_code in (401, 403, 404), f"upload: an agent token cannot use the person route ({r.status_code})")

# ================================================================== the request
r = ask(A, agent_id=CL, list_id=TEAM, text="Bob books the studio by Friday.")
check(r.status_code == 201, "extract with text only 201 " + r.text[:200])
J0 = r.json()["id"]
inp = requests.get(V + f"/agent/jobs/{J0}", headers=cl.h).json()["input"]
check(inp["text"].startswith("Bob books") and "images" not in inp and sorted(m["id"] for m in inp["members"]) == sorted([ALICE, BOB]),
      "text only: input unchanged (list, members, text, no images) " + str(inp)[:200])
A.post(B + f"/api/proposals/{J0}/discard")

_, cur = events(cl)
r = ask(A, agent_id=CL, list_id=TEAM, text="", image_ids=IMG)
check(r.status_code == 201, "extract with images only 201 " + r.text[:200])
J1 = r.json()["id"]
inp = requests.get(V + f"/agent/jobs/{J1}", headers=cl.h).json()["input"]
im = inp.get("images") or []
check([x["id"] for x in im] == IMG and im[0]["name"] == "whiteboard.png" and im[0]["mime"] == "image/png"
      and im[0]["url"] == f"/api/v1/chat-attachments/{IMG[0]}" and im[0]["size"] == len(P1), "input.images: id, name, mime, size, url " + str(im)[:300])
ev, _ = events(cl, cur)
jr = [e for e in ev if e["event"] == "job_request"]
check(jr and [x["id"] for x in ((jr[-1].get("data") or jr[-1]).get("input") or {}).get("images", [])] == IMG, "job_request carries input.images")
r = requests.get(V + f"/chat-attachments/{IMG[0]}", headers=cl.h)
check(r.status_code == 200 and r.content == P1, f"the agent reads the job's image ({r.status_code})")
check(requests.get(V + f"/chat-attachments/{IMG[0]}", headers=ot.h).status_code == 404, "another agent cannot read it (404)")

check(ask(A, agent_id=CL, list_id=TEAM).status_code == 400, "neither text nor image 400")
check(ask(A, agent_id=CL, list_id=TEAM, text="  ", image_ids=[]).status_code == 400, "blank text, no images 400")
check(ask(A, agent_id=CL, list_id=HL, text="x").status_code == 400, "a health list 400")
check(ask(A, agent_id=CL, list_id=TEAM, image_ids=[IMG[0], IMG[0]]).status_code == 400, "duplicate image ids 400")
check(ask(A, agent_id=CL, list_id=TEAM, image_ids=IMG * 2 + [1]).status_code == 400, "more than four image ids 400")
check(ask(A, agent_id=CL, list_id=TEAM, image_ids=["x"]).status_code == 400, "a bad id 400")
r = upload(Bo, CL, ("bob.png", P2, "image/png"))
check(r.status_code == 201, "bob uploads into his own chat with claude")
BIMG = r.json()["images"][0]["id"]
check(ask(A, agent_id=CL, list_id=TEAM, image_ids=[BIMG]).status_code == 400, "another person's image (bob's chat) 400")
r = A.post(B + f"/api/agents/{CL}/chat", data={"body": "the notes"}, files=[("file", ("notes.txt", b"line\n", "text/plain"))])
TXT = r.json()["attachments"][0]["id"]
check(ask(A, agent_id=CL, list_id=TEAM, image_ids=[TXT]).status_code == 400, "a text file of my own chat 400")
r = cl.req("POST", f"/agent/chats/{ALICE}", data={"body": "a picture"}, files=[("file", ("agent.png", P2, "image/png"))])
AIMG = r.json()["attachments"][0]["id"]
check(ask(A, agent_id=CL, list_id=TEAM, image_ids=[AIMG]).status_code == 400, "the agent's own image 400")
r = upload(A, OT, ("otto.png", P1, "image/png"))
check(r.status_code == 201, "alice uploads into her chat with otto")
OIMG = r.json()["images"][0]["id"]
check(ask(A, agent_id=CL, list_id=TEAM, image_ids=[OIMG]).status_code == 400, "an image of my chat with ANOTHER agent 400")
check(requests.get(V + f"/chat-attachments/{OIMG}", headers=cl.h).status_code == 404, "claude cannot read the image of the otto chat")
r = ask(Ca, agent_id=CL, list_id=TEAM, text="x")
check(r.status_code in (403, 404), f"carol (no list, no agent) cannot ask ({r.status_code})")

# an agent without the right to make proposals: not offered, nothing accepted
check(A.patch(B + f"/api/admin/agents/{OT}", json={"proposals": "off"}).ok, "otto: proposals off")
check(OT not in [a["id"] for a in A.get(B + "/api/proposals/agents").json()["agents"]], "otto not offered any more")
check(upload(A, OT, ("x.png", P1, "image/png")).status_code == 404, "upload to otto 404 (no proposals)")
check(ask(A, agent_id=OT, list_id=OTL, text="x").status_code == 404, "request to otto 404")

# ================================================================== the proposal, the card, apply with a part selection
EX = {"summary": "From the whiteboard", "tasks": [{"title": "Book the studio", "assignee_id": BOB, "due": "2031-02-07", "section": "Prep"},
                                                  {"title": "Write the brief", "assignee_id": ALICE},
                                                  {"title": "Order pizza"}]}
check(requests.post(V + f"/agent/jobs/{J1}/proposal", headers=cl.h, json=EX).status_code == 201, "the agent proposes three tasks")
cs = cards(A, CL)
check(len(cs) == 1 and cs[0]["id"] == J1 and [t["title"] for t in cs[0]["tasks"]] == ["Book the studio", "Write the brief", "Order pizza"]
      and cs[0]["tasks"][0]["assignee"] == "Bob" and cs[0]["tasks"][0]["due"] == "2031-02-07" and cs[0]["images"] == 2
      and cs[0]["list"]["id"] == TEAM and cs[0]["summary"] == "From the whiteboard", "the chat card: titles, assignee, due, list " + str(cs)[:300])
check(cards(Bo, CL) == [], "bob sees no card of alice's proposal")
check(cards(A, OT) == [], "no card in the chat with otto")
r = requests.post(B + f"/api/proposals/{J1}/apply", headers={**cl.h, **H}, json={"select": ["0"]})
check(r.status_code in (401, 403, 404), f"the agent cannot apply its own proposal ({r.status_code})")
check(Bo.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code == 404, "bob cannot apply alice's proposal")
r = A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0", "2"]})
check(r.ok and r.json()["created"] == 2, "apply two of three " + r.text[:200])
rows = {x[0]: x for x in dbx("SELECT title, assignee_id, created_by, due, section_id FROM tasks WHERE list_id=? AND deleted_at IS NULL", (TEAM,))}
check(set(rows) == {"Book the studio", "Order pizza"}, "only the ticked tasks " + str(sorted(rows)))
b = rows.get("Book the studio") or ()
check(b and b[1] == BOB and b[2] == ALICE and str(b[3]).startswith("2031-02-07") and b[4] == SEC, "assignee bob, created by alice, due, section")
check(rows.get("Order pizza", (0, 1))[1] is None, "no assignee where none was proposed")
check(cards(A, CL) == [], "the card is gone after apply")
check(A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["1"]}).status_code == 409, "apply twice 409")
r = A.post(B + f"/api/proposals/{J1}/undo")
check(r.ok and r.json()["undone"] == 2 and not dbx("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at IS NULL", (TEAM,)), "one undo step takes both back")
r = A.post(B + f"/api/proposals/{J1}/redo")
check(r.ok and len(dbx("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at IS NULL", (TEAM,))) == 2, "redo brings both back")

# discard from the card
r = ask(A, agent_id=CL, list_id=TEAM, text="Carol? no. Alice calls the venue.")
J2 = r.json()["id"]
requests.post(V + f"/agent/jobs/{J2}/proposal", headers=cl.h, json={"tasks": [{"title": "Call the venue", "assignee_id": ALICE}]})
check([c["id"] for c in cards(A, CL)] == [J2], "a second proposal = a card")
check(A.post(B + f"/api/proposals/{J2}/discard").ok and cards(A, CL) == [], "discard: the card is gone")
check(not dbx("SELECT 1 FROM tasks WHERE title='Call the venue'"), "discard creates nothing")

# ================================================================== a freelancer without an organisation
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})  # people may connect their own agents
r = Fr.post(B + "/api/my/agents", json={"username": "fredbot", "scopes": ["read", "tasks:write", "comments"]})
check(r.status_code == 201, "freelancer: his own personal agent " + r.text[:200])
FA, fa = r.json()["id"], Api(r.json()["token"])
FL = Fr.post(B + "/api/lists", json={"name": "My shoots"}).json()["id"]
share(Fr, FL, FA)
check(FA in [a["id"] for a in Fr.get(B + "/api/proposals/agents").json()["agents"]], "freelancer: his own agent takes his requests")
r = upload(Fr, FA, ("board.png", P1, "image/png"))
check(r.status_code == 201, "freelancer: upload " + r.text[:200])
r = ask(Fr, agent_id=FA, list_id=FL, image_ids=[r.json()["images"][0]["id"]])
check(r.status_code == 201, "freelancer: request with a photo " + r.text[:200])
FJ = r.json()["id"]
check(requests.post(V + f"/agent/jobs/{FJ}/proposal", headers=fa.h, json={"tasks": [{"title": "Edit the teaser", "assignee_id": FRED, "due": "2031-03-01"}]}).status_code == 201,
      "freelancer: the agent proposes")
check([c["id"] for c in cards(Fr, FA)] == [FJ], "freelancer: the card")
r = Fr.post(B + f"/api/proposals/{FJ}/apply", json={"select": ["0"]})
check(r.ok and [tuple(x) for x in dbx("SELECT created_by, assignee_id FROM tasks WHERE title='Edit the teaser'")] == [(FRED, FRED)],
      "freelancer: applied as himself " + r.text[:200])
check(ask(Fr, agent_id=CL, list_id=FL, text="x").status_code == 404, "freelancer: an agent of the organisation is not his")

print(f"p270_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
