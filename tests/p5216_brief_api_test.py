#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.739.0 API tests (#5216): the brief of a job -- the exact wording an agent gave its job, as a chat message of the new
kind brief. Own container (start.sh). Invented names only, addresses @example.com.
 - POST /api/v1/agent/chats/{uid} {kind: brief, job_id, body}: 201, kind brief, job_id; the text kept as it is
   (Markdown, line breaks), up to 60000 characters
 - it shows ONLY in the job's own chat: GET ?job= carries it as brief {id, body, created_at} (not in messages); the whole
   chat (first page, ?after=, ?before=) never has it, nor the message search
 - never unread, it does not end the open buttons of an earlier message, it cannot be pinned
 - a newer brief of the same job replaces the older one
 - 400: without job_id, a job of another person, a job of another agent, other fields (choices, task_id), files, an
   empty or too long body; nothing stored
 - another person cannot open the job's chat (404)
 - a person without an organisation (freelancer fixture) with an own agent: the same
tenant-matrix: agent
freelancer-matrix: agents
usage: p5216_brief_api_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
import requests  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(prefix="P5216")
s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
V = B + "/api/v1"
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
Bo, Ca = sess("bob"), sess("carol")


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": name, "display_name": name.title()})
    assert r.ok, r.text
    aid = r.json()["id"]
    A.patch(B + f"/api/admin/agents/{aid}", json={"org_id": ORG})
    return aid, {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"}


CL, CLH = agent("claude")
OT, OTH = agent("otto")
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
for m in (CL, OT, BOB, CAROL):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": m, "role": "edit"}).ok, f"setup: {m} in the list")
A.patch(B + f"/api/lists/{W}", json={"agent_members": True})


def job(hdr, title, who=BOB):
    r = requests.post(V + "/agent/jobs", headers=hdr, json={"title": title, "user_id": who, "state": "running"})
    assert r.ok, r.text
    return r.json()["id"]


def chat(s, aid=CL, q=""):
    r = s.get(B + f"/api/agents/{aid}/chat" + q)
    return r.json() if r.ok else {"_status": r.status_code}


def post(hdr, who, payload, **kw):
    return requests.post(V + f"/agent/chats/{who}", headers=hdr, json=payload, **kw)


def briefs_in(msgs):
    return [m for m in msgs if m.get("kind") == "brief"]


TEXT = "# Release 2.739\n\nBuild **the job brief** card.\n\n- step one\n- step two: Zwiebelkuchen\n"
J = job(CLH, "Knox: Release 2.739")
CJ = job(CLH, "Carla: for carol", CAROL)
OJ = job(OTH, "Oskar: otto's job")

# ================================================================== an open question before (its buttons must stay open)
pl = post(CLH, BOB, {"body": "A plain answer with Zwiebelkuchen"})
check(pl.status_code == 201, "setup: a plain answer")
PL = pl.json().get("id")
q = post(CLH, BOB, {"body": "Which size?", "choices": [{"id": "s", "label": "Small"}, {"id": "l", "label": "Large"}]})
check(q.status_code == 201, "setup: a question with buttons " + q.text[:200])
QID = q.json().get("id")

# ================================================================== posting the brief
r = post(CLH, BOB, {"kind": "brief", "job_id": J, "body": TEXT})
check(r.status_code == 201 and r.json().get("kind") == "brief" and r.json().get("job_id") == J, "the brief: 201, kind brief, job_id " + r.text[:300])
check(r.json().get("body") == TEXT.strip(), "the text is kept as it is (Markdown, line breaks) " + repr(r.json().get("body"))[:200])
BID = r.json().get("id")

# ================================================================== only in the job's own chat
whole = chat(Bo)
check(not briefs_in(whole.get("messages", [])) and BID not in [m["id"] for m in whole.get("messages", [])], "the whole chat never has the brief")
check("brief" not in whole, "the whole chat has no field brief")
check(not briefs_in(chat(Bo, q=f"?after={PL}").get("messages", [])), "?after= (the app's refresh): no brief")
check(not briefs_in(chat(Bo, q=f"?before={BID + 1}").get("messages", [])), "?before= (older pages): no brief")
jc = chat(Bo, q=f"?job={J}")
b = jc.get("brief") or {}
check(b.get("id") == BID and b.get("body") == TEXT.strip() and b.get("created_at"), "?job=: brief {id, body, created_at} " + str(b)[:200])
check(not briefs_in(jc.get("messages", [])), "?job=: the brief is not one of the messages (always on top, never paged away)")
check(chat(Bo, q=f"?job={CJ}").get("_status") == 404, "bob: carol's job chat 404")
check(Ca.get(B + f"/api/agents/{CL}/chat?job={J}").status_code == 404, "carol: bob's job chat 404")
jo = chat(Bo, q="?job=%d" % J)
check(jo.get("brief", {}).get("id") == BID, "the brief stays on a second load")
other = job(CLH, "Mira: no brief")
check(chat(Bo, q=f"?job={other}").get("brief") is None, "a job without a brief: brief null")

# ================================================================== never unread, buttons stay open, no pin, no search
unread = [a.get("chat_unread") for a in Bo.get(B + "/api/agents").json().get("agents", []) if a.get("id") == CL]
check(unread in ([0], [None]), "the brief is never unread " + str(unread))
qs = [m for m in chat(Bo).get("messages", []) if m["id"] == QID]
check(qs and qs[0].get("choice_state") == "open", "the brief does not end the open buttons " + str(qs)[:300])
check(Bo.post(B + f"/api/agents/{CL}/chat/{BID}/pin", json={"pinned": True}).status_code == 400, "the brief cannot be pinned")
hits = Bo.get(B + "/api/search/messages", params={"q": "Zwiebelkuchen", "art": "a"}).json().get("hits", [])
ids = [h.get("id") for h in hits]
check(PL in ids, "search control: the plain answer is found " + str(hits)[:300])
check(BID not in ids, "the message search never finds the brief " + str(ids))

# ================================================================== a newer brief replaces the older one
r2 = post(CLH, BOB, {"kind": "brief", "job_id": J, "body": "Second version of the brief"})
check(r2.status_code == 201, "a second brief of the job " + r2.text[:200])
b2 = chat(Bo, q=f"?job={J}").get("brief") or {}
check(b2.get("id") == r2.json().get("id") and b2.get("body") == "Second version of the brief", "the newer brief replaces the older one " + str(b2)[:200])
allb = [m for m in requests.get(V + "/agent/chats", headers=CLH, params={"user_id": BOB}).json().get("data", []) if m.get("kind") == "brief"]
check([m["id"] for m in allb] == [r2.json().get("id")], "only one brief row of the job is left " + str([m["id"] for m in allb]))

# ================================================================== refused, nothing stored
before = len(requests.get(V + "/agent/chats", headers=CLH, params={"user_id": BOB}).json().get("data", []))
bad = [
    ({"kind": "brief", "body": "no job"}, "without job_id"),
    ({"kind": "brief", "job_id": CJ, "body": "carol's job"}, "a job of another person"),
    ({"kind": "brief", "job_id": OJ, "body": "otto's job"}, "a job of another agent"),
    ({"kind": "brief", "job_id": J, "body": "x", "choices": [{"id": "a", "label": "A"}]}, "with choices"),
    ({"kind": "brief", "job_id": J, "body": "x", "task_id": 1}, "with task_id"),
    ({"kind": "brief", "job_id": J, "body": "   "}, "an empty body"),
    ({"kind": "brief", "job_id": J, "body": "x" * 60001}, "a body over 60000 characters"),
    ({"kind": "memo", "job_id": J, "body": "x"}, "an unknown kind"),
]
for payload, what in bad:
    rr = post(CLH, BOB, payload)
    check(rr.status_code == 400, f"400: {what} ({rr.status_code} {rr.text[:120]})")
rf = requests.post(V + f"/agent/chats/{BOB}", headers=CLH, data={"kind": "brief", "job_id": str(J), "body": "with a file"},
                   files={"file": ("a.txt", b"hello", "text/plain")})
check(rf.status_code == 400, "400: a brief with a file " + str(rf.status_code))
after = len(requests.get(V + "/agent/chats", headers=CLH, params={"user_id": BOB}).json().get("data", []))
check(after == before, f"nothing stored by the refused posts ({before} -> {after})")
big = post(CLH, BOB, {"kind": "brief", "job_id": J, "body": "y" * 60000})
check(big.status_code == 201 and len((chat(Bo, q=f"?job={J}").get("brief") or {}).get("body", "")) == 60000, "60000 characters are taken whole")

# ================================================================== a person without an organisation, own agent
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FU, F = freelancer(B, A, "frida")
ag = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]})
check(ag.status_code in (200, 201), "freelancer: an own agent " + ag.text[:200])
FA = ag.json().get("id")
tk = F.post(B + f"/api/my/agents/{FA}/token")
FH = {"Authorization": "Bearer " + tk.json().get("token", ""), "X-Requested-With": "kalmido"}
FJ = job(FH, "Mira: Release 1.4", who=FU)
fr = post(FH, FU, {"kind": "brief", "job_id": FJ, "body": "Build the **invoice** list."})
check(fr.status_code == 201 and fr.json().get("kind") == "brief", "freelancer's agent: the brief " + fr.text[:200])
check(not briefs_in(chat(F, FA).get("messages", [])), "freelancer: not in the whole chat")
check((chat(F, FA, f"?job={FJ}").get("brief") or {}).get("body") == "Build the **invoice** list.", "freelancer: the brief in the job's chat")
check(post(FH, FU, {"kind": "brief", "job_id": J, "body": "x"}).status_code == 400, "freelancer's agent: bob's job 400")

sys.exit(kt.done("p5216_brief_api"))
