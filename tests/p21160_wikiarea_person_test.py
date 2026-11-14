#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1160.0 (#5862): a whole private knowledge area shared with a PERSON (until now agents only, #5823). Invented names only.
 - Frida (no organisation) shares her area "Knowledge" (POST /api/files/nodes/<root>/shares {user_id}) with Bob: the root's
   share targets offer people (no groups); the dialog's question (GET /api/wiki/area-share&user_id=) counts what he will see
 - Bob: "Shared with me" (GET /api/wiki/shared) lists every page (paths from "Knowledge" on) and the folder "Knowledge" with
   Frida's name, reads a page, a page made later in a new folder at once; 'view' adds nothing, 'edit' adds a page at the top
   (POST /api/wiki/shared/pages with the root as folder_id): the page is Frida's
 - exclusions are the share's own (PATCH /api/files/shares/<id> {excluded}): the folder and all below it are gone for Bob
   (list, read 404, the folder list, a page made there later), the folder's dialog marks the area share "excluded here";
   a folder inside shared with him on its own wins; invalid values 400 (the root, another tree's folder, not a list, a share
   that is not a whole area's); another person cannot change them
 - an organisation's area stays with its agents: its root offers no person and refuses one (409)
 - Fable review: deleting her account hands Bob only the pages he sees; the share made again (Undo) keeps its exclusions
 - ending the share takes the area away at once (the folder shared on its own stays)
 - freelancer-matrix: wiki (Frida has no organisation; she shares her own area)
usage: p21160_wikiarea_person_test.py <datadir>"""
import sys

import kt
from kt import B, check, dbx, sess
from freelancer_fixture import FEATURES, freelancer

FEAT = FEATURES + ",wiki,files,collab"

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
FID, F = freelancer(B, A, features=FEAT)
OID, OTTO = freelancer(B, A, "otto", features=FEAT)
a_, b_ = sorted((FID, BOB))  # an accepted connection (accounts/discover.py): she may share with him (as p2200_b_wiki_share)
dbx("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?, ?, '2026-01-01T00:00:00Z')", (a_, b_))


def page(s, path, space="private", text="text"):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, (path, r.status_code, r.text)
    return r.json()["id"]


def index(s, space="private"):
    j = s.get(B + "/api/wiki", params={"space": space}).json()
    return j.get("root"), {f["path"]: f["id"] for f in j.get("folders", [])}


def shared(s):
    j = s.get(B + "/api/wiki/shared").json()
    return {p["id"]: p["path"] for p in j.get("pages", [])}, j.get("folders", [])


def reads(s, pid):
    return s.get(B + f"/api/wiki/shared/pages/{pid}").status_code


def area(s, space="private", **q):
    return s.get(B + "/api/wiki/area-share", params={"space": space, **q}).json()


def excl(s, sid, value):
    return s.patch(B + f"/api/files/shares/{sid}", json={"excluded": value})


P_ONE = page(F, "One/Alpha", text="alpha text")
P_TWO = page(F, "Two/Beta", text="beta text")
P_SEC = page(F, "Private/Secret", text="secret words")
P_SUB = page(F, "Private/Inside/Open", text="open words")
ROOT, FOLD = index(F)
check(ROOT and {"One", "Two", "Private", "Private/Inside"} <= set(FOLD), f"setup: the tree {ROOT} {FOLD}")
check(shared(Bo)[0] == {}, "before the share: Bob sees none of her pages")

# ---- the share
t = F.get(B + f"/api/files/nodes/{ROOT}/share-targets").json()
check(BOB in [x["id"] for x in t["people"]] and t["groups"] == [], f"the private root offers people (no groups): {t}")
pv = area(F, user_id=BOB)["preview"]
check(pv == {"user_id": BOB, "folders": 4, "pages": 4, "excluded": 0}, f"the dialog's question for a person: {pv}")
r = F.post(B + f"/api/files/nodes/{ROOT}/shares", json={"user_id": BOB, "role": "view"})
check(r.status_code == 201, f"freelancer-matrix: wiki -- her whole area shared with a person: {r.status_code} {r.text[:200]}")
SID = r.json().get("id")
L, FS = shared(Bo)
check(set(L) == {P_ONE, P_TWO, P_SEC, P_SUB}, f"Bob lists every page of the area: {L}")
check(L.get(P_ONE) == "Knowledge/One/Alpha", f"the paths start at Knowledge: {L.get(P_ONE)}")
top = [f for f in FS if f["parent_id"] is None]
check(len(top) == 1 and top[0]["id"] == ROOT and top[0]["name"] == "Knowledge" and top[0]["owner_name"] == "Frida",
      f"'Shared with me' shows the folder Knowledge with her name: {top}")
check({f["path"] for f in FS} >= {"Knowledge/One", "Knowledge/Private/Inside"}, f"and its folders: {[f['path'] for f in FS]}")
g = Bo.get(B + f"/api/wiki/shared/pages/{P_ONE}")
check(g.ok and g.json().get("body") == "alpha text", f"Bob reads a page: {g.status_code}")
P_NEW = page(F, "Three/Later", text="later text")
check(P_NEW in shared(Bo)[0], "a page made later in a new folder: Bob sees it at once")
r = Bo.post(B + "/api/wiki/shared/pages", json={"folder_id": ROOT, "name": "From Bob", "body": "x"})
check(r.status_code == 403, f"'view': no new page at the top: {r.status_code}")
sh = area(F)["shares"]
check([(x["user_id"], x["agent_id"], x["role"], x["excluded"], x["editable"]) for x in sh] == [(BOB, None, "view", [], True)],
      f"area-share lists the person's share: {sh}")

# ---- exclusions: the share's own
check(excl(F, SID, [FOLD["Private"]]).ok, "Private excluded for Bob")
check(area(F)["shares"][0]["excluded"] == [FOLD["Private"]], f"area-share names it: {area(F)['shares']}")
L, FS = shared(Bo)
check(set(L) == {P_ONE, P_TWO, P_NEW}, f"the excluded folder and all below it are gone for Bob: {L}")
check(not any(f["path"].startswith("Knowledge/Private") for f in FS), f"and from his folder list: {[f['path'] for f in FS]}")
check(reads(Bo, P_SEC) == 404 and reads(Bo, P_SUB) == 404, "reading a page there: 404")
check(Bo.get(B + f"/api/wiki/pages/{P_SEC}").status_code in (403, 404), "also through the page route")
P_LATE = page(F, "Private/Later", text="late")
check(P_LATE not in shared(Bo)[0], "a page made there later stays out")
inh = F.get(B + f"/api/files/nodes/{FOLD['Private']}").json().get("inherited", [])
check(any(x.get("area") and x["user_id"] == BOB and x.get("excluded") for x in inh), f"the folder's dialog: excluded here {inh}")
inh = F.get(B + f"/api/files/nodes/{FOLD['One']}").json().get("inherited", [])
check(any(x.get("area") and x["user_id"] == BOB and not x.get("excluded") for x in inh), f"another folder: shared via the area {inh}")
pv = area(F, user_id=BOB)["preview"]
check(pv["excluded"] == 1 and pv["pages"] == 3, f"the question for Bob again counts his exclusion: {pv}")
r = F.post(B + f"/api/files/nodes/{FOLD['Private/Inside']}/shares", json={"user_id": BOB, "role": "view"})
check(r.status_code == 201, "a folder inside shared with him on its own")
SID2 = r.json().get("id")
L = shared(Bo)[0]
check(P_SUB in L and P_SEC not in L, f"the share of its own wins (only that folder): {L}")
check(reads(Bo, P_SUB) == 200, "he reads its page")
# invalid values
check(excl(F, SID, [ROOT]).status_code == 400, "the root itself: 400")
page(OTTO, "Otto/Note")
check(excl(F, SID, [index(OTTO)[1]["Otto"]]).status_code == 400, "a folder of another tree: 400")
check(excl(F, SID, "x").status_code == 400 and excl(F, SID, [True]).status_code == 400, "not a list of ids: 400")
check(excl(F, SID2, []).status_code == 400, "a share that is not a whole area's: 400")
check(excl(OTTO, SID, []).status_code in (403, 404), "another person cannot change them")
check(excl(Bo, SID, []).status_code in (403, 404), "nor the person it is shared with")
check(area(F)["shares"][0]["excluded"] == [FOLD["Private"]], "the exclusion stayed")

# ---- edit: a page at the top of her area
check(F.patch(B + f"/api/files/shares/{SID}", json={"role": "edit"}).ok, "the share raised to edit")
r = Bo.post(B + "/api/wiki/shared/pages", json={"folder_id": ROOT, "name": "From Bob", "body": "x"})
check(r.status_code == 201, f"'edit': Bob adds a page at the top of her area: {r.status_code} {r.text[:200]}")
PB = r.json().get("id")
mine = {p["id"]: p["path"] for p in F.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]}
check(mine.get(PB) == "From Bob", f"the page is hers, at the top: {mine.get(PB)}")
check(PB not in {p["id"] for p in Bo.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]}, "nothing lands in Bob's own space")

# ---- Fable review 1: deleting her account hands Bob only what he sees (not the excluded folder's pages)
j = F.get(B + "/api/account/delete").json()
to = ((j.get("purge") or {}).get("shared") or {}).get("to", {})
check(to.get("wiki") == 4, f"the delete dialog: Bob takes over the 4 pages he sees (not Private/*): {j.get('purge', {}).get('shared')}")

# ---- Fable review 2: "stop sharing" undone (the share made again) keeps the exclusions
check(F.delete(B + f"/api/files/shares/{SID}").ok, "the area share taken back")
r = F.post(B + f"/api/files/nodes/{ROOT}/shares", json={"user_id": BOB, "role": "edit"})
check(r.status_code == 201, "and made again (the dialog's Undo)")
SID = r.json().get("id")
check(area(F)["shares"][0]["excluded"] == [FOLD["Private"]], f"the exclusion came back with it: {area(F)['shares']}")
check(P_SEC not in shared(Bo)[0], "Private stays out for Bob")

# ---- an organisation's area: agents only (tenant-matrix: wiki)
page(A, "Team/Plan", space=f"org:{ORG}")
OROOT = index(A, f"org:{ORG}")[0]
t = A.get(B + f"/api/files/nodes/{OROOT}/share-targets").json()
check(t["people"] == [] and t["groups"] == [], f"the organisation's root offers no person: {t}")
check(A.post(B + f"/api/files/nodes/{OROOT}/shares", json={"user_id": FID, "role": "view"}).status_code == 409, "org root: a person 409")
check(A.post(B + f"/api/files/nodes/{OROOT}/shares", json={"user_id": BOB, "role": "view"}).status_code == 409, "not even a member")

# ---- ending the share
check(F.delete(B + f"/api/files/shares/{SID}").ok, "the area share ended")
L, FS = shared(Bo)
check(set(L) == {P_SUB}, f"the area is gone at once, the folder shared on its own stays: {L}")
check(reads(Bo, P_ONE) == 404, "a page of the area: 404")

sys.exit(kt.done("p21160_wikiarea_person_test"))
