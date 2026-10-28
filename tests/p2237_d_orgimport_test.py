#!/usr/bin/env python3
"""2.237.0 D (#2870): the organisation import takes nobody else's account as author, and its undo checks rights and locks.
Invented names only.
 - an organisation with chat (alice + bob), a reaction of bob, time entries of alice + bob, a timesheet decided by bob,
   an absence of bob entered by bob and an office (a draft and a finalised invoice) is exported and imported into an
   EMPTY organisation with bob ticked: no author / decider / creator column names bob (chat, reaction, timesheet,
   absence creator); bob stays where the import shares (task people) or an admin enters it in the app too (his absence);
   his time entry goes to alice with his name in front of the note; the office log says "imported" for the documents
 - undo as an admin who is no admin of the target any more: 403, nothing removed
 - undo after a document of the import was finalised in the target: 409, nothing removed
 - undo by the admin of another target (the finalised invoice of the file was finalised there before): works, nothing left
 - a person without organisation (freelancer) imports it privately: unchanged (no rows of others)
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2237D_NOSTART=1 = the server already runs like that).
usage: p2237_d_orgimport_test.py <datadir>"""
# freelancer-matrix: admin
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
from kt import FAILS, OKS, check, sess, su_get

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
O, D = "/api/office", "/api/office/docs"


def EH(email):
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


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


def wait(s, iid, secs=240):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def opened(s, data, rk):
    iid = upload(s, data)
    j = wait(s, iid)
    check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {j.get('error')}")
    check(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
    j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    return iid


def run(s, iid, target, people=None):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": people or {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    j = wait(s, iid)
    check(j.get("state") == "done", f"import into {target} done {j.get('state')} {j.get('error')}")
    return j


def export(s, oid):
    r = s.post(B + f"/api/orgs/{oid}/export")
    check(r.status_code == 202, f"organisation export {oid} started {r.text[:120]}")
    for _ in range(960):
        if s.get(B + f"/api/orgs/{oid}/export").json().get("state") != "running":
            break
        time.sleep(0.25)
    ox = su_get(s, B + f"/api/orgs/{oid}/export/file").content  # 2.360.0 (#2496): the step-up
    rk = s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
    check(ox[:13] == b"KALMIDO-ORGX\n" and rk, f"organisation export {oid} + recovery key")
    return ox, rk


def counts(oid):
    """What an undo would remove in organisation oid (bundle 2.305: lists in the trash do not count, 2.272.0 C #3027: the undo
    puts the lists into the list trash, restorable, instead of deleting them)."""
    return {t: one(f"SELECT COUNT(*) FROM {t} WHERE org_id=?" + (" AND deleted_at IS NULL" if t == "lists" else ""), (oid,))
            for t in ("lists", "office_docs", "clients", "hub_absences", "time_sheets")}


# ---------------------------------------------------------------- server, people, organisations
if not os.environ.get("P2237D_NOSTART"):
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
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Mitglied", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
orgs = {}
for name in ("Alpha Team", "Gamma Leer", "Delta Leer"):
    r = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": ALICE})
    assert r.status_code == 201, r.text
    orgs[name] = r.json()["id"]
ORG, ORG3, ORG4 = orgs["Alpha Team"], orgs["Gamma Leer"], orgs["Delta Leer"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
# bundle 2.305 (2.278.0 A #3095): an organisation import maps a ticked person only when he is a member of the target already
# (else he is invited and his rows stay out until he accepts) - bob is a member of both targets, as #2870 assumes
for o in (ORG3, ORG4):
    assert A.put(B + f"/api/orgs/{o}/members", json={"email": "bob@example.com", "role": "member"}).ok
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
NOW = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

# ---------------------------------------------------------------- the organisation's data
LO = ok(A.post(B + "/api/lists", json={"name": "Alpha Projekt", "org_id": ORG}), "org list")["id"]
ok(A.put(B + f"/api/lists/{LO}/members", json={"user_id": BOB, "role": "edit"}), "share the list with bob")
ok(A.patch(B + f"/api/lists/{LO}", json={"kind": "project", "time_tracking": True}), "a project with time tracking")
TO = ok(A.post(B + "/api/tasks", json={"title": "Dreh vorbereiten", "list_id": LO}), "task")["id"]
ok(A.patch(B + f"/api/tasks/{TO}", json={"people": [BOB]}), "bob comes along to the task")
rooms = [x for x in A.get(B + "/api/team").json().get("rooms", []) if x.get("kind") == "list" and x.get("list_id") == LO]
check(rooms, "the list has its channel")
RID = rooms[0]["id"] if rooms else 0
M1 = ok(A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Start um neun"}), "alice writes").get("id")
ok(Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Passt", "reply_to": M1}), "bob answers")
M1 = M1 or one("SELECT MIN(id) FROM tchat_msgs WHERE room_id=?", (RID,))
dbx("INSERT INTO tchat_rx(message_id,user_id,emoji,created_at) VALUES(?,?,?,?)", (M1, BOB, "up", NOW))
for s, who in ((A, "alice"), (Bo, "bob")):
    ok(s.post(B + "/api/time/entries", json={"list_id": LO, "start": "2026-10-12T09:00", "minutes": 30, "note": f"Schnitt {who}"}),
       f"time entry of {who}")
dbx("INSERT INTO time_sheets(org_id,user_id,month,state,note,log,created_at,updated_at,decided_by,decided_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
    (ORG, ALICE, "2026-09", "approved", "", "[]", NOW, NOW, BOB, NOW))
dbx("INSERT INTO hub_absences(org_id,user_id,kind,start_date,end_date,note,created_by,created_at,status,decided_by,decided_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (ORG, BOB, "vacation", "2026-11-02", "2026-11-06", "", BOB, NOW, "approved", BOB, NOW))
# the office: a finalised invoice and a draft
CL = ok(A.post(B + "/api/clients", json={"name": "Kunde Beispiel", "email": "kunde@example.com", "org_id": ORG, "street": "Musterweg 1",
                                          "zip": "12345", "city": "Musterstadt"}), "a client")["id"]
ok(A.put(B + f"{O}/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "street": "Hafenweg 2", "zip": "12345", "city": "Musterstadt",
                                                       "iban": "DE02120300000000202051", "tax_number": "12/345/67890"}, "lang": "en", "currency": "EUR"}),
   "office settings")
INV = ok(A.post(B + D, json={"kind": "invoice", "client_id": CL, "project_title": "Fertig", "service_from": "2026-05-01",
                             "items": [{"title": "Beratung", "qty": 1, "rate": 300}]}), "an invoice").get("id")
check(ok(A.post(B + f"{D}/{INV}/finalize"), "finalise").get("locked"), "the invoice is finalised")
ok(A.post(B + D, json={"kind": "invoice", "client_id": CL, "project_title": "Entwurf", "service_from": "2026-06-01",
                       "items": [{"title": "Schnitt", "qty": 1, "rate": 500}]}), "a draft")

OX, RK = export(A, ORG)
dbx("DELETE FROM time_sheets WHERE org_id=?", (ORG,))  # one timesheet per person and month on the whole server (like a move to another server)

# ---------------------------------------------------------------- import into the empty organisation, bob ticked
j = run(A, opened(A, OX, RK), ORG3, people={EH("bob@example.com"): {"share": True}})
NL = one("SELECT id FROM lists WHERE org_id=? AND name='Alpha Projekt'", (ORG3,))
NT = one("SELECT id FROM tasks WHERE list_id=? AND title='Dreh vorbereiten'", (NL,))
NR = one("SELECT id FROM tchat_rooms WHERE kind='list' AND list_id=?", (NL,))
check(NL and NT and NR, "list, task and channel are in the new organisation")
by = {x["body"]: x["user_id"] for x in dbx("SELECT body, user_id FROM tchat_msgs WHERE room_id=?", (NR,))}
check(by.get("Start um neun") == ALICE, f"alice's own message keeps her as author {by}")
check("Passt" in by and by["Passt"] is None, f"bob's message comes without an account as author {by}")
check(not dbx("SELECT 1 FROM tchat_rx x JOIN tchat_msgs m ON m.id=x.message_id WHERE m.room_id=? AND x.user_id=?", (NR, BOB)),
      "no reaction under bob's account")
te = dbx("SELECT user_id, note FROM time_entries WHERE list_id=? ORDER BY note", (NL,))
check(len(te) == 2 and all(x["user_id"] == ALICE for x in te), f"both time entries under the importing person {[dict(x) for x in te]}")
check(any(x["note"].startswith("Bob Mitglied: ") and "Schnitt bob" in x["note"] for x in te), f"bob's entry names him in the note {[x['note'] for x in te]}")
ts = dbx("SELECT user_id, decided_by FROM time_sheets WHERE org_id=?", (ORG3,))
check(ts and all(x["decided_by"] != BOB for x in ts), f"the timesheet is not decided by bob {[dict(x) for x in ts]}")
ab = dbx("SELECT user_id, created_by, decided_by FROM hub_absences WHERE org_id=?", (ORG3,))
check(len(ab) == 1 and ab[0]["user_id"] == BOB and ab[0]["created_by"] != BOB and ab[0]["decided_by"] != BOB,
      f"bob's absence is his (like an admin enters it), not entered or decided by him {[dict(x) for x in ab]}")
check(one("SELECT user_id FROM task_people WHERE task_id=?", (NT,)) == BOB, "bob stays on the task (sharing)")
check(not dbx("SELECT 1 FROM office_doc_log WHERE org_id=? AND user_id=?", (ORG3, BOB)), "no office log entry under bob")
nd = {x["project_title"]: x["id"] for x in dbx("SELECT id, project_title FROM office_docs WHERE org_id=?", (ORG3,))}
check({"Fertig", "Entwurf"} <= set(nd), f"both documents came along {nd}")
lg = dbx("SELECT doc_id, user_id FROM office_doc_log WHERE org_id=? AND action='import' AND target='doc'", (ORG3,))
check({x["doc_id"] for x in lg} >= {nd.get("Fertig"), nd.get("Entwurf")} and all(x["user_id"] == ALICE for x in lg),
      f"the office log says the documents were imported, by alice {[dict(x) for x in lg]}")
IMP3 = (j.get("result") or {}).get("import_id")

# ---------------------------------------------------------------- undo: only admins of the target now, nothing frozen since
check(A.put(B + f"/api/orgs/{ORG3}/members", json={"email": "bob@example.com", "role": "admin"}).ok, "bob becomes admin of the target")
check(Bo.put(B + f"/api/orgs/{ORG3}/members", json={"email": "alice@example.com", "role": "member"}).ok, "alice is no admin there any more")
before = counts(ORG3)
r = A.post(B + f"/api/imports/{IMP3}/undo")
check(r.status_code == 403, f"undo as a former admin: 403 ({r.status_code} {r.text[:160]})")
check(counts(ORG3) == before and before["lists"] and before["office_docs"], f"nothing removed {before} {counts(ORG3)}")
check(Bo.put(B + f"/api/orgs/{ORG3}/members", json={"email": "alice@example.com", "role": "admin"}).ok, "alice is admin again")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG3}"})
check(ok(A.post(B + f"{D}/{nd.get('Entwurf')}/finalize"), "finalise the imported draft in the target").get("locked"), "the draft is finalised")
r = A.post(B + f"/api/imports/{IMP3}/undo")
check(r.status_code == 409, f"undo after a document of it was finalised here: 409 ({r.status_code} {r.text[:160]})")
check(counts(ORG3) == before, f"nothing removed {before} {counts(ORG3)}")

# ---------------------------------------------------------------- the normal undo by the admin (another target)
j = run(A, opened(A, OX, RK), ORG4, people={EH("bob@example.com"): {"share": True}})
check(one("SELECT COUNT(*) FROM office_docs WHERE org_id=? AND locked_at IS NOT NULL", (ORG4,)) == 1, "the invoice finalised in the file came along")
r = A.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok, f"undo by the admin {r.status_code} {r.text[:160]}")
check(not any(counts(ORG4).values()), f"the undo removed everything {counts(ORG4)}")
check(not dbx("SELECT 1 FROM office_doc_log WHERE org_id=? AND action='import'", (ORG4,)), "... and its 'imported' log entries")

# ---------------------------------------------------------------- a freelancer imports it privately (unchanged)
FID, Fr = freelancer(B, A)
j = run(Fr, opened(Fr, OX, RK), "private")
FL = one("SELECT id FROM lists WHERE owner_id=? AND name='Alpha Projekt'", (FID,))
check(FL, "freelancer: the project came along")
check(one("SELECT COUNT(*) FROM tchat_msgs m JOIN tchat_rooms r ON r.id=m.room_id WHERE r.list_id=? AND m.user_id IS NOT NULL AND m.user_id<>?",
          (FL, FID)) == 0, "freelancer: no chat message under another account")
check(one("SELECT COUNT(*) FROM time_entries WHERE list_id=?", (FL,)) == 0, "freelancer: no time entries of others")
check(not dbx("SELECT 1 FROM org_members WHERE user_id=?", (FID,)), "freelancer: still in no organisation")
r = Fr.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok and r.json().get("trash") and not dbx("SELECT 1 FROM lists WHERE id=? AND deleted_at IS NULL", (FL,)),
      f"freelancer: own undo works (the list in the trash, 2.272.0 C) {r.status_code} {r.text[:160]}")

if FAILS:  # the container log once
    ct = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
    print(subprocess.run(["docker", "logs", "--tail", "60", ct], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True).stdout[-6000:], flush=True)
print(f"p2237_d_orgimport: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
