#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1045.0 B (#5823): a whole knowledge area shared with an agent at once + single folders excluded. Invented names only.
 - the share is the file store's (POST /api/files/nodes/<root "Knowledge">/shares): the root takes agent shares only (a
   person 409), the private area only the person's own agent (an organisation's agent, another person's agent 409), an
   encrypted area 409
 - the agent lists every page (paths from "Knowledge" on), reads and changes one, sees a page made later in a new folder
 - exclusion = the agent's data lock wiki_folders (PATCH /api/agents/<id>/data-lock): the folder and everything below it is
   gone for the agent (list, read 404, search, the file store's API, a page made there later, a new page there 404); the
   gear names it, the agent only counts it; a folder inside shared on its own wins; renamed it stays excluded; invalid ids 400
 - review M2 / N5: an excluded folder the editor sees only through a share on it is named without the folders above
   (gear and "Sees now"); taking an exclusion off needs the same right as adding it (a folder that is gone: always)
 - GET /api/wiki/area-share: counts, the agent shares with their exclusions, the preview of the dialog's question
 - ending the share: nothing at once; an organisation's area with its own agent (and not the private one)
 - freelancer-matrix: wiki (a person without an organisation and her own agent)
usage: p21045_b_wikiarea_test.py <datadir>"""
import sys

import requests

import kt
from kt import B, check, dbx, sess
from freelancer_fixture import FEATURES, freelancer

V = B + "/api/v1"
SC = ["read", "wiki:read", "wiki:write", "files:read"]

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES + ",wiki,files", "tour": "done"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
FID, F = freelancer(B, A, features=FEATURES + ",wiki,files")
OID, O = freelancer(B, A, "otto", features=FEATURES + ",wiki,files")


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def agent(name, org=None, owner=None):
    body = {"scopes": SC, "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


def page(s, path, space="private", text="text"):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, (path, r.status_code, r.text)
    return r.json()["id"]


def index(s, space="private"):
    j = s.get(B + "/api/wiki", params={"space": space}).json()
    return j.get("root"), {f["path"]: f["id"] for f in j.get("folders", [])}


def listed(t):
    r = t.get(V + "/wiki/pages")
    return {p["id"]: p["path"] for p in r.json()["data"]} if r.ok else {}


def found(t, q):
    r = t.get(V + "/search", params={"kind": "wiki", "q": q})
    return [p["id"] for p in r.json().get("data", [])] if r.ok else []


def lock(s, aid, method="get", **kw):
    return getattr(s, method)(B + f"/api/agents/{aid}/data-lock", **kw)


def area(s, space="private", aid=None):
    return s.get(B + "/api/wiki/area-share", params={"space": space, **({"agent_id": aid} if aid else {})}).json()


# ================================================================ a person without an organisation (freelancer-matrix: wiki)
DA, da = agent("fridabot", owner=FID)
OA, oa = agent("ottobot", owner=OID)
TA, ta = agent("teambot", org=ORG)
P_ONE = page(F, "One/Alpha", text="alpha text")
P_TWO = page(F, "Two/Beta", text="beta text")
P_SEC = page(F, "Private/Secret", text="ZQXPRIV hidden words")
P_SUB = page(F, "Private/Inside/Open", text="ZQXSUB open words")
ROOT, FOLD = index(F)
check(ROOT and {"One", "Two", "Private", "Private/Inside"} <= set(FOLD), f"setup: the tree {ROOT} {FOLD}")
check(listed(da) == {}, "before the share: the agent sees no page")
check(area(F)["may"] is True and area(F)["shares"] == [] and area(F)["pages"] == 4, f"area-share before: {area(F)}")

r = F.get(B + f"/api/files/nodes/{ROOT}/share-targets")
t = r.json()
check(r.ok and [x["id"] for x in t["agents"]] == [DA] and t["people"] == [] and t["groups"] == [],
      f"the root offers only her own agent: {t}")
check(F.post(B + f"/api/files/nodes/{ROOT}/shares", json={"user_id": OID, "role": "view"}).status_code == 409, "a person: 409")
check(F.post(B + f"/api/files/nodes/{ROOT}/shares", json={"agent_id": TA, "role": "view"}).status_code == 409,
      "an organisation's agent never gets the private area (409)")
check(F.post(B + f"/api/files/nodes/{ROOT}/shares", json={"agent_id": OA, "role": "view"}).status_code == 409,
      "another person's agent: 409")
check(O.post(B + f"/api/files/nodes/{ROOT}/shares", json={"agent_id": OA, "role": "view"}).status_code in (403, 404),
      "another person cannot share her area")
check(F.patch(B + f"/api/files/nodes/{ROOT}", json={"name": "Renamed"}).status_code == 409, "the root still cannot be renamed")

pv = area(F, aid=DA)["preview"]
check(pv == {"agent_id": DA, "folders": 4, "pages": 4, "excluded": 0}, f"the dialog's question before: {pv}")
r = F.post(B + f"/api/files/nodes/{ROOT}/shares", json={"agent_id": DA, "role": "edit"})
check(r.status_code == 201, f"shared with her own agent (edit): {r.status_code} {r.text[:200]}")
SID = r.json()["id"]
L = listed(da)
check(set(L) == {P_ONE, P_TWO, P_SEC, P_SUB}, f"the agent lists every page: {L}")
check(L.get(P_ONE) == "Knowledge/One/Alpha", f"the agent's paths start at Knowledge: {L.get(P_ONE)}")
g = da.get(V + f"/wiki/pages/{P_ONE}")
check(g.ok and g.json()["body"] == "alpha text" and g.json()["role"] == "edit", f"reads a page: {g.status_code}")
u = da.patch(V + f"/wiki/pages/{P_ONE}", json={"body": "alpha changed", "expect_updated_at": g.json()["updated_at"]})
check(u.ok and F.get(B + f"/api/wiki/pages/{P_ONE}").json()["body"] == "alpha changed", f"changes a page: {u.status_code} {u.text[:200]}")
P_NEW = page(F, "Three/Later", text="later text")
check(P_NEW in listed(da), "a page made later in a new folder: the agent sees it at once")
check(P_ONE in found(da, "alpha"), "the search finds a page of the area")
ROOT2, FOLD = index(F)
nf = da.post(V + "/wiki/pages", json={"folder_id": ROOT, "name": "From the agent", "body": "x"})
check(nf.status_code == 201, f"the agent may add a page at the top of the area (edit): {nf.status_code} {nf.text[:160]}")
inh = F.get(B + f"/api/files/nodes/{FOLD['One']}").json().get("inherited", [])
check(any(x.get("area") and x["agent_id"] == DA for x in inh), f"a folder's dialog: shared via the whole area {inh}")

# ---------------------------------------------------------------- exclusions (the agent's data lock)
PRIV = FOLD["Private"]
check(lock(F, DA, "patch", json={"wiki_folders": [PRIV]}).ok, "Private excluded")
wf = lock(F, DA).json()["data_lock"]["wiki_folders"]
check(wf == [{"id": PRIV, "name": "Private", "path": "Knowledge/Private"}], f"the gear names it: {wf}")
me_a = da.get(V + "/agent").json().get("data_lock", {})
check(me_a.get("wiki_folders_count") == 1 and "Private" not in str(me_a), f"the agent only counts it: {me_a}")
L = listed(da)
check(P_SEC not in L and P_SUB not in L and P_ONE in L and P_NEW in L, f"excluded: gone from the list, the rest stays {L}")
check(da.get(V + f"/wiki/pages/{P_SEC}").status_code == 404 and da.get(V + f"/wiki/pages/{P_SUB}").status_code == 404, "excluded: 404")
check(da.patch(V + f"/wiki/pages/{P_SEC}", json={"body": "x", "expect_updated_at": "x"}).status_code == 404, "excluded: no write")
check(found(da, "ZQXPRIV") == [] and found(da, "ZQXSUB") == [], "excluded: not in the search")
check(da.post(V + "/wiki/pages", json={"folder_id": PRIV, "name": "Sneak", "body": "x"}).status_code == 404, "no new page in it")
P_LATE = page(F, "Private/Later secret", text="ZQXLATE")
check(P_LATE not in listed(da) and da.get(V + f"/wiki/pages/{P_LATE}").status_code == 404, "a page made there later: not for the agent")
kids = da.get(V + f"/files/{ROOT}").json().get("children", [])
check(PRIV not in [k["id"] for k in kids] and FOLD["One"] in [k["id"] for k in kids], f"the file store's API: not among the children {kids}")
check(da.get(V + f"/files/{PRIV}").status_code == 404 and da.get(V + f"/files/{FOLD['Private/Inside']}").status_code == 404,
      "the file store's API: the folder and below 404")
top = da.get(V + "/files").json().get("data", [])
check(all("Private" not in str(x) for x in top), f"the file store's top: nothing of it {top}")
for url in ("/wiki/pages", f"/files/{ROOT}", "/files", "/search?q=ZQX", "/search?kind=wiki&q=ZQX", "/agent/events?since=0&limit=500"):
    body = da.get(V + url).text
    check("ZQXPRIV" not in body and "ZQXSUB" not in body and "ZQXLATE" not in body and "Secret" not in body,
          f"the marker shows up nowhere: {url}")
a = area(F)
check(a["shares"] and a["shares"][0]["agent_id"] == DA and a["shares"][0]["excluded"] == [PRIV] and a["shares"][0]["editable"],
      f"area-share names the exclusion: {a['shares']}")
pv = area(F, aid=DA)["preview"]
check(pv["excluded"] == 1 and pv["pages"] == 4 and pv["folders"] == 3, f"the dialog's question: {pv}")
inh = F.get(B + f"/api/files/nodes/{FOLD['Private/Inside']}").json().get("inherited", [])
check(any(x.get("area") and x.get("excluded") and x["agent_id"] == DA for x in inh), f"an excluded folder's dialog says so {inh}")

# a folder inside shared on its own wins
r = F.post(B + f"/api/files/nodes/{FOLD['Private/Inside']}/shares", json={"agent_id": DA, "role": "view"})
check(r.status_code == 201, f"Private/Inside shared on its own: {r.status_code}")
L = listed(da)
check(P_SUB in L and P_SEC not in L, f"the folder shared on its own is visible, the rest of Private not: {L}")
check(da.get(V + f"/wiki/pages/{P_SUB}").ok and P_SUB in found(da, "ZQXSUB") and found(da, "ZQXPRIV") == [], "read + search: only the inner one")
check(da.get(V + f"/wiki/pages/{P_SUB}").json()["role"] == "view", "the inner one with its own role (view)")
F.delete(B + f"/api/files/shares/{r.json()['id']}")
check(P_SUB not in listed(da), "its own share ended: excluded again")

# renamed / moved: the exclusion stays with the folder
check(F.patch(B + f"/api/files/nodes/{PRIV}", json={"name": "Hidden"}).ok, "Private renamed to Hidden")
L = listed(da)
check(P_SEC not in L and P_SUB not in L and da.get(V + f"/wiki/pages/{P_SEC}").status_code == 404, f"renamed: still excluded {L}")
check(lock(F, DA).json()["data_lock"]["wiki_folders"][0]["name"] == "Hidden", "the gear shows the new name")

# invalid exclusions
PNODE = F.get(B + f"/api/wiki/pages/{P_ONE}").json()["node_id"]
for bad, why in (([ROOT], "the root"), (["x"], "not an id"), ([PNODE], "a page's node"), ([10 ** 9], "nothing")):
    check(lock(F, DA, "patch", json={"wiki_folders": bad}).status_code == 400, f"invalid exclusion ({why}): 400")
_, OF = (page(O, "Otto/Page"), index(O))
check(lock(F, DA, "patch", json={"wiki_folders": [OF[1]["Otto"]]}).status_code == 400, "another person's folder: 400")
check(lock(O, DA, "patch", json={"wiki_folders": []}).status_code == 404, "another person cannot change the exclusions")

# 2.1045.0 review M2 + N5: an exclusion on a folder the editor sees only through a share on it (bob, a colleague in Alpha,
# shares "Docs" under "ZQXGeheim/Intern" with alice): the gear and "Sees now" name it without the folders above; she
# cannot take it off (N5)
import json  # noqa: E402
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123",
                                   "email": "bob@example.com"})
check(r.ok, f"setup: bob {r.status_code} {r.text[:160]}")
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES + ",wiki,files", "tour": "done"})
AA, aa = agent("alicebot", owner=ALICE)
P_DOC = page(Bo, "ZQXGeheim/Intern/Docs/Plan", text="plan")
DOCS = index(Bo)[1]["ZQXGeheim/Intern/Docs"]
r = Bo.post(B + f"/api/files/nodes/{DOCS}/shares", json={"user_id": ALICE, "role": "view"})
check(r.status_code == 201, f"setup: Docs shared with alice {r.status_code} {r.text[:200]}")
check(A.get(B + f"/api/wiki/pages/{P_DOC}").ok, "setup: alice reads the page through the share")
page(A, "Mine/Note")
MINE = index(A)[1]["Mine"]
check(lock(A, AA, "patch", json={"wiki_folders": [MINE]}).ok, "setup: alice excludes her own folder")
check(lock(A, AA, "patch", json={"wiki_folders": [MINE, DOCS]}).status_code == 400, "N5 setup: she may not add Docs herself (400)")


def set_wf(ids):  # the lock as another editor left it (stored directly)
    cur = json.loads(dbx("SELECT data_lock FROM agents WHERE user_id=?", (AA,))[0][0] or "{}")
    dbx("UPDATE agents SET data_lock=? WHERE user_id=?", (json.dumps({**cur, "wiki_folders": ids}), AA))


set_wf([MINE, DOCS])
r = lock(A, AA)
wf = {x["id"]: x for x in r.json()["data_lock"]["wiki_folders"]}
check(wf.get(DOCS, {}).get("path") == "Docs" and wf.get(MINE, {}).get("path") == "Knowledge/Mine",
      f"M2: the gear names Docs from the share down, her own folder from Knowledge {wf}")
check("ZQXGeheim" not in r.text and "Intern" not in r.text, "M2: no folder above the share in the gear")
r = A.get(B + f"/api/agents/{AA}/sees")
ex = {x["id"]: x for x in r.json().get("except", [])} if r.ok else {}
check(r.ok and ex.get(DOCS, {}).get("path") == "Docs" and "ZQXGeheim" not in r.text and "Intern" not in r.text,
      f"M2: 'Sees now' names the exclusion without the folders above {r.status_code} {ex}")
dbx("INSERT INTO fs_shares(node_id,agent_id,role,created_by,created_at) VALUES(?,?,?,?,?)", (DOCS, AA, "view", ME["id"], "2026-11-12T00:00:00Z"))
r = A.get(B + f"/api/agents/{AA}/sees")
it = [x for x in r.json().get("items", []) if x.get("node_id") == DOCS] if r.ok else []
check(r.ok and "ZQXGeheim" not in r.text and "Intern" not in r.text, f"M2: 'Sees now' names no folder above a shared one {r.status_code}")
if it:
    check(it[0].get("path") == "Docs", f"M2: the shared folder's path starts at it {it[0]}")
else:
    print("NOTE: M2: the share of Docs with the agent is not listed (the agent does not reach it) - path checked through the text only")
dbx("DELETE FROM fs_shares WHERE node_id=? AND agent_id=?", (DOCS, AA))
check(lock(A, AA, "patch", json={"wiki_folders": [MINE]}).status_code == 400, "N5: she cannot take off an exclusion she may not set")
check(DOCS in [x["id"] for x in lock(A, AA).json()["data_lock"]["wiki_folders"]], "N5: it stays")
set_wf([MINE, DOCS, 10 ** 9])
check(lock(A, AA, "patch", json={"wiki_folders": [MINE, DOCS]}).ok, "N5: a folder that is gone can be taken off")
check(lock(A, AA, "patch", json={"wiki_folders": []}).status_code == 400, "N5: Docs still not")
set_wf([])

# included again
check(lock(F, DA, "patch", json={"wiki_folders": []}).ok and P_SEC in listed(da), "included again: visible again")

# ending the share: nothing at once
check(F.delete(B + f"/api/files/shares/{SID}").ok, "the area's share ended")
check(listed(da) == {} and da.get(V + f"/wiki/pages/{P_ONE}").status_code == 404 and found(da, "alpha") == [], "ended: nothing at once")

# an encrypted area: no share
dbx("INSERT INTO wiki_spaces(owner_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (FID,))
check(F.post(B + f"/api/files/nodes/{ROOT}/shares", json={"agent_id": DA, "role": "view"}).status_code == 409, "encrypted: 409")
check(area(F).get("locked") is True, "area-share: locked")
dbx("DELETE FROM wiki_spaces WHERE owner_id=?", (FID,))

# ================================================================ an organisation's area with its agent
Q1 = page(A, "Team/Handbook", space=f"org:{ORG}", text="team text")
OROOT, OFOLD = index(A, f"org:{ORG}")
t = A.get(B + f"/api/files/nodes/{OROOT}/share-targets").json()
check([x["id"] for x in t["agents"]] == [TA] and t["people"] == [], f"the organisation's root offers its agent only: {t}")
check(A.post(B + f"/api/files/nodes/{OROOT}/shares", json={"agent_id": TA, "role": "view"}).status_code == 201, "org area shared")
L = listed(ta)
check(Q1 in L and P_ONE not in L and L[Q1] == "Knowledge/Team/Handbook", f"the org agent: its area, nothing private {L}")
check(ta.patch(V + f"/wiki/pages/{Q1}", json={"body": "x", "expect_updated_at": "x"}).status_code == 403, "view: no write")
check(A.post(B + f"/api/files/nodes/{OROOT}/shares", json={"user_id": FID, "role": "view"}).status_code == 409, "org root: no person")
check(O.get(B + "/api/wiki/area-share", params={"space": f"org:{ORG}"}).status_code == 404, "tenant-matrix: wiki -- another person: 404")
oa_ = area(A, f"org:{ORG}")
check(oa_["may"] and [x["agent_id"] for x in oa_["shares"]] == [TA] and area(O)["shares"] == [], f"area-share per space: {oa_}")

sys.exit(kt.done("p21045_b_wikiarea_test"))
