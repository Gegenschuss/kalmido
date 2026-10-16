#!/usr/bin/env python3
"""2.66.0 API tests (part B): #1835 merging duplicate clients (POST /api/clients/merge, POST /api/clients/merges/{id}/undo).
 - dry: the overview (issued / open documents, contracts, archive entries, projects, contact persons), nothing changes
 - merge: quotations / invoices, contracts, archive entries, projects (lists.client_id) and contact persons move to the
   target; the finalised invoice keeps its printed address (snapshot, e-invoice XML), billed time stays billed; exactly one
   default contact person; picked fields win, empty target fields take the first filled value; the target's
   import_run_id is emptied; the other client is gone; history line in the client's answer; office log
 - undo: the clients come back under their ids with everything that moved; a second undo = 409; a reference moved on by
   hand since stays, a target field edited since stays; target deleted since: the others come back (target_gone)
 - rights: another organisation 404, a member who may not delete the other client 403, undo of a foreign run 404 / 403,
   clients of two workspaces (organisations, private + organisation) 400, invalid ids / pick 400, too many ids 400, CSRF
tenant-matrix: client
usage: p266_b_api_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,time"
TEST_IBAN = "DE02120300000000202051"
D = "/api/office/docs"
M_URL = B + "/api/clients/merge"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def undo_url(rid):
    return B + f"/api/clients/merges/{rid}/undo"


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments", "time"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
ORG3 = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
r = A.put(B + "/api/office/settings", json={"company": {"name": "Example Studio GmbH"}, "lang": "en", "currency": "EUR",
                                            "company_fields": {"name": "Example Studio GmbH", "street": "Example Road 1", "zip": "10115", "city": "Berlin",
                                                               "country": "DE", "email": "office@example.com", "phone": "+49 30 000000",
                                                               "tax_number": "12/345/67890", "iban": TEST_IBAN, "bic": "BYLADEM1001",
                                                               "bank_name": "Example Bank"}, "payment_days": 14})
check(r.ok, "setup: office settings " + r.text[:200])

# ---- two duplicates in Alpha: T (the target) and M (merged into it)
r = A.post(B + "/api/clients", json={"name": "Acme Ltd", "org_id": ORG, "email": "target@example.com", "rate": 80, "street": "New Street 1",
                                     "zip": "10115", "city": "Berlin", "country": "DE", "contacts": [{"name": "Tina Target", "is_default": True}]})
check(r.status_code == 201, "setup: client T " + r.text[:200])
T = r.json()["id"]
r = A.post(B + "/api/clients", json={"name": "ACME Ltd (old)", "org_id": ORG, "phone": "+49 40 1111", "rate": 90, "note": "old note",
                                     "street": "Old Street 9", "zip": "20095", "city": "Hamburg", "country": "DE",
                                     "contacts": [{"name": "Max Merge", "is_default": True}, {"name": "Mia Second"}]})
check(r.status_code == 201, "setup: client M " + r.text[:200])
M = r.json()["id"]
KMAX, KMIA = (k["id"] for k in r.json()["contacts"])
KT = A.get(B + f"/api/clients/{T}").json()["contacts"][0]["id"]
dbx("UPDATE clients SET import_run_id=5 WHERE id=?", (T,), write=True)

# a project of M with tracked time, billed by M's finalised invoice (covering the day, item = the project's name)
P = A.post(B + "/api/lists", json={"name": "Harbour site", "kind": "project", "time_tracking": True}).json()["id"]
dbx("UPDATE lists SET org_id=?, client_id=? WHERE id=?", (ORG, M, P), write=True)
r = A.post(B + "/api/time/entries", json={"list_id": P, "start": "2026-09-20T08:00:00Z", "end": "2026-09-20T10:00:00Z"})
check(r.ok, "setup: a time entry " + r.text[:200])
r = A.post(B + D, json={"kind": "invoice", "client_id": M, "service_from": "2026-09-18", "service_to": "2026-09-22",
                        "items": [{"title": "Harbour site", "qty": 1, "rate": 100}]})
check(r.status_code == 201, "setup: invoice of M " + r.text[:200])
I1 = r.json()["id"]
r = A.post(B + f"{D}/{I1}/finalize")
check(r.ok, "setup: invoice finalised " + r.text[:200])
SNAP = one("SELECT recipient_snapshot FROM office_docs WHERE id=?", (I1,))
REC = one("SELECT recipient FROM office_docs WHERE id=?", (I1,))
check(SNAP and "Old Street 9" in SNAP, "setup: the snapshot holds M's address " + str(SNAP)[:200])
r = A.post(B + D, json={"kind": "offer", "client_id": M, "items": [{"title": "Edit", "qty": 1, "rate": 50}]})
I2 = r.json()["id"]
CO = dbx("INSERT INTO office_contracts(org_id, name, client_id, created_at, updated_at) VALUES(?,?,?,?,?) RETURNING id",
         (ORG, "Frame contract", M, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"), write=True)[0][0]
AR = dbx("INSERT INTO office_archive(org_id, kind, number, client_id, client_name, created_at) VALUES(?,?,?,?,?,?) RETURNING id",
         (ORG, "invoice", "OLD-2020-1", M, "ACME old name", "2026-01-01T00:00:00Z"), write=True)[0][0]


def billed():
    return A.get(B + f"/api/lists/{P}/time/delete-all").json().get("billed")


check(billed() == 1, "setup: the time entry counts as billed")

# ================================================================== dry run
r = A.post(M_URL, json={"target": T, "ids": [T, M], "pick": {"phone": M, "rate": M}, "dry": True})
check(r.ok, f"dry: ok ({r.status_code} {r.text[:200]})")
lines = r.json().get("lines") or []
txt = " | ".join(lines)
for want in ("1 issued quotation or invoice", "1 draft or open quotation shows the address of Acme Ltd", "1 contract", "1 archive entry",
             "1 project", "2 contact persons"):
    check(want in txt, f"dry: the overview names '{want}': {txt}")
check(A.get(B + f"/api/clients/{M}").ok and one("SELECT client_id FROM office_docs WHERE id=?", (I1,)) == M
      and one("SELECT COUNT(*) FROM merge_runs") == 0, "dry: nothing changes")

# ================================================================== rights and input
check(Ca.post(M_URL, json={"target": T, "ids": [M]}).status_code == 404, "tenant-matrix: client -- another organisation cannot merge (404)")
check(Ca.post(M_URL, json={"target": T, "ids": [M], "dry": True}).status_code == 404, "tenant-matrix: client -- ... not even the overview (404)")
check(Bo.post(M_URL, json={"target": T, "ids": [M]}).status_code == 403, "a member who may not delete the other client: 403")
G = A.post(B + "/api/clients", json={"name": "Gamma client", "org_id": ORG3}).json()["id"]
PR = A.post(B + "/api/clients", json={"name": "Private client", "org_id": None}).json()["id"]
check(A.post(M_URL, json={"target": T, "ids": [G]}).status_code == 400, "clients of two organisations: 400")
check(A.post(M_URL, json={"target": T, "ids": [PR]}).status_code == 400, "a private client and an organisation's client: 400")
check(A.post(M_URL, json={"target": T, "ids": [T]}).status_code == 400, "only one client: 400")
check(A.post(M_URL, json={"target": T, "ids": list(range(T, T + 11))}).status_code in (400, 404), "more than 10 clients: 400")
check(A.post(M_URL, json={"target": T, "ids": [str(M), "x"]}).status_code == 400, "an invalid id: 400")
check(A.post(M_URL, json={"target": True, "ids": [M]}).status_code == 400, "target true: 400")
check(A.post(M_URL, json={"target": T, "ids": [M], "pick": {"secret": M}}).status_code == 400, "an unknown pick field: 400")
check(A.post(M_URL, json={"target": T, "ids": [M], "pick": {"phone": G}}).status_code == 400, "a pick from a client outside the merge: 400")
check(A.post(M_URL, json={"target": T, "ids": [M], "extra": 1}).status_code == 400, "an unknown body field: 400")
check(A.post(M_URL, json={"target": T, "ids": [999999]}).status_code == 404, "an unknown client: 404")
r = A.post(M_URL, json={"target": T, "ids": [M]}, headers={"X-Requested-With": None})
check(r.status_code in (400, 401, 403) and A.get(B + f"/api/clients/{M}").ok, f"CSRF: without the app header nothing happens ({r.status_code})")
check(one("SELECT COUNT(*) FROM merge_runs") == 0, "no merge so far")

# ================================================================== merge
r = A.post(M_URL, json={"target": T, "ids": [T, M], "pick": {"phone": M, "rate": M}})
check(r.ok, f"merge: ok ({r.status_code} {r.text[:300]})")
RID = r.json().get("run_id")
t = r.json().get("target") or {}
check(t.get("id") == T and t.get("phone") == "+49 40 1111" and t.get("rate") == 90 and t.get("email") == "target@example.com"
      and t.get("note") == "old note" and t.get("name") == "Acme Ltd",
      f"merge: picked fields win, the target keeps its own, an empty one takes the other's {t}")
check(t.get("billing", {}).get("street") == "New Street 1", "merge: the target keeps its own address")
ks = t.get("contacts") or []
check(sorted(k["name"] for k in ks) == ["Max Merge", "Mia Second", "Tina Target"], f"merge: the contact persons are joined {ks}")
check([k["name"] for k in ks if k["is_default"]] == ["Tina Target"] and t.get("contact") == "Tina Target",
      "merge: exactly one default contact person (the target's)")
check(A.get(B + f"/api/clients/{M}").status_code == 404 and one("SELECT COUNT(*) FROM clients WHERE id=?", (M,)) == 0, "merge: the other client is gone")
for tb, i in (("office_docs", I1), ("office_docs", I2), ("office_contracts", CO), ("office_archive", AR), ("lists", P)):
    check(one(f"SELECT client_id FROM {tb} WHERE id=?", (i,)) == T, f"merge: {tb} {i} moved to the target")
check(one("SELECT client_name FROM office_archive WHERE id=?", (AR,)) == "ACME old name", "merge: the archive entry keeps its client name")
check(one("SELECT recipient_snapshot FROM office_docs WHERE id=?", (I1,)) == SNAP and one("SELECT recipient FROM office_docs WHERE id=?", (I1,)) == REC,
      "merge: the finalised invoice keeps its printed address (snapshot unchanged)")
x = A.get(B + f"{D}/{I1}/xml").text
bp = x[x.find("BuyerTradeParty"):x.find("</ram:BuyerTradeParty>")]
check("Old Street 9" in bp and "New Street 1" not in bp, "merge: the e-invoice of the finalised invoice shows the old address " + bp[:300])
check(billed() == 1, "merge: the billed time stays billed")
check(one("SELECT import_run_id FROM clients WHERE id=?", (T,)) is None, "merge: the target's import_run_id is emptied")
mg = t.get("merges") or []
check(len(mg) == 1 and mg[0]["id"] == RID and mg[0]["merged"] == [{"id": M, "name": "ACME Ltd (old)"}] and mg[0]["undo"] == ""
      and mg[0]["can_undo"] and mg[0]["by_name"] == "Alice Admin", f"merge: the history line in the client's answer {mg}")
check(one("SELECT COUNT(*) FROM office_doc_log WHERE org_id=? AND action='client_merge'", (ORG,)) == 1, "merge: office log entry")
check(one("SELECT org_id FROM merge_runs WHERE id=?", (RID,)) == ORG, "merge: the run carries the organisation")
mb = Bo.get(B + f"/api/clients/{T}").json().get("merges") or []
check(len(mb) == 1 and mb[0]["can_undo"] is False, "merge: a member sees the line but may not undo it")

# ================================================================== undo: rights, then undo
check(Ca.post(undo_url(RID)).status_code == 404, "tenant-matrix: client -- another organisation cannot undo the merge (404)")
check(Bo.post(undo_url(RID)).status_code == 403, "undo: a member who may not delete the clients: 403")
check(A.post(undo_url(999999)).status_code == 404, "undo: an unknown run: 404")
r = A.post(undo_url(RID))
check(r.ok and r.json().get("ok") and r.json().get("target_gone") is False, f"undo: ok ({r.status_code} {r.text[:300]})")
m = A.get(B + f"/api/clients/{M}")
check(m.ok and m.json()["name"] == "ACME Ltd (old)" and m.json()["phone"] == "+49 40 1111", "undo: the other client is back under its id")
mk = m.json().get("contacts") or []
check(sorted(k["id"] for k in mk) == sorted([KMAX, KMIA]) and [k["id"] for k in mk if k["is_default"]] == [KMAX], f"undo: its contact persons are back {mk}")
tt = A.get(B + f"/api/clients/{T}").json()
check([k["id"] for k in tt["contacts"]] == [KT] and tt["phone"] == "" and tt["rate"] == 80 and tt["note"] == "", f"undo: the target's values are back {tt}")
check(one("SELECT import_run_id FROM clients WHERE id=?", (T,)) == 5, "undo: the target's import_run_id is back")
for tb, i in (("office_docs", I1), ("office_docs", I2), ("office_contracts", CO), ("office_archive", AR), ("lists", P)):
    check(one(f"SELECT client_id FROM {tb} WHERE id=?", (i,)) == M, f"undo: {tb} {i} back at the other client")
check(billed() == 1, "undo: the billed time stays billed")
check(A.post(undo_url(RID)).status_code == 409, "undo: a second time = 409")
h = tt.get("merges") or []
check(len(h) == 1 and h[0]["undo"] == "undone" and h[0]["undone_at"], f"undo: the history line says undone {h}")
check(one("SELECT COUNT(*) FROM office_doc_log WHERE org_id=? AND action='client_merge_undo'", (ORG,)) == 1, "undo: office log entry")

# ---- undo after later changes: a field edited since stays, a reference moved on since stays
r = A.post(M_URL, json={"target": T, "ids": [M], "pick": {"rate": M}})
check(r.ok and r.json()["target"]["rate"] == 90, "again: merged (redo)")
RID2 = r.json()["run_id"]
check(A.patch(B + f"/api/clients/{T}", json={"rate": 100}).ok, "again: the rate edited afterwards")
X = A.post(B + "/api/clients", json={"name": "Third client", "org_id": ORG}).json()["id"]
dbx("UPDATE office_docs SET client_id=? WHERE id=?", (X, I2), write=True)
r = A.post(undo_url(RID2))
check(r.ok, "again: undone " + r.text[:200])
check(A.get(B + f"/api/clients/{T}").json()["rate"] == 100, "undo: a field edited since the merge keeps the new value")
check(one("SELECT client_id FROM office_docs WHERE id=?", (I2,)) == X, "undo: a document moved to another client since stays there")
check(one("SELECT client_id FROM office_docs WHERE id=?", (I1,)) == M, "undo: ... the others go back")
dbx("UPDATE office_docs SET client_id=? WHERE id=?", (M, I2), write=True)

# ---- undo after the target was deleted
r = A.post(M_URL, json={"target": T, "ids": [M]})
RID3 = r.json()["run_id"]
check(A.delete(B + f"/api/clients/{T}").ok, "deleted: the target deleted after the merge")
r = A.post(undo_url(RID3))
check(r.ok and r.json().get("target_gone") is True and r.json().get("target") is None, f"deleted: undo brings the others back ({r.text[:200]})")
check(A.get(B + f"/api/clients/{M}").ok and one("SELECT client_id FROM office_docs WHERE id=?", (I1,)) == M
      and one("SELECT client_id FROM lists WHERE id=?", (P,)) == M, "deleted: the other client and its references are back")
check(one("SELECT recipient_snapshot FROM office_docs WHERE id=?", (I1,)) == SNAP, "the finalised invoice's snapshot never changed")

# ---- the agent token never merges
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "helper", "display_name": "Helper"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
r = requests.post(M_URL, headers=AGH, json={"target": M, "ids": [X]})
check(r.status_code in (401, 403, 404) and A.get(B + f"/api/clients/{X}").ok, f"an agent token cannot merge ({r.status_code})")

print(f"p266_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
