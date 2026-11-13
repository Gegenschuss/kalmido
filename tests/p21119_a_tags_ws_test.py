#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1119.0 (#5277, stage Q5c of the cross-cutting core): the tags of the file store (files, folders, documents) are rows of
the core (obj_tags scope ws, obj_tag_links kind fs_entry; core/objtags.py, docs/dtags.py). Own container. Invented names only.
 - doc_tags / doc_node_tags are gone; made again by hand with rows (what a version before 2.1119 leaves after a rollback) the
   next start moves them: names equal under lower() in one workspace become ONE tag, the mark auto becomes the link's how
   (src auto), a tag whose id is taken in obj_tags gets a new one and the places that keep its id follow (the tag model, a
   saved view's query and rules, a suggestion, "apply what was learned"); a tag whose id is free keeps it
 - writing through the app: Neu / neu on one node are one tag, a later NEU on another node finds it (unique index); renaming
   a tag to a name the workspace has is refused (409, no second row); delete + undo; the filter finds the nodes
 - question 11 (decided 08.11.2026): a person a node is shared with (edit, a guest of the organisation) sees the tags on
   it, not the workspace's other names; a member of the workspace sees them
 - a node deleted for good takes its links along (trigger kalmido_otg_gone_fs)
 - a person without an organisation tags her own files and filters by them
freelancer-matrix: files
usage: p21119_a_tags_ws_test.py <datadir>"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, dbx  # noqa: E402
from freelancer_fixture import FEATURES, org_join  # noqa: E402

TS = "2026-11-01T10:00:00+00:00"


def box(code):
    """Python inside the app container (as the system); "import app" starts the app (init_db: the move, the fragments)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app, json\nfrom kalmido.core.db import connect\n"
                          "from kalmido.core.pg import system_ctx\nfrom kalmido.docs import store as S\nc = connect()\nwith system_ctx(c):\n"
                          + "".join("    " + ln + "\n" for ln in code.splitlines()) + "c.commit()\nc.close()"],
                         capture_output=True, text=True)
    check(out.returncode == 0, f"the run in the container works {out.stderr[-800:]}")
    return out.stdout.strip()


def table_there(t):
    return bool(dbx("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?", (t,)))


def folder(s, name, space="private"):
    r = s.post(B + "/api/files/folders", json={"name": name, "space": space})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(s, parent, name):
    r = s.post(B + "/api/files/upload", data={"parent_id": str(parent)}, files={"file": (name, b"invented plain text", "text/plain")})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def wstags(ws):
    """[(name, id)] of workspace ws's tags in the core, by name."""
    return [tuple(r) for r in dbx("SELECT name, id FROM obj_tags WHERE scope_kind='ws' AND scope_id=? ORDER BY lower(name)", (ws,))]


def links(nid):
    """[(tag id, src, how)] on node nid."""
    return [tuple(r) for r in dbx("SELECT tag_id, src, how FROM obj_tag_links WHERE kind='fs_entry' AND obj_id=? ORDER BY tag_id", (nid,))]


def node_tags(s, nid):
    r = s.get(B + f"/api/files/nodes/{nid}/tags")
    assert r.ok, r.text
    return r.json()


kt.fresh(prefix="P21119A")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": kt.PASSWORD})
assert r.ok, r.text
A = kt.sess("alice")
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
r = A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = dbx("SELECT id FROM orgs WHERE name='Alpha'")[0][0]
uid = {}
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u == "bob" else [], "username": u, "display_name": u.title(), "password": kt.PASSWORD,
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
org_join(B, "bob", ORG)
Bo, Ca = kt.sess("bob"), kt.sess("carl")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BOB, CARL = uid["bob"], uid["carl"]
OWS, AWS = f"o{ORG}", f"u{ALICE}"
OF = folder(A, "Belege", f"org:{ORG}")
D1, D2 = upload(A, OF, "rechnung.txt"), upload(A, OF, "vertrag.txt")
for n in (D1, D2):  # two documents of the organisation's workspace (as p2525_b_ablage_test makes them)
    dbx("INSERT INTO doc_meta(node_id, org_id, ws, state, doc_date, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        (n, ORG, OWS, "done", "2026-01-02", TS, TS))

# ================================================================== the old tables are gone, the move of a rolled-back database
check(not table_there("doc_tags") and not table_there("doc_node_tags"), "doc_tags / doc_node_tags are gone (fragment 5277_a)")
# the id X is taken in obj_tags (a project's tag): the old tag X gets a new id; Y is free and stays
L = A.post(B + "/api/lists", json={"name": "Projekt", "kind": "project"}).json()["id"]
X = dbx("INSERT INTO obj_tags(scope_kind, scope_id, name, created_at) VALUES('list',?,'Projekt-Tag',?) RETURNING id", (str(L), TS))[0][0]
Y = dbx("SELECT COALESCE(MAX(id), 0) + 500 FROM obj_tags")[0][0]
Z = Y + 1
# the places that keep a tag's id, written first (every box() is a start of the app: it would move the old tables at once)
box(f"""S.model_put(c, {OWS!r}, "tags", {{"{X}": {{"v": 1, "docs": 1, "classes": {{}}}}, "{Y}": {{"v": 1, "docs": 2, "classes": {{}}}}}})
c.execute("UPDATE doc_meta SET suggest=?, learn_prev=? WHERE node_id=?", (S._jseal(c, {OWS!r}, "doc_meta.suggest", {{"tags": {{"value": [{X}], "by": "learn"}}}}),
          json.dumps({{"run": "r1", "after": {{"tags": [{X}]}}}}), {D2}))""")
VIEW = dbx("""INSERT INTO doc_views(owner_id, title, query, rules, ws, created_at, updated_at) VALUES(?,?,?,?,?,?,?) RETURNING id""",
           (ALICE, "Steuer", f"tag={X}%2C{Y}&not_tag={Z}&q=rechnung", json.dumps({"op": "and", "conds": [{"f": "tag", "op": "in", "v": [f"{X},{Y}"]}]}),
            f"org:{ORG}", TS, TS))[0][0]
dbx("""CREATE TABLE doc_tags (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, org_id BIGINT REFERENCES orgs(id) ON DELETE CASCADE,
       ws TEXT NOT NULL, name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)""")
dbx("""CREATE TABLE doc_node_tags (node_id BIGINT NOT NULL REFERENCES fs_nodes(id) ON DELETE CASCADE, tag_id BIGINT NOT NULL
       REFERENCES doc_tags(id) ON DELETE CASCADE, auto TEXT NOT NULL DEFAULT '', PRIMARY KEY (node_id, tag_id))""")
for tid, name in ((X, "Steuer"), (Y, "Vertrag"), (Z, "steuer")):  # Z: the same name as X in another case (the old race)
    dbx("INSERT INTO doc_tags(id, org_id, ws, name, created_at) VALUES(?,?,?,?,?)", (tid, ORG, OWS, name, TS))
for nid, tid, auto in ((D1, X, "rule"), (D1, Z, ""), (D2, Y, "learn"), (D2, Z, "")):
    dbx("INSERT INTO doc_node_tags(node_id, tag_id, auto) VALUES(?,?,?)", (nid, tid, auto))
box("pass")  # the next start of the app
check(not table_there("doc_tags") and not table_there("doc_node_tags"), "the start dropped doc_tags / doc_node_tags made again")
got = wstags(OWS)
N = dict(got).get("Steuer")
check([x[0] for x in got] == ["Steuer", "Vertrag"] and N not in (X, None) and dict(got)["Vertrag"] == Y,
      f"the move: Steuer / steuer are ONE tag (the first by id) with a new id (X was taken), Vertrag keeps its id {got} X={X} Y={Y}")
check(dbx("SELECT name FROM obj_tags WHERE id=?", (X,)) == [("Projekt-Tag",)], "the project's tag with id X is untouched")
check(links(D1) == [(N, "auto", "rule")] and links(D2) == sorted([(N, "person", ""), (Y, "auto", "learn")]),
      f"the links: the mark auto is the link's how, src auto for the recognition's {links(D1)} {links(D2)}")
check(dbx("SELECT org_id FROM obj_tags WHERE id=?", (N,)) == [(ORG,)], "the organisation's workspace tag carries org_id (row-level security)")
out = box(f"""m = S.model_get(c, {OWS!r}, "tags")
d = S._jopen(c, {OWS!r}, "doc_meta.suggest", c.execute("SELECT suggest FROM doc_meta WHERE node_id=?", ({D2},)).fetchone()[0], {{}})
lp = json.loads(c.execute("SELECT learn_prev FROM doc_meta WHERE node_id=?", ({D2},)).fetchone()[0])
print("GOT" + json.dumps([sorted(m), d["tags"]["value"], lp["after"]["tags"]]))""")
check(f'GOT{json.dumps([sorted([str(N), str(Y)]), [N], [N]])}' in out,
      f"the tag model, the suggestion and 'apply what was learned' name the new id {out[-300:]} N={N}")
v = dbx("SELECT query, rules FROM doc_views WHERE id=?", (VIEW,))[0]
check(v[0] == f"tag={N}%2C{Y}&not_tag={N}&q=rechnung" and json.loads(v[1])["conds"][0]["v"] == [f"{N},{Y}"],
      f"the saved view's query and rules name the new id {v}")
check([t["name"] for t in node_tags(A, D1)["tags"]] == ["Steuer"], "the app reads the moved tags")

# ================================================================== writing through the app
P = folder(A, "Privat")
F1, F2, F3 = upload(A, P, "eins.txt"), upload(A, P, "zwei.txt"), upload(A, P, "drei.txt")
r = A.put(B + f"/api/files/nodes/{F1}/tags", json={"tags": ["Neu", "neu", "Alt"]})
check(r.ok and [t["name"] for t in r.json()["tags"]] == ["Alt", "Neu"], f"Neu / neu on one node: one tag {r.status_code} {r.text[:200]}")
r = A.put(B + f"/api/files/nodes/{F2}/tags", json={"tags": ["NEU"]})
NEU = dict(wstags(AWS)).get("Neu")
check(r.ok and links(F2) == [(NEU, "person", "")] and [x[0] for x in wstags(AWS)] == ["Alt", "Neu"],
      f"a later NEU finds the tag Neu (no second row) {wstags(AWS)}")
r = A.patch(B + f"/api/docs/labels/tag/{NEU}", json={"name": "alt"})
check(r.status_code == 409 and [x[0] for x in wstags(AWS)] == ["Alt", "Neu"], f"renaming to a name of the workspace: refused {r.status_code}")
r = A.patch(B + f"/api/docs/labels/tag/{NEU}", json={"name": "Neu2"})
check(r.ok and dict(wstags(AWS)).get("Neu2") == NEU, f"renamed {r.status_code} {wstags(AWS)}")
r = A.get(B + "/api/files/tagged", params={"space": "private", "tag": str(NEU)})
check(r.ok and sorted(x["id"] for x in r.json()["items"]) == [F1, F2], f"the filter finds both nodes {r.text[:200]}")
j = A.delete(B + f"/api/docs/labels/tag/{NEU}").json()
check(sorted(j.get("ids") or []) == [F1, F2] and not links(F2) and "Neu2" not in dict(wstags(AWS)), f"deleted: the tag and its links go {j}")
r = A.post(B + "/api/docs/labels/tag", json={"ws": "private", "name": "Neu2", "ids": [F1, F2]})
NEU = dict(wstags(AWS)).get("Neu2")
check(r.status_code == 201 and links(F2) == [(NEU, "person", "")], f"the undo puts it back {r.status_code} {links(F2)}")

# ================================================================== question 11: a share to someone who is no member of the workspace
# (an organisation's node can be shared with its people only: a guest of the organisation is no member of its documents' workspace)
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "guest"}], "username": "gina", "display_name": "Gina",
                                   "password": kt.PASSWORD, "email": "gina@example.com"})
check(r.ok, "setup: gina as a guest of the organisation " + r.text[:200])
GINA, Gi = r.json()["id"], kt.sess("gina")
G1 = upload(A, OF, "plan.txt")  # a plain file of the organisation (a document's tags change through the documents area)
check(A.put(B + f"/api/files/nodes/{G1}/tags", json={"tags": ["Steuer"]}).ok, "alice tags it")
r = A.post(B + f"/api/files/nodes/{G1}/shares", json={"user_id": GINA, "role": "edit"})
check(r.ok, f"alice shares a file of the organisation with gina (edit) {r.status_code} {r.text[:200]}")
j = node_tags(Gi, G1)
check([t["name"] for t in j["tags"]] == ["Steuer"] and j["can"] and j["all"] == [],
      f"gina sees the tags on the node, not the names of the organisation's workspace {j}")
r = Gi.put(B + f"/api/files/nodes/{G1}/tags", json={"tags": ["Steuer", "Von Gina"]})
check(r.ok and "Von Gina" in dict(wstags(OWS)), f"gina may still tag it (a typed name finds / makes the tag) {r.status_code} {r.text[:200]}")
check(A.post(B + f"/api/files/nodes/{G1}/shares", json={"user_id": BOB, "role": "edit"}).ok, "... and with bob (edit)")
check(sorted(t["name"] for t in node_tags(Bo, G1)["all"]) == ["Steuer", "Vertrag", "Von Gina"],
      "bob, a member of the organisation, sees all its workspace's names")
check(sorted(t["name"] for t in node_tags(A, F3)["all"]) == ["Alt", "Neu2"], "alice sees all names of her own workspace")

# ================================================================== a node deleted for good takes its links along
check(links(F2), "F2 carries a tag")
dbx("DELETE FROM fs_nodes WHERE id=?", (F2,))
check(not links(F2), "the node gone for good: its links are gone (kalmido_otg_gone_fs)")

# ================================================================== a person without an organisation
CP = folder(Ca, "Eigenes")
CF = upload(Ca, CP, "beleg.txt")
r = Ca.put(B + f"/api/files/nodes/{CF}/tags", json={"tags": ["Privat"]})
check(r.ok and [t["name"] for t in node_tags(Ca, CF)["all"]] == ["Privat"], f"carl tags his own file and sees his workspace's names {r.status_code}")
tid = dict(wstags(f"u{CARL}")).get("Privat")
r = Ca.get(B + "/api/files/tagged", params={"space": "private", "tag": str(tid)})
check(r.ok and [x["id"] for x in r.json()["items"]] == [CF], f"... and filters by it {r.text[:200]}")
check(Ca.get(B + "/api/files/tags", params={"space": "private"}).json()["tags"] == [{"name": "Privat", "ids": [tid]}], "the used tags of his space")

sys.exit(kt.done("p21119_a_tags_ws"))
