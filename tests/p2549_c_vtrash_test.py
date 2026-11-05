#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.549.0 C (#4536) API tests, own container: the video trash in the app.
 - GET /api/videos/trash lists the reviews in the video trash the person may see: the own private ones (also those rescued
   without a place when their project was deleted for good, videos/vdrescue.py), the organisation's ones for its members;
   never another person's private review, never an organisation's one for an outsider or a guest
 - POST /api/videos/ID/restore {list_id}: a review without a place goes into a project of its own workspace (then it shows at
   that project); a project of another person: 404, of another workspace: 409; a review that has a place: 409 (it goes back
   there with the plain restore)
The case without an organisation (freelancer fixture) runs the whole way.
freelancer-matrix: videos
usage: p2549_c_vtrash_test.py <datadir>"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, check, dbx, done  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

kt.fresh(prefix="P2549C")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
FID, Fr = freelancer(B, A)
OID, Ot = freelancer(B, A, "otto")
S = {}
for u, role in (("bob", "member"), ("gina", "guest")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as {role} {r.text[:200]}")
    S[u] = kt.sess(u)
    S[u].patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})


def project(s, name, org=None):
    return s.post(B + "/api/lists", json={"name": name, "kind": "project", "org_id": org}).json()["id"]


def review(s, **place):
    r = s.post(B + "/api/videos", json={"title": "Cut", "url": "https://vimeo.com/123456789", **place})
    assert r.ok, r.text
    return r.json()["id"]


def placeless(s, who, org=None):
    """A review whose project was deleted for good: in the video trash without a place."""
    lid = project(s, f"Gone {who}", org)
    vid = review(s, list_id=lid)
    s.patch(B + f"/api/lists/{lid}", json={"archived": True})
    check(s.delete(B + f"/api/lists/{lid}").ok and s.delete(B + f"/api/trash/lists/{lid}").ok, f"{who}: project deleted for good")
    r = dbx("SELECT task_id, list_id, client_id, deleted_at FROM video_reviews WHERE id=?", (vid,))
    check(r and r[0][:3] == (None, None, None) and r[0][3], f"{who}: the review lies in the video trash without a place {r}")
    return vid


def trash(s):
    r = s.get(B + "/api/videos/trash")
    return {x["id"]: x for x in r.json().get("reviews", [])} if r.ok else {"status": r.status_code}


# ================================================================== a person without an organisation
VF = placeless(Fr, "frida")
t = Fr.get(B + "/api/videos/trash").json()
x = {r["id"]: r for r in t["reviews"]}.get(VF)
check(x and x["can_restore"] and x["list_id"] is None and x["task_id"] is None and x["client_id"] is None and x["deleted_at"]
      and x["space"] == "private" and x["version"] == 1, f"frida: her review without a place is in her video trash {x}")
check(isinstance(t.get("trash_days"), int) and t["trash_days"] >= 1 and "purge_on" in t, f"frida: the trash period comes along {t}")
check(VF not in trash(Ot), "otto does not see frida's video trash")
check(Ot.post(B + f"/api/videos/{VF}/restore").status_code == 404, "otto cannot restore frida's review")
LO = project(Ot, "Otto's")
check(Fr.post(B + f"/api/videos/{VF}/restore", json={"list_id": LO}).status_code == 404, "frida: into otto's project: 404")
check(dbx("SELECT deleted_at FROM video_reviews WHERE id=?", (VF,))[0][0], "frida: the refused restore left it in the trash")
LF = project(Fr, "Frida new")
r = Fr.post(B + f"/api/videos/{VF}/restore", json={"list_id": LF})
check(r.ok and r.json().get("list_id") == LF and not r.json().get("deleted"), f"frida: restored into her project {r.text[:200]}")
check(VF in [v["id"] for v in Fr.get(B + f"/api/videos?list_id={LF}").json()["reviews"]] and VF not in trash(Fr),
      "frida: it shows at the project and left the trash")
# a review that has a place: the plain restore brings it back there, a project is refused
V2 = review(Fr, list_id=LF)
check(Fr.delete(B + f"/api/videos/{V2}").ok and trash(Fr).get(V2, {}).get("list_id") == LF, "frida: a deleted review at her project is in the trash with its place")
check(Fr.post(B + f"/api/videos/{V2}/restore", json={"list_id": project(Fr, "Other")}).status_code == 409, "frida: a review with a place: 409 for another project")
check(Fr.post(B + f"/api/videos/{V2}/restore").ok and V2 in [v["id"] for v in Fr.get(B + f"/api/videos?list_id={LF}").json()["reviews"]],
      "frida: the plain restore brings it back to its project")

# ================================================================== an organisation
VO = placeless(A, "alice-org", ORG)
check(VO in trash(A) and trash(A)[VO]["space"] == f"org:{ORG}", "alice: the organisation's review is in her video trash")
check(VO in trash(S["bob"]) and trash(S["bob"])[VO]["can_restore"], "bob (member): sees and may restore the organisation's review")
check(VO not in trash(S["gina"]), "gina (guest): does not see the organisation's review")
check(VO not in trash(Fr) and VO not in trash(Ot), "people outside the organisation do not see it")
check(Fr.post(B + f"/api/videos/{VO}/restore").status_code == 404, "frida cannot restore the organisation's review")
LP = project(A, "Alice private")
check(A.post(B + f"/api/videos/{VO}/restore", json={"list_id": LP}).status_code == 409, "alice: into a private project (another workspace): 409")
LA = project(S["bob"], "Alpha new", ORG)
r = S["bob"].post(B + f"/api/videos/{VO}/restore", json={"list_id": LA})
check(r.ok and r.json().get("list_id") == LA, f"bob: restored into the organisation's project {r.text[:200]}")
check(S["bob"].post(B + f"/api/videos/{VO}/restore").status_code == 404, "a second restore: 404 (no longer in the trash)")
check(trash(S["bob"]).get("status") is None, "the list answers")
sys.exit(done("p2549_c_vtrash"))
