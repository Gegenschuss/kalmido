#!/usr/bin/env python3
"""2.278.0 part B (#3094): the organisation / account import keeps billed time entries billed, maps the chat threads and
names every row it leaves out. Invented names only (example.com).
 - an organisation with a finalised invoice and three time entries (billed on that invoice, billed on a document that does
   not come along, open), a chat thread, a payment on a document of another organisation, a task in the trash with a
   reaction, and a chat reaction of a person who is not ticked; exported and imported into an EMPTY organisation:
   the billed entry points at the NEW invoice (billed_at kept), the one without its document comes billed but not billable
   (never open: no second billing), the open one stays open; the thread answer points at the new first message; the left-out
   payment and the reaction of the person not ticked are named once with their number; the trash stays behind silently
 - a person without organisation (freelancer, P4) moves a billed time entry by account export / import: it stays billed
   (not billable, billing date kept, no invoice: the account export has none), the open one stays open
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2278B_NOSTART=1 = the server already runs like that).
usage: p2278_b_import_ids_test.py <datadir>"""
# freelancer-matrix: own
# tenant-matrix: own
import base64
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm
from freelancer_fixture import FEATURES, freelancer
from kt import FAILS, OKS, check, sess

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
D = "/api/office/docs"


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


def run(s, iid, target, people=None):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": target, "people": people or {}, "again": True})  # 2.269.0 D (#3046): the same export runs several times here on purpose
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    return wait(s, iid)


def warns(j):
    return {x.get("text", ""): x.get("count", 1) for x in (j.get("result") or {}).get("warnings", [])}


# ---------------------------------------------------------------- server, people, organisations
if not os.environ.get("P2278B_NOSTART"):
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
for name in ("Alpha Quelle", "Beta Fremd", "Gamma Leer"):
    r = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": ALICE})
    assert r.status_code == 201, r.text
    orgs[name] = r.json()["id"]
ORG, ORGB, ORG3 = orgs["Alpha Quelle"], orgs["Beta Fremd"], orgs["Gamma Leer"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
# a member without an e-mail address: the import can only match carl by the user name the admin types
r = A.post(B + "/api/users", json={"username": "carl", "display_name": "Carl Ohne", "password": "password123"})
assert r.ok, r.text
CARL = r.json()["id"]
dbx("UPDATE users SET email=NULL WHERE id=?", (CARL,))
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,?)", (ORG, CARL, "member"))  # member of alpha (the API needs an address)
NOW = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

# ---------------------------------------------------------------- a document of another organisation (not in the export)
A.patch(B + "/api/settings", json={"workspace": f"org:{ORGB}"})
CLB = ok(A.post(B + "/api/clients", json={"name": "Kunde Fremd", "email": "fremd@example.com", "org_id": ORGB}), "client of beta").get("id")
FOREIGN = ok(A.post(B + D, json={"kind": "invoice", "client_id": CLB, "items": [{"title": "Fremd", "qty": 1, "rate": 50}]}),
             "a draft invoice of beta").get("id")

# ---------------------------------------------------------------- the source organisation
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
ok(A.put(B + "/api/office/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "street": "Hafenweg 2", "zip": "12345",
                                                               "city": "Musterstadt", "iban": "DE02120300000000202051",
                                                               "tax_number": "12/345/67890"}, "lang": "en", "currency": "EUR"}),
   "office settings")
CL = ok(A.post(B + "/api/clients", json={"name": "Kunde Beispiel", "email": "kunde@example.com", "org_id": ORG, "street": "Musterweg 1",
                                         "zip": "12345", "city": "Musterstadt"}), "client").get("id")
INV = ok(A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-05-01",
                             "items": [{"title": "Schnitt", "qty": 1, "rate": 300}]}), "an invoice").get("id")
r = A.post(B + f"{D}/{INV}/finalize")
check(r.ok and r.json().get("locked"), "the invoice is finalised " + r.text[:160])
INV_NO = r.json().get("number") if r.ok else None
dbx("INSERT INTO office_payments(org_id,doc_id,date,amount,method,note,created_at) VALUES(?,?,?,?,?,?,?)",
    (ORG, FOREIGN, "2026-06-01", 50, "transfer", "", NOW))  # points at a document that does not come along

LO = ok(A.post(B + "/api/lists", json={"name": "B Projekt", "org_id": ORG}), "org list")["id"]
ok(A.put(B + f"/api/lists/{LO}/members", json={"user_id": BOB, "role": "edit"}), "share the list")
ok(A.patch(B + f"/api/lists/{LO}", json={"kind": "project", "time_tracking": True}), "a project with time tracking")
E = {}
for minutes in (30, 45, 60):
    E[minutes] = ok(A.post(B + "/api/time/entries", json={"list_id": LO, "start": "2026-10-12T09:00", "minutes": minutes}),
                    f"time entry {minutes} min").get("id")
dbx("UPDATE time_entries SET billed_doc_id=?, billed_at=? WHERE id=?", (INV, "2026-10-13T10:00:00+00:00", E[30]))
dbx("UPDATE time_entries SET billed_doc_id=?, billed_at=? WHERE id=?", (FOREIGN, "2026-10-14T10:00:00+00:00", E[45]))
check(one("SELECT billed_doc_id FROM time_entries WHERE id=?", (E[30],)) == INV, "the entry is billed on the invoice")
# chat: a thread (first message + an answer in its thread) and a reaction of bob
rooms = [x for x in A.get(B + "/api/team").json().get("rooms", []) if x.get("kind") == "list" and x.get("list_id") == LO]
check(rooms, "the list has its channel")
RID = rooms[0]["id"] if rooms else 0
M1 = ok(A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Thread Anfang"}), "first message").get("id")
M2 = ok(A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Thread Antwort"}), "answer").get("id")
M1 = M1 or one("SELECT MIN(id) FROM tchat_msgs WHERE room_id=?", (RID,))
M2 = M2 or one("SELECT MAX(id) FROM tchat_msgs WHERE room_id=?", (RID,))
dbx("UPDATE tchat_msgs SET thread_of=? WHERE id=?", (M1, M2))
dbx("INSERT INTO tchat_rx(message_id,user_id,emoji,created_at) VALUES(?,?,?,?)", (M1, BOB, "up", NOW))
# a task in the trash with a comment + reaction (the trash stays behind: no warning for what hangs on it)
TT = ok(A.post(B + "/api/tasks", json={"title": "Weg damit", "list_id": LO}), "task for the trash")["id"]
CT = ok(A.post(B + f"/api/tasks/{TT}/comments", json={"body": "Notiz"}), "comment").get("id")
ok(Bo.post(B + f"/api/comments/{CT}/reactions", json={"emoji": "up", "on": True}), "bob reacts")
ok(A.delete(B + f"/api/tasks/{TT}"), "into the trash")

# ---------------------------------------------------------------- export, import into the empty organisation
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, f"organisation export started {r.text[:120]}")
for _ in range(960):  # until it is done (not only "not running": under load the file may not be there yet)
    xs = A.get(B + f"/api/orgs/{ORG}/export").json().get("state")
    if xs in ("done", "failed"):
        break
    time.sleep(0.25)
check(xs == "done", f"organisation export done {xs}")
OX = A.get(B + f"/api/orgs/{ORG}/export/file").content
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
check(OX[:13] == b"KALMIDO-ORGX\n" and RK, "organisation export + recovery key")
iid = upload(A, OX)
j = wait(A, iid)
check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {str(j.get('error') or '')[:200]}")
check(A.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": RK}).status_code == 202, "the recovery key is taken")
j = wait(A, iid)
check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
pp = {x.get("name"): x for x in (j.get("preview") or {}).get("people", [])}
c0 = pp.get("Carl Ohne", {})
check(c0.get("key") == f"id{CARL}" and c0.get("by_login") is True and not c0.get("found"),
      f"preview: carl (no address) is offered for a user name {c0}")
check(pp.get("Bob Mitglied", {}).get("found") is True, f"preview: bob is found by his address {pp.get('Bob Mitglied')}")
# a typed user name: carl (visible) is matched; an unknown name and a malformed one are skipped alike (no account listing)
j = run(A, iid, ORG3, people={f"id{CARL}": {"share": True, "login": "Carl "}, "id987654321": {"share": True, "login": "nobody"}})
res = {x.get("name"): x.get("state") for x in (j.get("result") or {}).get("people", [])}
check(res.get("Carl Ohne") not in (None, "skipped"), f"carl matched by user name {res}")  # bob not ticked
check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')}")
W = warns(j)
NL = one("SELECT id FROM lists WHERE org_id=? AND name='B Projekt'", (ORG3,))
check(NL, "the list is in the new organisation")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG3}"})
inv = [x for x in A.get(B + D + "?kind=invoice").json().get("docs", []) if x.get("number") == INV_NO]
check(len(inv) == 1, f"the finalised invoice came along {len(inv)}")
NINV = inv[0]["id"] if inv else -1
te = {r["seconds"]: dict(r) for r in dbx("SELECT seconds, billed_doc_id, billed_at, billable FROM time_entries WHERE list_id=?", (NL,))}
check(set(te) == {1800, 2700, 3600}, f"the three time entries came along {sorted(te)}")
b = te.get(1800, {})
check(b.get("billed_doc_id") == NINV and NINV != INV and b.get("billed_at", "").startswith("2026-10-13") and b.get("billable") == 1,
      f"billed entry: on the NEW invoice, billing date kept {b} new invoice {NINV}")
x = te.get(2700, {})
check(x.get("billed_doc_id") is None and (x.get("billed_at") or "").startswith("2026-10-14") and x.get("billable") == 0,
      f"billed without its document: stays billed (not billable), never open {x}")
o = te.get(3600, {})
check(o.get("billed_doc_id") is None and not o.get("billed_at") and o.get("billable") == 1, f"the open entry stays open {o}")
check(W.get("Billed time entries without their invoice were taken over as not billable") == 1, f"warning with its number {W}")
# chat thread
NR = one("SELECT id FROM tchat_rooms WHERE kind='list' AND list_id=?", (NL,))
by = {r["body"]: dict(r) for r in dbx("SELECT id, body, thread_of FROM tchat_msgs WHERE room_id=?", (NR,))}
n1, n2 = by.get("Thread Anfang", {}), by.get("Thread Antwort", {})
check(n1.get("id") and n2.get("thread_of") == n1.get("id") and n1.get("id") != M1, f"the answer hangs on the NEW first message {n1} {n2}")
check(n1.get("thread_of") is None, "the first message stays the thread's start")
# left-out rows: named once, with their number
check(W.get("Not taken over because the entry it belongs to is missing: Payments") == 1, f"the payment without its document is named {W}")
check(W.get("Entries of people who were not chosen were not taken over: Team chat", 0) >= 1, f"bob's chat reaction is named {W}")
check(not [k for k in W if "entry it belongs to is missing" in k and ("Reactions" in k or "History" in k)],
      f"the trash stays behind without a warning {W}")
check(one("SELECT COUNT(*) FROM office_payments WHERE org_id=?", (ORG3,)) == 0, "no payment without its document")

# the user name never finds what the admin could not see anyway: a malformed / unknown name = the same answer
iid2 = upload(A, OX)
wait(A, iid2)
A.post(B + f"/api/account/import/{iid2}/key", json={"recovery_key": RK})
wait(A, iid2)
j2 = run(A, iid2, "private", people={f"id{CARL}": {"share": True, "login": "nob%dy"}})
r2 = {x.get("name"): x.get("state") for x in (j2.get("result") or {}).get("people", [])}
check(r2.get("Carl Ohne") == "skipped", f"a malformed user name matches nobody {r2}")

# ---------------------------------------------------------------- P4: a freelancer moves billed time by account export / import
FID, Fr = freelancer(B, A, features=FEATURES)
FL = ok(Fr.post(B + "/api/lists", json={"name": "Frei Projekt"}), "freelancer list")["id"]
ok(Fr.patch(B + f"/api/lists/{FL}", json={"time_tracking": True}), "time tracking")
F1 = ok(Fr.post(B + "/api/time/entries", json={"list_id": FL, "start": "2026-10-12T09:00", "minutes": 20}), "billed entry").get("id")
ok(Fr.post(B + "/api/time/entries", json={"list_id": FL, "start": "2026-10-12T11:00", "minutes": 40}), "open entry")
dbx("UPDATE time_entries SET billed_doc_id=?, billed_at=? WHERE id=?", (987654321, "2026-10-15T10:00:00+00:00", F1))
r = Fr.post(B + "/api/account/export")
check(r.status_code == 202, f"account export started {r.text[:120]}")
for _ in range(480):
    if Fr.get(B + "/api/account/export").json().get("state") != "running":
        break
    time.sleep(0.25)
AX = Fr.get(B + "/api/account/export/file").content
GID, Gr = freelancer(B, A, name="greta", features=FEATURES)
iid = upload(Gr, AX, "frida.zip")
j = wait(Gr, iid)
check(j.get("state") == "preview", f"freelancer: opened {j.get('state')} {j.get('error')}")
j = run(Gr, iid, "private")
check(j.get("state") == "done", f"freelancer: import done {j.get('error')}")
fe = {r["seconds"]: dict(r) for r in dbx("SELECT seconds, billed_doc_id, billed_at, billable FROM time_entries WHERE user_id=?", (GID,))}
check(set(fe) == {1200, 2400}, f"freelancer: both entries came along {sorted(fe)}")
check(fe.get(1200, {}).get("billable") == 0 and (fe.get(1200, {}).get("billed_at") or "").startswith("2026-10-15")
      and fe.get(1200, {}).get("billed_doc_id") is None, f"freelancer: the billed entry stays billed {fe.get(1200)}")
check(fe.get(2400, {}).get("billable") == 1 and not fe.get(2400, {}).get("billed_at"), f"freelancer: the open entry stays open {fe.get(2400)}")
check(warns(j).get("Billed time entries without their invoice were taken over as not billable") == 1, f"freelancer: warning {warns(j)}")
check(not dbx("SELECT 1 FROM org_members WHERE user_id IN (?,?)", (FID, GID)), "freelancer: still in no organisation")

if FAILS:
    ct = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
    print(subprocess.run(["docker", "logs", "--tail", "60", ct], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True).stdout[-6000:], flush=True)
print(f"p2278_b_import_ids: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
