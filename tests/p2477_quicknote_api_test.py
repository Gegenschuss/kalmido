#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.477.0 (#3881) API tests, own container (kt.fresh): the private list "Notes" of the quick note.
 - POST /api/notes/quick-list makes the list once (private, lists.quicknote = 1, the name in the person's language) and
   answers the same one later; a note without a title takes the first line of its text
 - the list can never be shared: members (web + REST API), a group, the agent of the list, "share all lists" with an agent,
   a public link, another owner, a workspace, a folder (PATCH and dragging), agent switches -> refused (409
   quicknote_private) or left out; renaming it does not unlock it
 - a note moved out of it to other people: 409 quicknote_share with their names, only with share_ok; into a list of mine
   alone without a question
 - DELETE /api/notes/<id>?empty=1: only an empty note of mine, gone for good (never in the trash)
 - freelancer-matrix: tasks (a person without an organisation: the same list, the same lock)
usage: p2477_quicknote_api_test.py <datadir>"""
import sys

import kt
from kt import B, FAILS, OKS, check, sess  # noqa: F401
from freelancer_fixture import freelancer, org_join

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments,agents"})
AID = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": AID})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
org_join(B, "alice", ORG)
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": [ORG]})
assert r.ok, r.text
BID = r.json()["id"]
org_join(B, "bob", ORG)
FID, Fr = freelancer(B, A, "frida")


def lst(s, lid):
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)


def private_code(r):
    return r.status_code == 409 and (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("code") == "quicknote_private"


# ================= the list: made once, private
r = A.post(B + "/api/notes/quick-list")
check(r.status_code == 201 and r.json().get("created") is True, f"the first call makes the list {r.status_code} {r.text[:200]}")
Q = r.json()["list_id"]
r = A.post(B + "/api/notes/quick-list")
check(r.ok and r.json() == {"list_id": Q, "created": False}, f"the second call answers the same list {r.text[:200]}")
ql = lst(A, Q)
check(ql and ql["quicknote"] == 1 and ql["name"] == "Notes" and not ql.get("org_id") and not ql.get("shared"), f"private, marked, named Notes {ql and {k: ql.get(k) for k in ('quicknote', 'name', 'org_id', 'shared')}}")

# ================= the first line is the title
r = A.post(B + f"/api/lists/{Q}/notes", json={"body": "\n# Shopping list\nmilk\nbread"})
check(r.status_code == 201 and r.json()["title"] == "Shopping list", f"no title: the first line with text (without #) {r.status_code} {r.text[:200]}")
N1 = r.json()["id"]
r = A.post(B + f"/api/lists/{Q}/notes", json={"body": "   "})
check(r.status_code == 400, f"an empty note without a title stays refused {r.status_code}")

# ================= never shared
check(private_code(A.put(B + f"/api/lists/{Q}/members", json={"user_id": BID, "role": "edit"})), "members: refused (409 quicknote_private)")
r = A.post(B + "/api/admin/groups", json={"name": "Garden", "members": [BID]})
GID = r.json().get("id") if r.ok else None
check(GID and private_code(A.put(B + f"/api/lists/{Q}/groups/{GID}", json={"role": "edit"})), f"a group: refused {r.status_code}")
check(private_code(A.post(B + f"/api/lists/{Q}/owner", json={"user_id": BID})), "another owner: refused")
check(private_code(A.patch(B + f"/api/lists/{Q}", json={"org_id": ORG})), "into the organisation's workspace: refused")
check(private_code(A.patch(B + f"/api/lists/{Q}", json={"folder": "Garden"})), "into a folder: refused")
check(private_code(A.patch(B + f"/api/lists/{Q}", json={"agent_members": 1})), "members' agents: refused")
r = A.put(B + f"/api/lists/{Q}/public-link", json={"mode": "view"})
check(r.status_code == 409, f"a public link: refused {r.status_code} {r.text[:120]}")
r = A.post(B + "/api/admin/agents", json={"username": "helper", "display_name": "Helper"})
AG = r.json().get("id") if r.ok else None
check(bool(AG), f"setup: an agent {r.status_code} {r.text[:120]}")
if AG:
    check(private_code(A.put(B + f"/api/lists/{Q}/agent", json={"agent_id": AG})), "the agent of the list: refused")
    r = A.post(B + f"/api/agents/{AG}/share-all")
    check(r.ok, f"share all lists with the agent works for the others {r.status_code} {r.text[:120]}")
    check(not lst(A, Q).get("members"), f"… the list Notes is left out {lst(A, Q).get('members')}")
r = A.post(B + "/api/lists/reorder", json={"folder": {str(Q): "Garden"}})
check(r.ok and (lst(A, Q).get("folder") or "") == "", f"dragged into a folder: stays out of it {r.status_code} {lst(A, Q).get('folder')}")
r = A.patch(B + f"/api/lists/{Q}", json={"name": "Ideas", "org_id": None, "folder": "", "agent_tidy": "off"})
check(r.ok and lst(A, Q)["name"] == "Ideas" and lst(A, Q)["quicknote"] == 1, f"renamed (unchanged off values along): still the list Notes {r.status_code} {r.text[:200]}")
check(private_code(A.put(B + f"/api/lists/{Q}/members", json={"user_id": BID, "role": "view"})), "renamed: sharing stays refused")
tok = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "write"]})
check(tok.ok and bool(tok.json().get("token")), f"setup: a token of Alice {tok.status_code} {tok.text[:120]}")
if tok.ok and tok.json().get("token"):
    T = sess()
    T.headers.update({"Authorization": "Bearer " + tok.json()["token"]})
    r = T.put(B + f"/api/v1/lists/{Q}/members/{BID}", json={"role": "edit"})
    check(r.status_code == 409, f"REST API members: refused {r.status_code} {r.text[:160]}")
check(not lst(A, Q).get("members"), "after all of it: no member")
check(lst(sess("bob"), Q) is None, "Bob does not see the list")

# ================= a note moves out only after the yes
SH = A.post(B + "/api/lists", json={"name": "Shared garden"}).json()["id"]
assert A.put(B + f"/api/lists/{SH}/members", json={"user_id": BID, "role": "edit"}).ok
r = A.patch(B + f"/api/notes/{N1}", json={"list_id": SH})
j = r.json()
check(r.status_code == 409 and j.get("code") == "quicknote_share" and j.get("people") == ["Bob"], f"to other people: 409 with their names {r.status_code} {j}")
check(A.get(B + f"/api/notes/{N1}").json()["list_id"] == Q, "… the note stays where it was")
r = A.patch(B + f"/api/notes/{N1}", json={"list_id": SH, "share_ok": True})
check(r.ok and r.json()["list_id"] == SH, f"with the yes it moves {r.status_code} {r.text[:120]}")
MINE = A.post(B + "/api/lists", json={"name": "Mine alone"}).json()["id"]
N2 = A.post(B + f"/api/lists/{Q}/notes", json={"body": "Idea"}).json()["id"]
r = A.patch(B + f"/api/notes/{N2}", json={"list_id": MINE})
check(r.ok and r.json()["list_id"] == MINE, f"into a list of mine alone: no question {r.status_code}")

# ================= left empty: gone for good
N3 = A.post(B + f"/api/lists/{Q}/notes", json={"body": "x"}).json()["id"]
r = A.delete(B + f"/api/notes/{N3}?empty=1")
check(r.status_code == 409, f"with text: not purged {r.status_code}")
assert A.patch(B + f"/api/notes/{N3}", json={"body": ""}).ok
r = A.delete(B + f"/api/notes/{N3}?empty=1")
check(r.ok and r.json().get("purged") is True, f"empty: purged {r.status_code} {r.text[:120]}")
check(A.get(B + f"/api/notes/{N3}").status_code == 404, "… gone")
tr_ = A.get(B + f"/api/lists/{Q}/notes?trash=1").json().get("notes", [])
check(all(n["id"] != N3 for n in tr_), "… not in the trash")

# ================= freelancer: the same
r = Fr.post(B + "/api/notes/quick-list")
check(r.status_code == 201, f"freelancer: her list Notes {r.status_code} {r.text[:120]}")
FQ = r.json()["list_id"]
check(FQ != Q and lst(Fr, FQ)["quicknote"] == 1 and not lst(Fr, FQ).get("org_id"), "freelancer: her own private list")
r = Fr.post(B + f"/api/lists/{FQ}/notes", json={"body": "Call the tax office\ntomorrow"})
check(r.status_code == 201 and r.json()["title"] == "Call the tax office", f"freelancer: first line = title {r.text[:120]}")
FN = r.json()["id"]
check(private_code(Fr.put(B + f"/api/lists/{FQ}/members", json={"user_id": AID, "role": "edit"})), "freelancer: sharing refused")
assert Fr.patch(B + f"/api/notes/{FN}", json={"body": ""}).ok
check(Fr.delete(B + f"/api/notes/{FN}?empty=1").ok and Fr.get(B + f"/api/notes/{FN}").status_code == 404, "freelancer: empty = gone for good")
Bo = sess("bob")
assert Bo.patch(B + f"/api/notes/{N1}", json={"body": ""}).ok
check(Bo.delete(B + f"/api/notes/{N1}?empty=1").status_code == 409 and A.get(B + f"/api/notes/{N1}").ok, "an empty note of somebody else is never purged that way")

sys.exit(kt.done("p2477_quicknote"))
