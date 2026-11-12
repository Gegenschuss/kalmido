#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.654.0 part C, own container (start.sh). Invented names only, addresses @example.com.
#5053 the list limit of an API token (api_tokens.list_ids) also in the message search and in the knowledge pages:
 - GET /api/v1/search?scope=messages: a token limited to lists finds no message of a channel (the core's floor obj_gate, as
   need_room / the channel list); a comment in an allowed list it still finds; a token without a limit and the app's session
   find the channel's message as before -- for a person's token and for an agent whose token is limited
 - the channel list (GET /api/v1/team/channels) of the limited agent is empty, unlimited it lists the channel
 - knowledge (wiki): a page belongs to no list, so a limited token lists no page, reads none by its id, makes none; a token
   without a limit and the app are unchanged
 - a person without an organisation: the same for a channel and a page of her own space
usage: p2654_c_tokenlimit_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
import requests  # noqa: E402
import testclock  # noqa: E402,F401
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402,F401

V = B + "/api/v1"
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
SC = ["read", "comments", "wiki:read", "wiki:write"]


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def token(s, name, lists=None):
    j = {"name": name, "scopes": SC, "expires_days": None, **({"list_ids": lists} if lists is not None else {})}
    r = s.post(B + "/api/me/tokens", json=j)
    check(r.ok and r.json().get("token"), f"setup: token {name} {r.text[:160]}")
    return {"Authorization": "Bearer " + ((r.json().get("token") if r.ok else None) or "x")}


def vfind(h, q):
    r = requests.get(V + "/search", headers=h, params={"scope": "messages", "q": q})
    return [(x.get("chat_type"), x.get("id")) for x in r.json().get("data") or []] if r.ok else r.status_code


def afind(s, q):
    r = s.get(B + "/api/search?kind=messages", params={"q": q})
    return [(x.get("chat_type"), x.get("id")) for x in r.json().get("hits") or []] if r.ok else r.status_code


def post(s, rid, body):
    r = s.post(B + f"/api/team/rooms/{rid}/messages", json={"body": body})
    check(r.status_code in (200, 201), f"setup: message in room {rid} {r.text[:160]}")
    return (r.json() or {}).get("id") if r.ok else None


def vpages(h):
    r = requests.get(V + "/wiki/pages", headers=h)
    return [x["id"] for x in r.json().get("data") or []] if r.ok else r.status_code


def channels(h):
    r = requests.get(V + "/team/channels", headers=h)
    return [x["id"] for x in r.json().get("data") or []] if r.ok else r.status_code


def wiki_case(who, s, space, h_full, h_lim):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": f"Handbook {who}", "body": "Invented guide"})
    check(r.status_code in (200, 201), f"{who} setup: a page {r.text[:160]}")
    pid = (r.json() or {}).get("id")
    check(pid in vpages(h_full), f"{who}: a token without a limit lists the page (unchanged)")
    got = vpages(h_lim)
    check(got == [], f"{who}: a token limited to lists lists no page {got}")
    r = requests.get(V + f"/wiki/pages/{pid}", headers=h_lim)
    check(r.status_code == 404 and "Invented guide" not in r.text, f"{who}: ... reads none by its id {r.status_code}")
    check(requests.get(V + f"/wiki/pages/{pid}", headers=h_full).ok, f"{who}: the unlimited token reads it")
    r = requests.post(V + "/wiki/pages", headers=h_lim, json={"space": space, "path": f"Sneaky {who}", "body": "x"})
    check(r.status_code == 404, f"{who}: ... and makes none {r.status_code} {r.text[:120]}")
    check(not sql("SELECT 1 FROM wiki_pages WHERE path=?", (f"Sneaky {who}",)), f"{who}: nothing was made")
    check(s.get(B + f"/api/wiki/pages/{pid}").ok, f"{who}: the app reads the page (unchanged)")


kt.fresh(prefix="P2654C")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done", "workspace": f"org:{ORG}"})

# ================================================================ the message search
LW = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Plan", "list_id": LW}).json()["id"]
r = A.post(B + f"/api/tasks/{T}/comments", json={"body": "zebrafink in the plan"})
check(r.status_code in (200, 201), f"setup: comment {r.text[:120]}")
CM = (r.json() or {}).get("id")
r = A.post(B + "/api/team/channels", json={"name": "General", "org_id": ORG, "members": [BOB]})
check(r.status_code in (200, 201), f"setup: channel {r.text[:160]}")
CH = r.json().get("id")
M1 = post(A, CH, "zebrafink in the channel")
FULL, LIM = token(A, "full"), token(A, "only work", [LW])
check(("channel", M1) in afind(A, "zebrafink"), "app: the search finds the channel's message (unchanged)")
got = vfind(FULL, "zebrafink")
check(isinstance(got, list) and ("channel", M1) in got and ("task", CM) in got, f"a token without a limit finds both (unchanged) {got}")
got = vfind(LIM, "zebrafink")
check(isinstance(got, list) and ("task", CM) in got, f"a token limited to lists still finds the comment of its list {got}")
check(isinstance(got, list) and ("channel", M1) not in got, f"#5053: ... but no message of the channel {got}")
check(requests.get(V + f"/team/rooms/{CH}/messages", headers=LIM).status_code in (403, 404), "... which it may not read either (need_room)")
r = requests.get(V + "/search", headers=LIM, params={"scope": "messages", "q": "zebrafink", "room": CH})
check(r.ok and not r.json().get("data"), f"#5053: ... not with ?room= either {r.status_code} {r.text[:160]}")

# an agent of the organisation, member of the channel; its token limited to the list by the person who manages it
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "comments", "wiki:read"], "username": "robo", "display_name": "Robo"})
check(r.ok, f"setup: agent {r.text[:160]}")
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
check(A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": ORG}).ok, "setup: a team agent of the organisation")
sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG, AG), write=True)
check(A.put(B + f"/api/lists/{LW}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the agent in the list")
r = A.post(B + f"/api/team/rooms/{CH}/members", json={"user_id": AG})
check(r.ok, f"setup: the agent in the channel {r.status_code} {r.text[:160]}")
got = vfind(AGH, "zebrafink")
check(isinstance(got, list) and ("channel", M1) in got, f"agent without a limit: finds the channel's message (unchanged) {got}")
check(CH in channels(AGH), "agent without a limit: lists the channel (unchanged)")
sql("UPDATE api_tokens SET list_ids=? WHERE user_id=?", (str(LW), AG), write=True)
got = vfind(AGH, "zebrafink")
check(isinstance(got, list) and ("channel", M1) not in got, f"#5053: an agent token limited to lists finds no channel message {got}")
check(isinstance(got, list) and ("task", CM) in got, f"... the comment of its list it still finds {got}")
got = channels(AGH)
check(got == [], f"#5053: ... and its channel list is empty {got}")
sql("UPDATE api_tokens SET list_ids='' WHERE user_id=?", (AG,), write=True)

# ================================================================ knowledge pages
wiki_case("org", A, f"org:{ORG}", FULL, LIM)
wiki_case("private", A, "private", FULL, LIM)

# ================================================================ a person without an organisation
FID, Fr = freelancer(B, A)
LF = Fr.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
FF, FL = token(Fr, "full"), token(Fr, "only mine", [LF])
r = Fr.post(B + "/api/team/channels", json={"name": "Notes", "org_id": None})
check(r.status_code in (200, 201), f"freelancer setup: a channel of her own space {r.text[:160]}")
FCH = (r.json() or {}).get("id")
FM = post(Fr, FCH, "kolibri note")
got = vfind(FF, "kolibri")
check(isinstance(got, list) and ("channel", FM) in got, f"freelancer: a token without a limit finds her channel's message {got}")
got = vfind(FL, "kolibri")
check(isinstance(got, list) and ("channel", FM) not in got, f"freelancer #5053: a token limited to lists finds none {got}")
check(channels(FL) == [], "freelancer: ... and lists no channel")
wiki_case("freelancer", Fr, "private", FF, FL)

sys.exit(kt.done("p2654_c_tokenlimit"))
