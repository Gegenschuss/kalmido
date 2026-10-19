#!/usr/bin/env python3
"""2.111.0 API tests, part A (#2233): undo for the office editors (kalmido/office/undo.py). Invented names only.
 - a quotation: three own saves with the header X-Kalmido-Undo (head field twice, positions) = three steps; undo = the
   newest step back, redo = forward again, all = back to the opening, redoall = everything again; a member's undo keeps the
   purchase price only the admin sees (the copy is the stored row, not what the member was shown); a part (create, rename)
   is a step of its document too
 - a save without the header records nothing (agents, API, other clients); an own write without undo in between (no
   header) ends the way back: 409
 - someone else changed it in between: 409 and their change stays; finalised / sent in between: 409, the document stays
   as it is, and a save of a sent document records nothing
 - rights: another organisation's person 404, a colleague with the same token 409 (the steps are per person), a member on a
   service (admin only) 403, wrong token / operation 400
 - services (master data) and clients (with contact persons): the values from before the dialog come back; a client moved
   to another workspace in between: 409
 - a person without an organisation (freelancer fixture, P4): the same in the personal office (quotation, service) and
   with a private client
freelancer-matrix: office
usage: p2111_a_api_test.py <datadir>      (a fresh container; P2111A_NOSTART=1: the container runs already)"""
import base64
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "collab,comments,sheets,office,clients,time"
FAILS, OKS = [], [0]
T1, T2, T3, T4, T5, T6, T7, T8 = ("%032x" % (0xa11ce0 + i) for i in range(8))


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


def one(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        r = c.execute(sql, args).fetchall()
        return r[0][0] if r else None
    finally:
        c.close()


def steps(uid, tok):
    return one("SELECT COUNT(*) FROM office_undo WHERE user_id=? AND sess=? AND state='done'", (uid, tok))


def U(tok):
    return {"X-Kalmido-Undo": tok}


def undo(s, kind, rid, tok, op="all"):
    return s.post(B + f"/api/office/undo/{kind}/{rid}", json={"sess": tok, "op": op})


def doc(s, did):
    return s.get(B + f"/api/office/docs/{did}").json()


# ---- setup: alice (instance admin, admin of Alpha), bob member of Alpha, carol admin of Beta; the server key on
if not os.environ.get("P2111A_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_SECRET_KEY=" + KEY + " -e KALMIDO_ORGCRYPT_DELAY=0")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
BOB = uid["bob"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["carol"]})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})

# ---- a quotation: three steps, undo / redo / all / redoall
r = Bo.post(B + "/api/office/docs", json={"project_title": "Spring campaign"})
check(r.status_code == 201, f"bob creates a quotation ({r.status_code} {r.text[:200]})")
D = r.json()["id"]
ITEMS = [{"kind": "service", "title": "Shoot day", "qty": 2, "unit": "day", "rate": 500}]
check(Bo.patch(B + f"/api/office/docs/{D}", json={"project_title": "Spring film"}, headers=U(T1)).ok, "step 1: title")
check(Bo.patch(B + f"/api/office/docs/{D}", json={"intro": "Dear team"}, headers=U(T1)).ok, "step 2: intro")
check(Bo.put(B + f"/api/office/docs/{D}/items", json={"items": ITEMS}, headers=U(T1)).ok, "step 3: positions")
check(steps(BOB, T1) == 3, f"three steps recorded ({steps(BOB, T1)})")
r = undo(Bo, "doc", D, T1, "undo")
check(r.ok and r.json().get("items") == [] and r.json().get("intro") == "Dear team", f"undo: the positions are gone, the intro stays ({r.status_code} {r.text[:200]})")
check(r.ok and r.json().get("undo_steps") == {"done": 2, "undone": 1}, f"undo: 2 done, 1 undone ({r.json().get('undo_steps') if r.ok else ''})")
r = undo(Bo, "doc", D, T1, "redo")
check(r.ok and len(r.json().get("items") or []) == 1 and r.json()["totals"].get("net") == 1000, f"redo: the position is back, net 1000 ({r.text[:200]})")
r = undo(Bo, "doc", D, T1, "all")
d = doc(Bo, D)
check(r.ok and d["project_title"] == "Spring campaign" and d["intro"] == "" and d["items"] == [], f"all: as opened ({r.status_code} {d.get('project_title')!r} {d.get('intro')!r})")
check((d["totals"].get("net") or 0) == 0, "all: the sums follow (net 0)")
r = undo(Bo, "doc", D, T1, "undo")
check(r.status_code == 409, f"nothing left to undo: 409 ({r.status_code})")
r = undo(Bo, "doc", D, T1, "redoall")
d = doc(Bo, D)
check(r.ok and d["project_title"] == "Spring film" and d["intro"] == "Dear team" and len(d["items"]) == 1, f"redoall: everything again ({r.status_code})")
check(any(x.get("action") == "update" and (x.get("detail") or {}).get("undo") for x in A.get(B + f"/api/office/docs/{D}/log").json().get("log", [])),
      "the office log names the undo")

# ---- without the header nothing is recorded; an own write without undo in between ends the way back
n = one("SELECT COUNT(*) FROM office_undo")
check(Bo.patch(B + f"/api/office/docs/{D}", json={"project_ref": "P-1"}).ok and one("SELECT COUNT(*) FROM office_undo") == n, "no header: no step")
r = undo(Bo, "doc", D, T1, "undo")
check(r.status_code == 409 and doc(Bo, D)["project_ref"] == "P-1", f"a change without undo in between: 409, it stays ({r.status_code})")

# ---- a member's undo keeps the purchase price the admin set (the member never saw it)
check(A.put(B + f"/api/office/docs/{D}/items", json={"items": [{**ITEMS[0], "cost": 300}]}).ok, "alice sets the purchase price")
its = Bo.get(B + f"/api/office/docs/{D}").json()["items"]
check("cost" not in its[0], "bob does not see the purchase price")
check(Bo.put(B + f"/api/office/docs/{D}/items", json={"items": [{**its[0], "qty": 3}]}, headers=U(T2)).ok, "bob changes the quantity (step)")
r = undo(Bo, "doc", D, T2)
a = doc(A, D)["items"]
check(r.ok and a[0]["qty"] == 2 and a[0]["cost"] == 300, f"bob's undo: quantity 2, the purchase 300 stays ({r.status_code} {a[0].get('qty')} {a[0].get('cost')})")

# ---- parts of a quotation are steps of the document
r = Bo.post(B + f"/api/office/docs/{D}/parts", json={"title": "Part A"}, headers=U(T3))
check(r.status_code == 201, f"a part (step) ({r.status_code} {r.text[:200]})")
P = (r.json().get("part") or {}).get("id")
check(Bo.patch(B + f"/api/office/docs/{D}/parts/{P}", json={"title": "Part A renamed"}, headers=U(T3)).ok, "rename the part (step)")
r = undo(Bo, "doc", D, T3, "undo")
check(r.ok and [p["title"] for p in r.json().get("parts") or []] == ["Part A"], f"undo: the part's old title ({r.text[:200]})")
r = undo(Bo, "doc", D, T3, "undo")
check(r.ok and not r.json().get("parts") and not any(i.get("kind") == "part" for i in r.json().get("items") or []), "undo: the part and its title page line are gone")
r = undo(Bo, "doc", D, T3, "redoall")
check(r.ok and [p["id"] for p in r.json().get("parts") or []] == [P], "redoall: the part is back with its id")

# ---- someone else changed it in between: refused, their change stays
check(Bo.patch(B + f"/api/office/docs/{D}", json={"project_title": "Bob's title"}, headers=U(T4)).ok, "bob: a step")
check(A.patch(B + f"/api/office/docs/{D}", json={"project_title": "Alice's title"}).ok, "alice changes the same quotation")
r = undo(Bo, "doc", D, T4)
check(r.status_code == 409 and "someone else" in r.json().get("error", "").lower(), f"bob's undo: 409 with the reason ({r.status_code} {r.text[:200]})")
check(doc(A, D)["project_title"] == "Alice's title", "alice's change stays")
# a colleague with bob's token: the steps are bob's
check(Bo.patch(B + f"/api/office/docs/{D}", json={"project_ref": "P-2"}, headers=U(T5)).ok, "bob: another step")
r = undo(A, "doc", D, T5)
check(r.status_code == 409 and doc(A, D)["project_ref"] == "P-2", f"alice with bob's token: 409, nothing undone ({r.status_code})")
# another organisation
r = undo(Ca, "doc", D, T5)
check(r.status_code == 404, f"carol (another organisation): 404 ({r.status_code})")
for body in ({"sess": "x", "op": "undo"}, {"sess": T5, "op": "drop"}):
    r = Bo.post(B + f"/api/office/undo/doc/{D}", json=body)
    check(r.status_code == 400, f"invalid {body}: 400 ({r.status_code})")
r = Bo.post(B + f"/api/office/undo/nothing/{D}", json={"sess": T5, "op": "undo"})
check(r.status_code == 404, f"an unknown kind: 404 ({r.status_code})")

# ---- sent in between: final, nothing undone
r = A.post(B + f"/api/office/docs/{D}/status", json={"status": "sent"})
check(r.ok, f"alice marks it sent ({r.status_code} {r.text[:200]})")
r = undo(Bo, "doc", D, T5)
check(r.status_code == 409 and doc(A, D)["project_ref"] == "P-2" and doc(A, D)["status"] == "sent", f"sent: 409, it stays ({r.status_code} {r.text[:200]})")
n = one("SELECT COUNT(*) FROM office_undo")
r = Bo.patch(B + f"/api/office/docs/{D}", json={"project_ref": "P-3"}, headers=U(T5))
check(r.status_code == 409 and one("SELECT COUNT(*) FROM office_undo") == n, f"a save of a sent document: 409, no step ({r.status_code})")

# ---- master data: a service (admins only)
r = A.post(B + "/api/office/services", json={"name_de": "Beratung", "daily_rate": 800})
check(r.status_code in (200, 201), f"alice: a service ({r.status_code} {r.text[:200]})")
SV = r.json()["id"]
check(A.patch(B + f"/api/office/services/{SV}", json={"name_de": "Beratung plus", "daily_rate": 900}, headers=U(T6)).ok, "alice changes it (step)")
r = undo(Bo, "services", SV, T6)
check(r.status_code == 403, f"bob (member) on a service: 403 ({r.status_code})")
r = undo(A, "services", SV, T6)
sv = A.get(B + f"/api/office/services/{SV}").json()
check(r.ok and sv["name_de"] == "Beratung" and sv["daily_rate"] == 800, f"the service as before ({r.status_code} {sv.get('name_de')} {sv.get('daily_rate')})")
r = undo(A, "services", SV, T6, "redoall")
check(r.ok and A.get(B + f"/api/office/services/{SV}").json()["name_de"] == "Beratung plus", "redo: the new values again")

# ---- a client with contact persons
r = Bo.post(B + "/api/clients", json={"name": "Example Studio", "org_id": ORG, "contacts": [{"name": "Kim Example", "email": "kim@example.com"}]})
check(r.status_code in (200, 201), f"bob: a client ({r.status_code} {r.text[:200]})")
CL = r.json()["id"]
K = one("SELECT id FROM office_client_contacts WHERE client_id=?", (CL,))
r = Bo.patch(B + f"/api/clients/{CL}", json={"name": "Example Studio GmbH", "contacts": [{"id": K, "name": "Kim Sample", "email": "kim@example.com"},
                                                                                          {"name": "Lou Example"}]}, headers=U(T7))
check(r.ok, f"bob changes the client and its contacts (step) ({r.status_code} {r.text[:200]})")
r = undo(Bo, "client", CL, T7)
cl = Bo.get(B + f"/api/clients/{CL}").json()
check(r.ok and cl["name"] == "Example Studio" and one("SELECT COUNT(*) FROM office_client_contacts WHERE client_id=?", (CL,)) == 1
      and one("SELECT name FROM office_client_contacts WHERE id=?", (K,)) == "Kim Example",
      f"the client as before, one contact with its old name and id ({r.status_code} {cl.get('name')})")
r = undo(Ca, "client", CL, T7, "redo")
check(r.status_code == 404, f"carol on bob's organisation client: 404 ({r.status_code})")
# moved to the private space in between (a step itself): the move is not undone by a copy
check(Bo.patch(B + f"/api/clients/{CL}", json={"name": "Moved Studio"}, headers=U(T8)).ok, "bob: a step")
check(Bo.patch(B + f"/api/clients/{CL}", json={"org_id": None}, headers=U(T8)).ok, "bob moves the client into his private space (step)")
r = undo(Bo, "client", CL, T8, "undo")
check(r.status_code == 409 and Bo.get(B + f"/api/clients/{CL}").json().get("org_id") is None, f"undo of a move: 409, it stays private ({r.status_code} {r.text[:200]})")

# ---- a person without an organisation: the personal office, a private client (P4)
FID, Fr = freelancer(B, A)
r = Fr.post(B + "/api/office/docs", json={"project_title": "Own job"})
check(r.status_code == 201, f"freelancer: a quotation in the personal office ({r.status_code} {r.text[:200]})")
FD = r.json()["id"]
check(Fr.patch(B + f"/api/office/docs/{FD}", json={"project_title": "Own job 2"}, headers=U(T1)).ok, "freelancer: a step")
check(Fr.put(B + f"/api/office/docs/{FD}/items", json={"items": ITEMS}, headers=U(T1)).ok, "freelancer: positions (step)")
r = undo(Fr, "doc", FD, T1)
check(r.ok and r.json()["project_title"] == "Own job" and r.json()["items"] == [], f"freelancer: all back ({r.status_code} {r.text[:200]})")
check(undo(Bo, "doc", FD, T1, "redo").status_code == 404, "bob on the freelancer's document: 404")
r = Fr.post(B + "/api/office/services", json={"name_de": "Schnitt", "daily_rate": 400})
FS = r.json().get("id")
check(Fr.patch(B + f"/api/office/services/{FS}", json={"daily_rate": 450}, headers=U(T2)).ok, "freelancer: the service (step)")
r = undo(Fr, "services", FS, T2)
check(r.ok and Fr.get(B + f"/api/office/services/{FS}").json()["daily_rate"] == 400, f"freelancer: the service as before ({r.status_code})")
r = Fr.post(B + "/api/clients", json={"name": "Private Client", "org_id": None})
FC = r.json().get("id")
check(Fr.patch(B + f"/api/clients/{FC}", json={"name": "Private Client Ltd"}, headers=U(T3)).ok, "freelancer: the client (step)")
check(undo(Bo, "client", FC, T3).status_code == 404, "bob on the freelancer's private client: 404")
r = undo(Fr, "client", FC, T3)
check(r.ok and Fr.get(B + f"/api/clients/{FC}").json()["name"] == "Private Client", f"freelancer: the client as before ({r.status_code})")

print(f"p2111_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
