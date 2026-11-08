#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.579.0 API tests, part C (#4802): saved views of the documents search (kalmido/docs/dviews.py, kind 'docview' of the shared
core). Own container (start.sh). Invented names and generated texts only.
 - create / rename / delete with Undo (trash + restore, the core's session undo), 409 on a stale version, an unknown search
   key is dropped, a bad workspace is 400
 - private per person: not even the organisation's admin sees a member's view; a member never brings one into the
   organisation (org_join "admin": 403 on create, on share); an admin shares one with everyone of it (members / read-only:
   view, a guest nothing) and takes it back
 - hits and counts ALWAYS with the rights of whoever looks: a view the admin shared shows a member only the documents the
   member may see (rueckfall: the count must not be the admin's)
 - a view with a share of its own does not move (409); a view of a private workspace is not shared with an organisation (409)
 - agents: nothing without an explicit share (also not after "share with everyone"), the person routes refuse them (403)
 - the user setting dv_today (ids only), the favourites resolve a view (and drop it for whoever cannot see it)
tenant-matrix: obj (another organisation's admin: 404 on a view, its hits and its sharing)
freelancer-matrix: obj (a person without an organisation: her private view with its count and hits, sharing refused)
usage: p2579_c_api_test.py <datadir>"""
import os
import secrets
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, H, check, docker_logs_on_first_fail, done, fresh, sess, until  # noqa: E402

fresh(prefix="P2579C")
docker_logs_on_first_fail()
K = "docview"
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
WS = f"org:{ORG}"
uid = {}
for u, rk in (("bob", "member"), ("rita", "readonly"), ("gina", "guest")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rk}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as {rk} " + r.text[:200])
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
check(A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]}).ok, "setup: another organisation (olga its admin)")
Bo, Ri, Gi, Ol = (sess(u) for u in ("bob", "rita", "gina", "olga"))
for s in (Bo, Ri, Gi, Ol):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
FID, Fr = freelancer(B, A)


def folder(s, name, space):
    r = s.post(B + "/api/files/folders", json={"name": name, "space": space})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def doc_new(s, name, text, ws):
    """A text document of workspace ws, recognised (its words in the index)."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text.encode(), "text/plain"))])
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 120)
    return nid


def hits(s, ws, q):
    r = s.get(B + "/api/docs", params={"ws": ws, "q": q, "facets": "0"})
    return sorted(d["id"] for d in r.json()["docs"]) if r.ok else r.status_code


def view(s, vid):
    r = s.get(B + f"/api/obj/{K}/{vid}")
    return r.json() if r.ok else r.status_code


def listed(s, ws="all"):
    """{id: count} of the views s sees in workspace ws (or the status code)."""
    r = s.get(B + "/api/docs/views", params={"ws": ws})
    return {v["id"]: v.get("count") for v in r.json()["items"]} if r.ok else r.status_code


# ---------------------------------------------------------------- the documents: one every member sees, one only the admin
OPEN, SHUT = folder(A, "Open invoices", WS), folder(A, "Board only", WS)
check(A.patch(B + f"/api/files/nodes/{OPEN}", json={"org_access": "view"}).ok, "setup: a folder every member reads")
D1 = doc_new(A, "invoice-1.txt", "Rechnung Quokka open for everyone", WS)
D2 = doc_new(A, "invoice-2.txt", "Rechnung Quokka for the board only", WS)
check(A.patch(B + f"/api/files/nodes/{D1}", json={"parent_id": OPEN}).ok and A.patch(B + f"/api/files/nodes/{D2}", json={"parent_id": SHUT}).ok,
      "setup: the documents in their folders")
check(hits(A, WS, "Quokka") == sorted([D1, D2]) and hits(Bo, WS, "Quokka") == [D1], "setup: the admin finds both, the member only the open one")

# ---------------------------------------------------------------- create, list, count
r = A.post(B + f"/api/obj/{K}", json={"title": "  Quokka   invoices ", "query": "q=Quokka&sort=date&dir=desc&limit=5&evil=1", "ws": WS})
check(r.status_code == 201, f"create a view ({r.status_code} {r.text[:200]})")
V = r.json()
VID = V["id"]
check(V["title"] == "Quokka invoices" and V["query"] == "q=Quokka&sort=date&dir=desc" and V["ws"] == WS and V["org_id"] is None
      and V["role"] == "manage" and V["open"] == f"docs/v/{VID}", f"the view: name cleaned, only search keys kept, private {V}")
check(A.post(B + f"/api/obj/{K}", json={"title": "x", "ws": "org:abc"}).status_code == 400, "a bad workspace: 400")
check(A.post(B + f"/api/obj/{K}", json={"title": ""}).status_code == 400, "a view needs a name")
check(listed(A, WS) == {VID: 2} and listed(A) == {VID: 2} and listed(A, "private") == {}, f"listed with its count, only in its workspace {listed(A, WS)}")
r = A.get(B + f"/api/docs/views/{VID}/hits", params={"limit": 1})
check(r.ok and r.json()["total"] == 2 and len(r.json()["docs"]) == 1, f"the first hits and their number ({r.status_code} {r.text[:200]})")

# ---------------------------------------------------------------- private per person; only an admin shares with everyone
check(view(Bo, VID) == 404 and listed(Bo, WS) == {} and Bo.get(B + f"/api/docs/views/{VID}/hits").status_code == 404, "private: the member sees nothing of it")
r = Bo.post(B + f"/api/obj/{K}", json={"title": "Bob's", "query": "q=Quokka", "ws": WS, "org_id": ORG})
check(r.status_code == 403, f"a member does not create a view for everyone (org_join admin) ({r.status_code} {r.text[:160]})")
# 2.657.0 (#4828): a view is always made private -- not even the admin creates one in the organisation (sharing is /share)
r = A.post(B + f"/api/obj/{K}", json={"title": "Admin's direct", "query": "q=Quokka", "ws": "private", "org_id": ORG})
check(r.status_code == 403 and "Admin's direct" not in str(A.get(B + "/api/docs/views").json()),
      f"rueckfall #4828: the admin's create with org_id is refused, nothing made ({r.status_code} {r.text[:160]})")
BV = Bo.post(B + f"/api/obj/{K}", json={"title": "Bob's own", "query": "q=Quokka", "ws": WS}).json()["id"]
check(view(A, BV) == 404 and BV not in listed(A, WS), "a member's private view: not even the organisation's admin sees it")
check(listed(Bo, WS) == {BV: 1}, "the member's own view counts what he sees")
r = Bo.post(B + f"/api/docs/views/{BV}/share", json={"all": True})
check(r.status_code == 403, f"a member does not share his view with everyone ({r.status_code} {r.text[:160]})")
check(view(A, BV) == 404, "... and it stays private")
r = A.post(B + f"/api/docs/views/{VID}/share", json={"all": True})
check(r.ok and r.json()["shared_all"] and r.json()["org_id"] == ORG and r.json()["moved"], f"the admin shares it with everyone ({r.status_code} {r.text[:200]})")
check(view(Bo, VID).get("role") == "view" and view(Ri, VID).get("role") == "view" and view(Gi, VID) == 404 and view(Ol, VID) == 404
      and view(Fr, VID) == 404, "shared: members and read-only members read it, a guest / another organisation / a freelancer nothing")
# the rueckfall: the member's count and hits are HIS, not the admin's (doc_query runs as the viewer)
check(listed(Bo, WS) == {VID: 1, BV: 1} and listed(A, WS) == {VID: 2}, f"the count with the viewer's rights {listed(Bo, WS)} {listed(A, WS)}")
r = Bo.get(B + f"/api/docs/views/{VID}/hits")
check(r.ok and [d["id"] for d in r.json()["docs"]] == [D1] and r.json()["total"] == 1, f"the member's hits: never the board's document ({r.text[:200]})")
check(Ri.get(B + f"/api/docs/views/{VID}/hits").json()["total"] == 1, "read-only member: the open document only")
check(Bo.patch(B + f"/api/obj/{K}/{VID}", json={"title": "Mine now"}).status_code == 403, "a member does not change the shared view")
check(Bo.post(B + f"/api/obj/{K}/{VID}/trash").status_code == 403, "nor deletes it")
check(Bo.post(B + f"/api/docs/views/{VID}/share", json={"all": False}).status_code == 403, "nor takes it back")
check(A.patch(B + f"/api/obj/{K}/{VID}", json={"ws": "private"}).status_code == 400, "a shared view keeps its organisation's workspace")
# tenant-matrix: obj -- another organisation's admin
check(Ol.get(B + f"/api/docs/views/{VID}/hits").status_code == 404 and Ol.post(B + f"/api/docs/views/{VID}/share", json={"all": False}).status_code == 404
      and listed(Ol) == {}, "another organisation: 404 on the hits and the sharing, nothing listed")
r = A.post(B + f"/api/docs/views/{VID}/share", json={"all": False})
check(r.ok and not r.json()["shared_all"] and view(Bo, VID) == 404 and view(A, VID)["role"] == "manage", f"taken back: only the admin again ({r.text[:200]})")

# ---------------------------------------------------------------- version, rename + undo, delete + restore
cur = view(A, VID)
r = A.patch(B + f"/api/obj/{K}/{VID}", json={"title": "Renamed", "expect_updated_at": cur["updated_at"]})
check(r.ok and r.json()["title"] == "Renamed", f"rename with the version ({r.status_code} {r.text[:160]})")
r = A.patch(B + f"/api/obj/{K}/{VID}", json={"title": "Too late", "expect_updated_at": cur["updated_at"]})
check(r.status_code == 409 and view(A, VID)["title"] == "Renamed", f"a stale version: 409, nothing written ({r.status_code})")
tok = secrets.token_hex(16)
r = A.patch(B + f"/api/obj/{K}/{VID}", json={"query": "q=Quokka&review=1"}, headers={"X-Kalmido-Undo": tok})
check(r.ok and r.json()["query"] == "q=Quokka&review=1", "take over other filters (an undo step)")
r = A.post(B + f"/api/obj/{K}/{VID}/undo", json={"sess": tok, "op": "undo"})
check(r.ok and view(A, VID)["query"] == "q=Quokka&sort=date&dir=desc", f"undo brings the old search back ({r.status_code} {r.text[:160]})")
check(A.post(B + f"/api/obj/{K}/{VID}/trash").ok and listed(A, WS) == {} and view(A, VID) == 404, "deleted: gone from the list")
check(A.post(B + f"/api/obj/{K}/{VID}/restore").ok and listed(A, WS) == {VID: 2}, "undo of the delete: back with its count")

# ---------------------------------------------------------------- what does not move
PV = A.post(B + f"/api/obj/{K}", json={"title": "Private ones", "query": "q=Quokka", "ws": "private"}).json()["id"]
r = A.post(B + f"/api/docs/views/{PV}/share", json={"all": True})
check(r.status_code == 409, f"a view of the private workspace is not shared with the organisation ({r.status_code})")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})


def agent(name, org=None):
    r = A.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "tasks:write"], **({"org_id": org} if org else {})})
    check(r.ok, f"setup: agent {name} " + r.text[:160])
    return r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}


def agent_ids(h):
    return [x["id"] for x in requests.get(B + f"/api/v1/agent/objects/{K}", headers=h, timeout=30).json().get("data", [])]


OAID, OAH = agent("orgbot", ORG)  # the organisation's agent
PAID, PAH = agent("ownbot", "private")  # alice's own agent of her private workspace
check(agent_ids(OAH) == [] and agent_ids(PAH) == [] and requests.get(B + f"/api/v1/agent/objects/{K}/{VID}", headers=PAH, timeout=30).status_code == 404,
      "agents: nothing without a share")
st = (requests.get(B + "/api/docs/views", headers=OAH, timeout=30).status_code, requests.get(B + f"/api/docs/views/{VID}/hits", headers=PAH, timeout=30).status_code)
check(all(x in (401, 403) for x in st), f"agents: the person routes refuse them (an agent token is no session there) {st}")
check(A.post(B + f"/api/docs/views/{VID}/share", json={"all": True}).ok and agent_ids(OAH) == [], "shared with everyone: still nothing for the organisation's agent")
check(A.post(B + f"/api/docs/views/{VID}/share", json={"all": False}).ok, "back to private")
r = A.post(B + f"/api/obj/{K}/{VID}/shares", json={"agent_id": PAID, "role": "view"})
check(r.status_code == 201 and agent_ids(PAH) == [VID], f"shared with her own agent: it reads the view ({r.status_code} {r.text[:160]})")
r = A.post(B + f"/api/docs/views/{VID}/share", json={"all": True})
check(r.status_code == 409 and view(Bo, VID) == 404, f"a view with a share of its own does not move ({r.status_code} {r.text[:160]})")

# ---------------------------------------------------------------- 2.657.0 (#4828): the shares are checked before org_out
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "admin"}).ok, "setup: bob an admin for a while")
r = Bo.post(B + f"/api/docs/views/{BV}/share", json={"all": True})
check(r.ok and r.json()["shared_all"], f"setup: bob (admin) shares his view with everyone ({r.status_code} {r.text[:160]})")
r = Bo.post(B + f"/api/obj/{K}/{BV}/shares", json={"user_id": uid["rita"], "role": "view"})
check(r.status_code == 201, f"setup: a share of its own ({r.status_code} {r.text[:160]})")
BSID = r.json()["id"]
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "member"}).ok, "setup: bob a member again")
r = Bo.post(B + f"/api/docs/views/{BV}/share", json={"all": False})
check(r.status_code == 409, f"rueckfall #4828: the share is named first (409), not org_out's 403 ({r.status_code} {r.text[:160]})")
check(Bo.delete(B + f"/api/obj/{K}/{BV}/shares/{BSID}").ok, "setup: the share taken back")
r = Bo.post(B + f"/api/docs/views/{BV}/share", json={"all": False})
check(r.status_code == 403 and view(A, BV).get("org_id") == ORG, f"a member does not take it out of the organisation ({r.status_code})")
check(A.post(B + f"/api/docs/views/{BV}/share", json={"all": False}).ok and view(A, BV) == 404, "the admin takes it back: bob's own again")

# ---------------------------------------------------------------- Today and the favourites
check(A.patch(B + "/api/settings", json={"dv_today": f"{VID},{VID},{PV}"}).ok and A.get(B + "/api/state").json()["settings"]["dv_today"] == f"{VID},{PV}",
      "dv_today: ids, each once")
check(A.patch(B + "/api/settings", json={"dv_today": "1,x"}).status_code == 400, "dv_today: only ids")
check(A.patch(B + "/api/settings", json={"fav_items": f'["r:docview:{VID}"]'}).ok, "a view as a favourite")
r = A.get(B + "/api/favorites/targets").json()
check(r["items"].get(f"r:docview:{VID}", {}).get("to") == f"docs/v/{VID}", f"the favourite opens the view {r}")
check(Bo.patch(B + "/api/settings", json={"fav_items": f'["r:docview:{VID}"]'}).ok and Bo.get(B + "/api/favorites/targets").json()["gone"] == [f"r:docview:{VID}"],
      "whoever cannot see it: the favourite is gone")

# ---------------------------------------------------------------- freelancer-matrix: obj -- a person without an organisation
F1 = doc_new(Fr, "receipt.txt", "Rechnung Wombat private", "private")
r = Fr.post(B + f"/api/obj/{K}", json={"title": "Wombat", "query": "q=Wombat", "ws": "private"})
check(r.status_code == 201, "freelancer: her own view")
FV = r.json()["id"]
check(listed(Fr, "private") == {FV: 1} and Fr.get(B + f"/api/docs/views/{FV}/hits").json()["docs"][0]["id"] == F1, "freelancer: count and hits")
check(Fr.post(B + f"/api/docs/views/{FV}/share", json={"all": True}).status_code == 409, "freelancer: no organisation to share it with")
check(view(A, FV) == 404 and FV not in listed(A, "private"), "the instance admin does not see her view")
sys.exit(done("p2579_c_api"))
