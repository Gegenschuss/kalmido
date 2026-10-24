#!/usr/bin/env python3
"""2.96.0 part D (#1941, findings of #1918): an organisation export into the private space, and absences in the personal
area when the workspace switch is on "Private". Invented names only.
 - an organisation export (the existing export route + recovery key) offers "private" as a target; an admin imports it
   there: the lists / tasks / calendar are private (org_id NULL, owned by the importer), the attachment is readable, the
   members are not shared without a tick and nobody joins an organisation; a ticked member gets the list shared only;
   the warnings say so
 - targets: a foreign organisation 404, an organisation without admin rights 403
 - a person without any organisation (freelancer) imports the export of an organisation (of "another server") privately
 - absences: a member with the switch on "Private" enters into the own personal area, on "org:<id>" into that
   organisation, on "all" into the first organisation; GET names the personal area
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P296D_NOSTART=1 = the server already runs like that).
usage: p296_d_api_test.py <datadir>"""
# freelancer-matrix: own
# tenant-matrix: own
import base64
import hashlib
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm
from freelancer_fixture import FEATURES, freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]


def EH(email):
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)
        if len(FAILS) == 1:
            ct = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
            print(subprocess.run(["docker", "logs", "--tail", "60", ct], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True).stdout[-6000:], flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def upload(s, data, name="alpha.kalmido-export"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid, secs=180):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def opened(s, data, rk):
    """Upload + recovery key -> (import id, preview)."""
    iid = upload(s, data)
    j = wait(s, iid)
    check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {j.get('error')}")
    check(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
    j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    return iid, j.get("preview") or {}


def run(s, iid, target, people=None):
    # 2.269.0 (#3046): "again" = the person saw the preview's warning (a second import of one export is 409 without it)
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": people or {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    return wait(s, iid)


if not os.environ.get("P296D_NOSTART"):
    env = dict(os.environ, EXTRA=f"-e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Umzug", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
ids = {}
for u, n in (("bob", "Bob Mitglied"), ("carol", "Carol Fremd"), ("dora", "Dora Mitglied")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca, Do = sess("bob"), sess("carol"), sess("dora")
for s in (A, Bo, Ca, Do):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha Umzug", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
for u in ("bob", "dora"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta Fremd", "admin_id": ids["carol"]})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]

# ---------------------------------------------------------------- the organisation's data + its export
LO = A.post(B + "/api/lists", json={"name": "Alpha Orgliste", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{LO}/members", json={"user_id": ids["bob"], "role": "edit"}).ok, "the org list is shared with bob")
check(A.put(B + f"/api/lists/{LO}/members", json={"user_id": ids["dora"], "role": "edit"}).ok, "the org list is shared with dora")
TO = A.post(B + "/api/tasks", json={"title": "Orgaufgabe Privat", "list_id": LO}).json()["id"]
OATT = b"Org-Datei " + os.urandom(8).hex().encode()
check(A.post(B + f"/api/tasks/{TO}/attachments", files=[("file", ("org.txt", OATT, "text/plain"))]).ok, "org attachment")
r = A.post(B + "/api/evcals", json={"name": "Alpha Kalender", "org_id": ORG})
check(r.ok, "an org calendar " + r.text[:120])
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, "organisation export started " + r.text[:120])
for _ in range(480):
    if A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running":
        break
    time.sleep(0.25)
OX = A.get(B + f"/api/orgs/{ORG}/export/file").content
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
check(OX[:13] == b"KALMIDO-ORGX\n" and RK, "organisation export + recovery key")

# ---------------------------------------------------------------- the admin imports it into the private space
iid, pv = opened(A, OX, RK)
tg = [t["id"] for t in pv.get("targets", [])]
check(pv.get("kind") == "org" and "private" in tg and ORG in tg and ORG2 not in tg, f"targets: private + own organisation {tg}")
check(A.post(B + f"/api/account/import/{iid}/run", json={"target": ORG2}).status_code == 404, "a foreign organisation 404")
check(A.post(B + f"/api/account/import/{iid}/run", json={"target": "org:1"}).status_code == 400, "a broken target 400")
orgs_before = dbx("SELECT org_id, user_id FROM org_members ORDER BY org_id, user_id")
j = run(A, iid, "private", people={EH("bob@example.com"): {"share": True}})  # bob ticked, dora not
check(j.get("state") == "done", f"private import done {j.get('state')} {j.get('error')}")
pl = dbx("SELECT id, owner_id, org_id FROM lists WHERE name='Alpha Orgliste' AND id!=?", (LO,))
check(len(pl) == 1 and pl[0]["org_id"] is None and pl[0]["owner_id"] == ALICE, f"the list is private, alice owns it {[dict(x) for x in pl]}")
PL = pl[0]["id"] if pl else 0
pt = dbx("SELECT id FROM tasks WHERE list_id=? AND title='Orgaufgabe Privat'", (PL,))
check(len(pt) == 1, "the task came along into the private list")
pa = dbx("SELECT id FROM attachments WHERE task_id=? AND name='org.txt'", (pt[0]["id"] if pt else 0,))
check(pa and A.get(B + f"/api/attachments/{pa[0]['id']}").content == OATT, "the attachment is readable")
pc = dbx("SELECT org_id, owner_id FROM ev_cals WHERE name='Alpha Kalender' AND owner_id=? ORDER BY id DESC LIMIT 1", (ALICE,))
check(len(dbx("SELECT 1 FROM ev_cals WHERE name='Alpha Kalender'")) == 2 and pc and pc[0]["org_id"] is None, "the calendar is private")
mem = {r["user_id"] for r in dbx("SELECT user_id FROM list_members WHERE list_id=?", (PL,))}
check(ids["bob"] in mem and ids["dora"] not in mem, f"bob (ticked) gets the list shared, dora (not ticked) not {mem}")
check(dbx("SELECT org_id, user_id FROM org_members ORDER BY org_id, user_id") == orgs_before, "nobody joined an organisation")
w = " | ".join(x.get("text", "") for x in (j.get("result") or {}).get("warnings", []))
check("private space" in w and "nobody joins an organisation" in w, f"the warning names the private space {w}")
check(PL not in {x.get("id") for x in Do.get(B + "/api/state").json().get("lists", [])}, "dora does not see the private list")
r = A.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok and not dbx("SELECT 1 FROM lists WHERE id=?", (PL,)), f"undo removes the private import {r.text[:160]}")
A.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- a member (not its admin): private yes, the organisation no
iid, pv = opened(Bo, OX, RK)
check([t["id"] for t in pv.get("targets", [])] == ["private"], f"bob: only private {pv.get('targets')}")
check(Bo.post(B + f"/api/account/import/{iid}/run", json={"target": ORG}).status_code == 403, "bob: his organisation without admin rights 403")
check(Bo.post(B + f"/api/account/import/{iid}/run", json={"target": ORG2}).status_code == 404, "bob: a foreign organisation 404")
Bo.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- a freelancer (no organisation) imports it privately
FID, Fr = freelancer(B, A)
iid, pv = opened(Fr, OX, RK)
check([t["id"] for t in pv.get("targets", [])] == ["private"], f"freelancer: the private space is the target {pv.get('targets')}")
check(Fr.post(B + f"/api/account/import/{iid}/run", json={"target": ORG}).status_code == 404, "freelancer: an organisation 404")
j = run(Fr, iid, "private")
check(j.get("state") == "done", f"freelancer: import done {j.get('error')}")
fl = dbx("SELECT id, org_id FROM lists WHERE owner_id=? AND name='Alpha Orgliste'", (FID,))
check(len(fl) == 1 and fl[0]["org_id"] is None, "freelancer: the list is in the private space")
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id!=?", (fl[0]["id"] if fl else 0, FID)), "freelancer: shared with nobody")
check(not dbx("SELECT 1 FROM org_members WHERE user_id=?", (FID,)), "freelancer: still in no organisation")
check(Fr.get(B + "/api/state").json()["me"].get("workspaces") == [], "freelancer: no workspace appeared")
fa = dbx("SELECT a.id FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND a.name='org.txt'", (fl[0]["id"] if fl else 0,))
check(fa and Fr.get(B + f"/api/attachments/{fa[0]['id']}").content == OATT, "freelancer: the attachment is readable")
check(A.get(B + f"/api/attachments/{fa[0]['id'] if fa else 0}").status_code in (403, 404), "alice cannot read the freelancer's file")

# ---------------------------------------------------------------- absences follow the workspace switch
D1 = "2026-11-16"


def absence(s, ws, day):
    check(s.patch(B + "/api/settings", json={"workspace": ws}).ok, f"switch {ws}")
    r = s.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": day})
    check(r.status_code == 201, f"absence with {ws}: {r.status_code} {r.text[:160]}")
    return dbx("SELECT org_id FROM hub_absences WHERE id=?", (r.json().get("id") if r.ok else 0,))


row = absence(Do, "private", D1)
pers = dbx("SELECT id FROM orgs WHERE personal_of=?", (ids["dora"],))
PB = pers[0]["id"] if pers else None
check(PB and row and row[0]["org_id"] == PB and PB != ORG, f"switch Private: the personal area {row and row[0]['org_id']} (personal {PB})")
g = Do.get(B + "/api/team/absences", params={"start": "2026-11-01", "end": "2026-11-30"}).json()
check(g.get("org_id") == PB and g.get("personal") == PB and [o["id"] for o in g.get("orgs", [])] == [ORG], f"GET: the personal area {g.get('org_id')} {g.get('personal')}")
check(not any(i.get("user_id") == ids["bob"] for i in g.get("items", [])) and
      all(p["id"] == ids["dora"] for p in g.get("people", [])), "the personal area holds only dora")
row = absence(Do, f"org:{ORG}", "2026-11-17")
check(row and row[0]["org_id"] == ORG, "switch on the organisation: into it")
row = absence(Do, "all", "2026-11-18")
check(row and row[0]["org_id"] == ORG, "switch All: the first organisation (as before)")
ga = A.get(B + "/api/team/absences", params={"org": ORG, "start": "2026-11-01", "end": "2026-11-30"}).json()
days = sorted(i["start_date"] for i in ga.get("items", []) if i.get("user_id") == ids["dora"])
check(days == ["2026-11-17", "2026-11-18"], f"the organisation sees only its two days, not the private one {days}")
check(Do.get(B + "/api/team/absences", params={"org": ORG2}).status_code == 404, "a foreign organisation's absences 404")
check(Do.patch(B + "/api/settings", json={"workspace": "private"}).ok and
      Do.get(B + "/api/team/absences", params={"org": ORG}).json().get("org_id") == ORG, "?org= still wins over the switch")
Do.patch(B + "/api/settings", json={"workspace": "all"})

print(f"p296_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
