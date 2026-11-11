#!/usr/bin/env python3
"""2.455.0 part C (#3469): what was left of the exports. Invented names only (example.com).
 - account export + import (a person without organisation, P4): sprints (tasks keep their sprint, the close-out names the new
   tasks), further placements, rules of the own lists, customer reports. Every id runs through the mapping: a rule's section, tag,
   field, person, target list; what did not come along pauses the rule, an action this version does not know leaves it out, never
   an old id. A placement in or a move target into another person's list and every status link stay out of the file
 - a second import of a newer export skips what is there, takes the new rows and its undo takes only those
 - organisation export + import: the feeds (none twice, an address with an access key stays out, no fetch state) and the read-later
   project; the rules and sprint close-outs of the organisation path are mapped the same way
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2455C_NOSTART=1 = the server already runs like that).
usage: p2455_c_export_test.py <datadir>"""
# freelancer-matrix: own
# tenant-matrix: own
import base64
import io
import json
import os
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess, su_get, until  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
TS = "2026-10-01T10:00:00+00:00"
OLD = 987654  # an id no row of this server has


def ok(r, what, codes=(200, 201, 202, 204)):
    check(r.status_code in codes, f"{what}: {r.status_code} {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        return {}


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def upload(s, data, name="alpha.zip"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def state(s, iid):
    return s.get(B + f"/api/account/import/{iid}").json()


def wait(s, iid):
    until(lambda: state(s, iid).get("state") not in ("checking", "running", "upload"), 240)
    return state(s, iid)


def run(s, iid, target):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    j = wait(s, iid)
    check(j.get("state") == "done", f"import into {target} done {j.get('state')} {j.get('error')}")
    return j


def warns(j):
    return " | ".join(x.get("text", "") for x in (j.get("result") or {}).get("warnings", []))


def acct_export(s):
    ok(s.post(B + "/api/account/export"), "account export started")
    until(lambda: s.get(B + "/api/account/export").json().get("state") != "running", 120)
    return su_get(s, B + "/api/account/export/file").content  # 2.360.0 (#2496): the step-up


def org_export(s, oid):
    ok(s.post(B + f"/api/orgs/{oid}/export"), "organisation export started")
    until(lambda: s.get(B + f"/api/orgs/{oid}/export").json().get("state") != "running", 240)
    ox = su_get(s, B + f"/api/orgs/{oid}/export/file").content
    rk = s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
    check(ox[:13] == b"KALMIDO-ORGX\n" and rk, "organisation export + recovery key")
    return ox, rk


def org_import(s, ox, rk, target):
    iid = upload(s, ox, "alpha.kalmido-export")
    check(wait(s, iid).get("state") == "key", "asks for the recovery key")
    ok(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}), "the recovery key")
    check(wait(s, iid).get("state") == "preview", "the archive opens")
    return run(s, iid, target)


def rule(lid, name, trig, tv, act, av, target=None, **kw):
    return dbx("""INSERT INTO list_rules(list_id,org_id,name,trig,trig_val,act,act_val,target_list_id,created_by,created_at,updated_at,deleted_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
               (lid, kw.get("org"), name, trig, str(tv), act, json.dumps(av), target, kw.get("by"), TS, TS, kw.get("gone")))[0][0]


def rules(lid):
    return {r[0]: {"tv": r[1], "av": json.loads(r[2]), "target": r[3], "active": r[4], "why": r[5], "by": r[6]} for r in dbx(
        "SELECT name, trig_val, act_val, target_list_id, active, paused_reason, created_by FROM list_rules WHERE list_id=? AND deleted_at IS NULL", (lid,))}


def parts(lid):
    """A list with what its rules can point at."""
    sec = dbx("INSERT INTO sections(list_id,name) VALUES(?,'Doing') RETURNING id", (lid,))[0][0]
    # 2.947.0 (#5275): a project tag is a row of the core (obj_tags scope list)
    tag = dbx("INSERT INTO obj_tags(scope_kind,scope_id,name,created_at) VALUES('list',CAST(? AS TEXT),'Hot',?) RETURNING id", (lid, TS))[0][0]
    fld = dbx("INSERT INTO list_fields(list_id,name,type,created_at) VALUES(?,'Lead','person',?) RETURNING id", (lid, TS))[0][0]
    return sec, tag, fld


def named(table, lid, name):
    if table == "list_tags":  # 2.947.0 (#5275): the core's tags
        return one("SELECT id FROM obj_tags WHERE scope_kind='list' AND scope_id=CAST(? AS TEXT) AND name=?", (lid, name))
    return one(f"SELECT id FROM {table} WHERE list_id=? AND name=?", (lid, name))


# ---------------------------------------------------------------- server, people
if not os.environ.get("P2455C_NOSTART"):
    env = dict(os.environ, EXTRA=f"-e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Umzug", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})

# ---------------------------------------------------------------- account: a person without organisation (P4)
FID, Fr = freelancer(B, A, features=FEATURES)
GID, Gr = freelancer(B, A, name="greta", features=FEATURES)
L1 = ok(Fr.post(B + "/api/lists", json={"name": "Frei Eins"}), "list 1")["id"]
L2 = ok(Fr.post(B + "/api/lists", json={"name": "Frei Zwei"}), "list 2")["id"]
ALIEN = ok(A.post(B + "/api/lists", json={"name": "Fremd"}), "a list of another person")["id"]
S1, T1, F1 = parts(L1)
S2, _t, _f = parts(L2)
K1 = ok(Fr.post(B + "/api/tasks", json={"title": "Eins", "list_id": L1}), "task 1")["id"]
K2 = ok(Fr.post(B + "/api/tasks", json={"title": "Zwei", "list_id": L1}), "task 2")["id"]
ACT = dbx("INSERT INTO sprints(list_id,num,start,end_day,state,created_at,created_by) VALUES(?,2,'2026-10-12','2026-10-25','active',?,?) RETURNING id", (L1, TS, FID))[0][0]
REV = json.dumps({"done": [K2], "moved": [K1, OLD], "added": [], "count_done": 1, "count_total": 2, "next_id": ACT})
dbx("INSERT INTO sprints(list_id,num,start,end_day,state,review,closed_at,created_at,created_by) VALUES(?,1,'2026-09-28','2026-10-11','closed',?,?,?,?)", (L1, REV, TS, TS, FID))
dbx("INSERT INTO sprints(list_id,num,start,end_day,state,created_at,created_by) VALUES(?,3,'kaputt','2026-11-08','planned',?,?)", (L1, TS, FID))
dbx("UPDATE tasks SET sprint_id=?, sprint_at=? WHERE id=?", (ACT, TS, K1))
dbx("UPDATE tasks SET sprint_id=?, sprint_at=? WHERE id=?", (OLD, TS, K2))  # a sprint that does not exist: the backlog
L3 = ok(Fr.post(B + "/api/lists", json={"name": "Frei Gesund"}), "list 3")["id"]
dbx("UPDATE lists SET life='health' WHERE id=?", (L3,))  # review: a placement the app refuses (ml_add) stays out of the import
for lid, sid in ((L2, S2), (L3, None), (ALIEN, None)):  # the last one must stay out of the file
    dbx("INSERT INTO task_links(task_id,list_id,section_id,sort,added_by,created_at) VALUES(?,?,?,7,?,?)", (K1, lid, sid, FID, TS))
rule(L1, "move", "section", S1, "move", {"list_id": L2, "section_id": S2}, L2, by=FID)
rule(L1, "assign", "assigned", FID, "assign", {"user_id": FID}, by=FID)
rule(L1, "tag", "ltag", T1, "tag", {"tag_id": T1}, by=FID)
rule(L1, "field", "field", f"{F1}=x", "field", {"field_id": F1, "value": FID}, by=FID)
rule(L1, "text", "done", "", "comment", {"text": f"see <@{FID}> and <@{OLD}>"}, by=FID)
rule(L1, "gone person", "done", "", "assign", {"user_id": OLD}, by=FID)
rule(L1, "gone column", "section", OLD, "due", {"days": 2}, by=FID)
rule(L1, "foreign target", "done", "", "move", {"list_id": ALIEN, "section_id": None}, ALIEN, by=FID)
rule(L1, "unknown", "done", "", "hack", {"url": "http://example.com/"}, by=FID)
rule(L1, "binned", "done", "", "due", {"days": 1}, by=FID, gone=TS)
dbx("""INSERT INTO portal_tickets(task_id,list_id,owner_id,name,token,token_hash,created_at) VALUES(?,?,?,'Kundin Beispiel','old-status-link','old-status-hash',?)""",
    (K2, L1, FID, TS))
AX = acct_export(Fr)
zf = zipfile.ZipFile(io.BytesIO(AX))
blob = b"".join(zf.read(n) for n in zf.namelist() if n.endswith(".json"))
table = lambda t: json.loads(zf.read(f"data/{t}.json"))  # noqa: E731
check(len(table("sprints")) == 3 and len(table("list_rules")) == 9, "sprints and rules are in the file, the trash is not")
check(sorted((x["task_id"], x["list_id"]) for x in table("task_links")) == sorted([(K1, L2), (K1, L3)]), "a placement only between my own lists")
check(b"old-status-link" not in blob and b"old-status-hash" not in blob, "a customer report's status link stays out of the file")
fr = next(x for x in table("list_rules") if x["name"] == "foreign target")
check(fr["target_list_id"] is None and json.loads(fr["act_val"]) == {}, "the id of another person's list stays out of the file")
check(any("agents" in x for x in json.loads(zf.read("manifest.json"))["not_included"]), "the manifest names the agents as not included")

iid = upload(Gr, AX)
j = wait(Gr, iid)
check(j.get("state") == "preview", f"the file opens {j.get('state')} {j.get('error')}")
check(not [x for x in j.get("not_taken") or [] if x.get("what") in ("sprints", "task_links", "list_rules", "portal_tickets")], "the preview names none of them as left behind")
j = run(Gr, iid, "private")
W = warns(j)
N1, N2 = (one("SELECT id FROM lists WHERE owner_id=? AND name=?", (GID, n)) for n in ("Frei Eins", "Frei Zwei"))
NK1, NK2 = (one("SELECT id FROM tasks WHERE list_id=? AND title=?", (N1, n)) for n in ("Eins", "Zwei"))
NS1, NS2, NT1, NF1 = named("sections", N1, "Doing"), named("sections", N2, "Doing"), named("list_tags", N1, "Hot"), named("list_fields", N1, "Lead")
nact = one("SELECT id FROM sprints WHERE list_id=? AND num=2", (N1,))
check(nact and nact != ACT, "the sprint came along with a new id")
check(one("SELECT sprint_id FROM tasks WHERE id=?", (NK1,)) == nact and one("SELECT sprint_at FROM tasks WHERE id=?", (NK1,)) == TS, "the task stays in its sprint")
check(one("SELECT sprint_id FROM tasks WHERE id=?", (NK2,)) is None and one("SELECT sprint_at FROM tasks WHERE id=?", (NK2,)) is None, "a sprint that did not come along = the backlog")
check(one("SELECT COUNT(*) FROM sprints WHERE list_id=? AND num=3", (N1,)) == 0, "a sprint with a broken day stays out")
rv = json.loads(one("SELECT review FROM sprints WHERE list_id=? AND num=1", (N1,)))
check(rv["done"] == [NK2] and rv["moved"] == [NK1] and rv["next_id"] == nact, f"the close-out names the new tasks {rv}")
check([tuple(x) for x in dbx("SELECT list_id, section_id, sort, added_by FROM task_links WHERE task_id=?", (NK1,))] == [(N2, NS2, 7, GID)], "the further placement came along with its section")
R = rules(N1)
check(len(R) == 8 and "unknown" not in R and "binned" not in R, f"the rules came along, not the unknown action, not the trash {sorted(R)}")
check(R["move"]["tv"] == str(NS1) and R["move"]["av"] == {"list_id": N2, "section_id": NS2} and R["move"]["target"] == N2 and R["move"]["active"], f"a move rule mapped {R['move']}")
check(R["assign"]["tv"] == str(GID) and R["assign"]["av"] == {"user_id": GID} and R["assign"]["by"] == GID, f"person of an assign rule mapped {R['assign']}")
check(R["tag"]["tv"] == str(NT1) and R["tag"]["av"] == {"tag_id": NT1} and R["tag"]["active"], f"tag rule mapped {R['tag']}")
check(R["field"]["tv"] == f"{NF1}=x" and R["field"]["av"] == {"field_id": NF1, "value": GID}, f"field rule mapped {R['field']}")
check(R["text"]["av"]["text"] == f"see <@{GID}> and @?", f"mention by id mapped, an unknown one gone {R['text']}")
for n, why in (("gone person", "assignee"), ("gone column", "section"), ("foreign target", "target")):
    check(R[n]["why"] == why and not R[n]["active"], f"{n}: paused ({R[n]})")
check(R["gone person"]["av"] == {"user_id": None} and R["foreign target"]["target"] is None and R["gone column"]["tv"] == "", "a paused rule keeps no old id")
check("A rule was paused" in W and "A rule was left out" in W, f"the report names paused and left-out rules {W[:300]}")
nt = dbx("SELECT task_id, list_id, owner_id, name, token_hash FROM portal_tickets WHERE list_id=?", (N1,))
check(len(nt) == 1 and tuple(nt[0])[:4] == (NK2, N1, GID, "Kundin Beispiel") and nt[0][4] != "old-status-hash", f"the customer report with a new status link {nt}")

# ---------------------------------------------------------------- a newer export: what is there is skipped, undo takes only the new rows
dbx("UPDATE sprints SET state='closed' WHERE id=?", (ACT,))
NEW = dbx("INSERT INTO sprints(list_id,num,start,end_day,state,created_at,created_by) VALUES(?,4,'2026-11-09','2026-11-22','active',?,?) RETURNING id", (L1, TS, FID))[0][0]
rule(L1, "later", "done", "", "due", {"days": 3}, by=FID)
dbx("UPDATE tasks SET sprint_id=? WHERE id=?", (None, K2))
AX2 = acct_export(Fr)
iid = upload(Gr, AX2, "alpha2.zip")
check(wait(Gr, iid).get("state") == "preview", "the newer file opens")
dbx("UPDATE sprints SET state='closed' WHERE list_id=? AND num=2", (N1,))  # changed on the target since
dbx("INSERT INTO sprints(list_id,num,start,end_day,state,created_at,created_by) VALUES(?,9,'2026-11-09','2026-11-22','active',?,?)", (N1, TS, GID))  # review: the list runs a sprint already
j = run(Gr, iid, "private")
check(one("SELECT COUNT(*) FROM sprints WHERE list_id=?", (N1,)) == 4 and len(rules(N1)) == 9, "nothing twice, only the new sprint and rule")
check(one("SELECT state FROM sprints WHERE list_id=? AND num=4", (N1,)) == "planned", "at most one running sprint per list, also with one already there")
check(one("SELECT state FROM sprints WHERE list_id=? AND num=2", (N1,)) == "closed", "a sprint that is there keeps what happened to it")
check(one("SELECT COUNT(*) FROM portal_tickets WHERE list_id=?", (N1,)) == 1, "the customer report not twice")
imp = (j.get("result") or {}).get("import_id")
ok(Gr.post(B + f"/api/imports/{imp}/undo"), "the undo of the second import")
check(one("SELECT COUNT(*) FROM sprints WHERE list_id=? AND num=4", (N1,)) == 0 and "later" not in rules(N1), "the undo takes the rows it added")
check(one("SELECT COUNT(*) FROM sprints WHERE list_id=?", (N1,)) == 3 and len(rules(N1)) == 8, "the first import's rows stay")

# ---------------------------------------------------------------- organisation: feeds, read-later project, mapped rules and sprints
orgs = {n: ok(A.post(B + "/api/admin/orgs", json={"name": n, "admin_id": ALICE}), n)["id"] for n in ("Alpha Quelle", "Gamma Leer")}
ORG, ORG2 = orgs["Alpha Quelle"], orgs["Gamma Leer"]
OL = ok(A.post(B + "/api/lists", json={"name": "Org Liste", "org_id": ORG}), "org list")["id"]
ORD = ok(A.post(B + "/api/lists", json={"name": "Org Lesen", "org_id": ORG}), "the read-later project")["id"]
dbx("UPDATE lists SET org_id=? WHERE id IN (?,?)", (ORG, OL, ORD))
OS, OT, OF = parts(OL)
OK1 = ok(A.post(B + "/api/tasks", json={"title": "Org Eins", "list_id": OL}), "org task")["id"]
dbx("INSERT INTO reading_orgs(org_id,list_id,created_at) VALUES(?,?,?)", (ORG, ORD, TS))
for url, etag in (("https://feeds.example.com/news.xml", "etag-1"), ("https://feeds.example.com/private.xml?access_token=geheim", ""), ("https://feeds.example.com/private-0a1b2c/basic.xml", ""), ("https://feeds.example.com/twice.xml", "")):
    dbx("INSERT INTO rss_feeds(user_id,org_id,url,title,etag,last_fetch,fails,created_at) VALUES(?,?,?,'Quelle',?,?,3,?)", (ALICE, ORG, url, etag, TS, TS))
dbx("INSERT INTO rss_feeds(user_id,org_id,url,created_at) VALUES(?,?,'https://feeds.example.com/twice.xml',?)", (ALICE, ORG2, TS))
rule(OL, "o field", "field", OF, "tag", {"tag_id": OT}, org=ORG, by=ALICE)
rule(OL, "o person", "assigned", OLD, "field", {"field_id": OF, "value": OLD}, org=ORG, by=ALICE)
dbx("INSERT INTO sprints(list_id,num,start,end_day,state,review,created_at) VALUES(?,1,'2026-09-28','2026-10-11','closed',?,?)", (OL, json.dumps({"done": [OK1, OLD]}), TS))
OX, RK = org_export(A, ORG)
j = org_import(A, OX, RK, ORG2)
W = warns(j)
feeds = {r[0]: r[1:] for r in dbx("SELECT url, user_id, etag, last_fetch, fails FROM rss_feeds WHERE org_id=? AND deleted_at IS NULL", (ORG2,))}
check(set(feeds) == {"https://feeds.example.com/news.xml", "https://feeds.example.com/twice.xml"}, f"the feeds came along, none twice, none with a key {sorted(feeds)}")
# #3469 #3107: the watchdog of this server may fetch the new feed at once: never the old server's values, not "none at all"
nf = feeds["https://feeds.example.com/news.xml"]
check(nf[0] == ALICE and nf[1] != "etag-1" and nf[2] != TS and nf[3] < 3, f"no fetch state of the old server {feeds}")
check("A feed without its address" in W, f"the report names the feed without address {W[:300]}")
NOL, NRD = (one("SELECT id FROM lists WHERE org_id=? AND name=?", (ORG2, n)) for n in ("Org Liste", "Org Lesen"))
check(one("SELECT list_id FROM reading_orgs WHERE org_id=?", (ORG2,)) == NRD, "the read-later project is registered in the target")
R = rules(NOL)
NOF, NOT = named("list_fields", NOL, "Lead"), named("list_tags", NOL, "Hot")
check(R["o field"]["tv"] == str(NOF) and R["o field"]["av"] == {"tag_id": NOT}, f"organisation path: field trigger and tag action mapped {R['o field']}")
check(R["o person"]["tv"] == "" and R["o person"]["av"]["value"] is None and not R["o person"]["active"], f"organisation path: an old person stays nowhere {R['o person']}")
rv = json.loads(one("SELECT review FROM sprints WHERE list_id=?", (NOL,)))
check(rv["done"] == [one("SELECT id FROM tasks WHERE list_id=? AND title='Org Eins'", (NOL,))], f"organisation path: the close-out names the new task {rv}")
n = one("SELECT COUNT(*) FROM rss_feeds WHERE org_id=?", (ORG2,))
ok(A.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo"), "the undo of the organisation import")
check(one("SELECT COUNT(*) FROM rss_feeds WHERE org_id=?", (ORG2,)) == n - 1 and not one("SELECT list_id FROM reading_orgs WHERE org_id=?", (ORG2,)),
      "the undo takes the new feed and the registration, the feed that was there stays")
# into the private workspace: the feeds become the person's own, the organisation's project mark stays behind
j = org_import(A, OX, RK, "private")
check(one("SELECT COUNT(*) FROM rss_feeds WHERE user_id=? AND org_id IS NULL AND url LIKE '%feeds.example.com%'", (ALICE,)) == 2, "into the private workspace: the importing person's own feeds")

print(f"p2455_c_export: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
