#!/usr/bin/env python3
"""2.47.3 API tests (part C), own container (start.sh).

 - #1731: properties of several contacts at once (POST /api/contacts/bulk action set): groups added / removed, company,
   department, kind, a note appended (not replaced); the answer's undo sent back (action restore) puts the old values back;
   contacts of a read-only address book are skipped and counted, a foreign id -> 404 (nothing changes); CardDAV / the vCard
   export carries the change; nothing to change -> 400; the token API has set too
 - #1733: several clients at once (POST /api/clients/bulk, /api/v1/clients/bulk): delete (a client used in a framework
   contract is archived instead; only the creator or an admin deletes, the rest is skipped), archive / unarchive, set (rate,
   budget, colour, note appended) and restore; a client of another organisation -> 404 (tenant matrix), a person without an
   organisation works on their own clients
"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def tok(s, scopes):
    r = s.post(B + "/api/me/tokens", json={"name": "t" + str(time.time()), "scopes": scopes})
    assert r.ok, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


if not os.environ.get("KMT_NOSTART"):  # KMT_NOSTART=1: against an app that already runs (a quick local check)
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["contacts"]})
FEAT = "contacts,clients,office,time,collab"
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
me = A.get(B + "/api/state").json()["me"]["id"]
uids = {}
for u in ("bob", "eve"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.org"})
    assert r.ok, r.text
    uids[u] = r.json()["id"]
Bo, Ev = sess("bob"), sess("eve")
for s_ in (Bo, Ev):
    s_.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": me}).json()["id"]
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.org"}).status_code == 200, "Bob joins the organisation")


def cbulk(s, **b):
    return s.post(B + "/api/contacts/bulk", json=b)


def contact(s, cid):
    r = s.get(B + f"/api/contacts/{cid}")
    assert r.ok, r.text
    return r.json()


# ================================================================== #1731: contacts set + restore
BK = A.post(B + "/api/books", json={"name": "Work", "org_id": None}).json()["id"]
cs = []
for i, (grp, note) in enumerate([(["Old", "Keep"], ""), (["old"], "first line"), ([], "x")]):
    r = A.post(B + "/api/contacts", json={"book_id": BK, "fn": f"Test Person {i}", "groups": grp, "note": note, "org": "Before Ltd"})
    assert r.status_code == 201, r.text
    cs.append(r.json()["id"])
r = cbulk(A, action="set", ids=cs, groups_add=["New"], groups_remove=["OLD"], org="Example Corp", dept="Sales", kind="org", note_append="Met at the fair")
j = r.json()
check(r.ok and j["action"] == "set" and j["changed"] == 3 and j["skipped"] == 0 and len(j["undo"]) == 3, f"#1731: set changes three contacts {r.status_code} {r.text[:200]}")
c0, c1, c2 = (contact(A, x) for x in cs)
check(c0["groups"] == ["Keep", "New"] and c1["groups"] == ["New"] and c2["groups"] == ["New"], f"#1731: groups added / removed (case-insensitive) {c0['groups']} {c1['groups']}")
check(all(c["org"] == "Example Corp" and c["dept"] == "Sales" and c["kind"] == "org" for c in (c0, c1, c2)), "#1731: company, department, kind set")
check(c0["note"] == "Met at the fair" and c1["note"] == "first line\n\nMet at the fair", f"#1731: the note is appended, not replaced {c1['note']!r}")
vc = A.get(B + f"/api/books/{BK}/export.vcf").text
check("ORG:Example Corp;Sales" in vc or "ORG:Example Corp" in vc, "#1731: the vCard export (CardDAV) carries the new company")
r = cbulk(A, action="restore", items=j["undo"])
check(r.ok and r.json()["changed"] == 3, f"#1731: restore puts the old values back {r.text[:200]}")
c0, c1 = contact(A, cs[0]), contact(A, cs[1])
check(c0["groups"] == ["Old", "Keep"] and c1["groups"] == ["old"] and c1["note"] == "first line" and c0["org"] == "Before Ltd" and c0["kind"] == "individual",
      f"#1731: undo: groups, note, company, kind as before {c0['groups']} {c1['note']!r}")
r = cbulk(A, action="set", ids=cs)
check(r.status_code == 400, f"#1731: nothing to change -> 400 {r.status_code}")
r = cbulk(A, action="set", ids=cs, org="X", bogus=1)
check(r.status_code == 400, f"#1731: an unknown field -> 400 {r.status_code}")
r = cbulk(A, action="set", ids=cs, kind="group")
check(r.status_code == 400, "#1731: kind only person / company")
# a read-only address book: skipped and counted
check(A.put(B + f"/api/books/{BK}/members", json={"user_id": uids["bob"], "role": "view"}).status_code == 200, "Alice shares the book with Bob (view)")
r = cbulk(Bo, action="set", ids=cs, org="Bob Corp")
check(r.ok and r.json()["changed"] == 0 and r.json()["skipped"] == 3 and contact(A, cs[0])["org"] == "Before Ltd", f"#1731: a read-only book: skipped {r.text[:200]}")
# a foreign id: 404, nothing changes
EB = Ev.post(B + "/api/books", json={"name": "Eve"}).json()["id"]
ec = Ev.post(B + "/api/contacts", json={"book_id": EB, "fn": "Eve Contact"}).json()["id"]
r = cbulk(A, action="set", ids=[cs[0], ec], org="Leak")
check(r.status_code == 404 and contact(A, cs[0])["org"] == "Before Ltd" and contact(Ev, ec)["org"] == "", f"#1731: a foreign id -> 404, nothing changes {r.status_code}")
r = cbulk(A, action="restore", items=[{"id": ec, "org": "Leak"}])
check(r.status_code == 404 and contact(Ev, ec)["org"] == "", "#1731: restore checks every id as well")
# the token API
r = requests.post(B + "/api/v1/contacts/bulk", headers=tok(A, ["read", "contacts"]), json={"action": "set", "ids": cs[:1], "dept": "Ops"})
check(r.ok and contact(A, cs[0])["dept"] == "Ops", f"#1731: /api/v1/contacts/bulk set {r.status_code} {r.text[:160]}")
r = requests.post(B + "/api/v1/contacts/bulk", headers=tok(A, ["read"]), json={"action": "set", "ids": cs[:1], "dept": "No"})
check(r.status_code == 403, "#1731: the token API needs contacts")


# ================================================================== #1733: clients
def clb(s, **b):
    return s.post(B + "/api/clients/bulk", json=b)


def client(s, cid):
    return s.get(B + f"/api/clients/{cid}")


def mk(s, name, **kw):
    r = s.post(B + "/api/clients", json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


C1, C2, C3 = mk(A, "Client One", org_id=ORG, note="old note"), mk(A, "Client Two", org_id=ORG), mk(A, "Client Three", org_id=ORG)
C4 = mk(Bo, "Bob's Client", org_id=ORG)
# set + restore (one undo step)
r = clb(A, action="set", ids=[C1, C2], rate="85,5", budget_h=40, budget_amount=None, color="#336699", note_append="Second line")
j = r.json()
check(r.ok and j["changed"] == 2 and len(j["undo"]) == 2, f"#1733: set changes two clients {r.status_code} {r.text[:200]}")
x1 = client(A, C1).json()
check(x1["rate"] == 85.5 and x1["budget_h"] == 40 and x1["color"] == "#336699" and x1["note"] == "old note\n\nSecond line", f"#1733: rate, budget, colour, note appended {x1['rate']} {x1['note']!r}")
r = clb(A, action="restore", items=j["undo"])
x1 = client(A, C1).json()
check(r.ok and x1["rate"] is None and x1["budget_h"] is None and x1["color"] == "" and x1["note"] == "old note", f"#1733: restore = the old values {r.text[:120]}")
r = clb(A, action="set", ids=[C1], color="red")
check(r.status_code == 400, "#1733: an invalid colour -> 400")
r = clb(A, action="set", ids=[C1])
check(r.status_code == 400, "#1733: nothing to change -> 400")
# archive / unarchive + undo
r = clb(A, action="archive", ids=[C1, C2])
j = r.json()
check(r.ok and j["changed"] == 2 and client(A, C1).json()["archived"], f"#1733: archive {r.text[:160]}")
r = clb(A, action="archive", ids=[C1])
check(r.ok and r.json()["changed"] == 0 and r.json()["unchanged"] == 1, "#1733: archiving an archived one changes nothing")
r = clb(A, action="restore", items=j["undo"])
check(r.ok and not client(A, C1).json()["archived"] and not client(A, C2).json()["archived"], "#1733: undo of archive")
r = clb(A, action="archive", ids=[C3])
r = clb(A, action="unarchive", ids=[C3])
check(r.ok and r.json()["changed"] == 1 and not client(A, C3).json()["archived"], "#1733: unarchive (restore)")
# delete: in use -> archived; not the creator / admin -> skipped
r = A.post(B + "/api/office/contracts", json={"name": "Frame", "client_id": C2})
check(r.status_code in (200, 201), f"a framework contract points to Client Two {r.status_code} {r.text[:160]}")
r = clb(Bo, action="delete", ids=[C1, C4])
j = r.json()
check(r.ok and j["deleted"] == 1 and j["skipped"] == 1 and client(A, C4).status_code == 404 and client(A, C1).ok, f"#1733: Bob deletes only his own client {r.text[:200]}")
r = clb(A, action="delete", ids=[C2, C3])
j = r.json()
check(r.ok and j["deleted"] == 1 and j["archived"] == 1 and client(A, C2).json()["archived"] and client(A, C3).status_code == 404,
      f"#1733: a client in use is archived instead of deleted {r.text[:200]}")
ct = [x for x in A.get(B + "/api/office/contracts").json().get("items", []) if x["name"] == "Frame"]
check(ct and ct[0]["client_id"] == C2, "#1733: the contract keeps its client")
r = clb(A, action="restore", items=j["undo"])
check(r.ok and not client(A, C2).json()["archived"], "#1733: undo of the archive part of a delete")
# the organisation boundary (tenant matrix) and a person without an organisation
r = clb(Ev, action="archive", ids=[C1])
check(r.status_code == 404 and not client(A, C1).json()["archived"], "tenant-matrix: client -- another person cannot change a client of the organisation in bulk (404)")
r = clb(Ev, action="restore", items=[{"id": C1, "archived": True}])
check(r.status_code == 404 and not client(A, C1).json()["archived"], "tenant-matrix: client -- nor restore it (404)")
E1 = mk(Ev, "Eve's Own")  # a person without an organisation: their own clients
r = clb(Ev, action="set", ids=[E1], rate=50)
check(r.ok and client(Ev, E1).json()["rate"] == 50 and client(A, E1).status_code == 404, f"#1733: without an organisation: one's own clients {r.text[:120]}")
r = clb(Ev, action="delete", ids=[E1])
check(r.ok and r.json()["deleted"] == 1, "#1733: without an organisation: delete one's own")
r = clb(A, action="archive", ids=list(range(1, 1003)))
check(r.status_code == 400, "#1733: at most 1000 clients at once")
r = clb(A, action="bogus", ids=[C1])
check(r.status_code == 400, "#1733: an unknown action -> 400")
# the token API
r = requests.post(B + "/api/v1/clients/bulk", headers=tok(A, ["read", "structure"]), json={"action": "archive", "ids": [C1]})
check(r.ok and client(A, C1).json()["archived"], f"#1733: /api/v1/clients/bulk {r.status_code} {r.text[:160]}")
r = requests.post(B + "/api/v1/clients/bulk", headers=tok(A, ["read"]), json={"action": "unarchive", "ids": [C1]})
check(r.status_code == 403 and client(A, C1).json()["archived"], f"#1733: the token API needs structure {r.status_code}")

print(f"p2473_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
time.sleep(0.1)
sys.exit(1 if FAILS else 0)
