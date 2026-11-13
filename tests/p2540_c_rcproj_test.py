#!/usr/bin/env python3
# kalmido-suite:
"""2.540.0 API test, part C (#4471): the projects a receipt can go to (GET /api/docs/<id>/receipt "projects" + "recent")
are the same set as the office's quotations and invoices (static/js/office_docproject.js dpj_lists):
 - private receipt of a person without an organisation (freelancer-matrix: files): only her own lists; a private list of
   another person shared with her that carries the same name as her own is not offered (the double name of the bug)
 - no inbox, archived, health, budget or locked lists
 - recent: the projects she last chose at receipts of this area, newest first, at most 5, only ones of the set
 - organisation receipt: the organisation's lists only, no private list of the person
Invented names only, generated file contents.
usage: p2540_c_rcproj_test.py <datadir>"""
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def tiny_pdf(text):
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def upload(s, name, text, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf(text), "application/pdf")})
    assert r.ok, r.text
    j = r.json()
    return (j.get("ids") or [x["id"] for x in j.get("docs") or j.get("items") or []])[0]


def project(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, "kind": "project", "org_id": org})
    assert r.ok, r.text
    return r.json()["id"]


def share(lid, uid):
    dbx("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,'edit','2026-01-01T00:00:00+00:00') ON CONFLICT DO NOTHING", (lid, uid), write=True)


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
FID, Fr = freelancer(B, A)
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ---- the freelancer's private receipt (freelancer-matrix: files)
OWN = project(Fr, "Errands")
FAIR = project(Fr, "Trade fair")
SHOOT = project(Fr, "Shoot")
FOREIGN = project(Bo, "Errands")           # bob's private list of the same name, shared with her
share(FOREIGN, FID)
OTHER = project(Bo, "Bob shared")          # another private list of bob's, shared with her
share(OTHER, FID)
HEALTH, BUDGET, LOCKED, ARCH = (project(Fr, n) for n in ("Health notes", "Budget plan", "Locked diary", "Old project"))
dbx("UPDATE lists SET life='health' WHERE id=?", (HEALTH,), write=True)
dbx("UPDATE lists SET life='budget' WHERE id=?", (BUDGET,), write=True)
dbx("UPDATE lists SET e2e='x' WHERE id=?", (LOCKED,), write=True)
dbx("UPDATE lists SET archived=true WHERE id=?", (ARCH,), write=True)
INBOX = [x[0] for x in dbx("SELECT id FROM lists WHERE owner_id=? AND is_inbox", (FID,))]

D1, D2, D3, D4 = (upload(Fr, f"receipt-{i}.pdf", f"Receipt {i} total 10.00 EUR") for i in range(1, 5))
r = Fr.get(B + f"/api/docs/{D1}/receipt")
check(r.ok, f"the freelancer reads her receipt ({r.status_code} {r.text[:200]})")
j = r.json() if r.ok else {}
ids = [p["id"] for p in j.get("projects", [])]
check(OWN in ids and FAIR in ids and SHOOT in ids, f"her own lists are offered {j.get('projects')}")
check(FOREIGN not in ids and OTHER not in ids, f"#4471: no private list of another person, even shared with her {j.get('projects')}")
check([p["name"] for p in j.get("projects", [])].count("Errands") == 1, "#4471: the name Errands only once")
check(not {HEALTH, BUDGET, LOCKED, ARCH, *INBOX} & set(ids), f"no health, budget, locked, archived or inbox list {j.get('projects')}")
check(j.get("recent") == [], f"nothing chosen yet: no recent projects ({j.get('recent')})")

# recent: newest first, only projects of the set (a foreign list set before the change is no recent one)
for d, lid, at in ((D1, FAIR, "2026-11-01T10:00:00+00:00"), (D2, SHOOT, "2026-11-02T10:00:00+00:00"), (D3, FAIR, "2026-11-03T10:00:00+00:00")):
    r = Fr.put(B + f"/api/docs/{d}/receipt", json={"project_id": lid, "category": "Material"})
    check(r.ok, f"setup: project set at receipt {d} ({r.status_code} {r.text[:200]})")
    dbx("UPDATE rc_receipts SET set_at=? WHERE node_id=?", (at, d), write=True)
dbx("INSERT INTO rc_receipts(node_id, org_id, ws, list_id, category, set_by, set_at) VALUES(?, NULL, 'private', ?, '', ?, ?)",
    (D4, FOREIGN, FID, "2026-11-04T10:00:00+00:00"), write=True)
j = Fr.get(B + f"/api/docs/{D1}/receipt").json()
check(j.get("recent") == [FAIR, SHOOT], f"recent: newest first, once each, no foreign list ({j.get('recent')} want {[FAIR, SHOOT]})")
more = [project(Fr, f"Extra {i}") for i in range(1, 7)]
for i, lid in enumerate(more):
    d = upload(Fr, f"extra-{i}.pdf", f"Extra receipt {i}")
    Fr.put(B + f"/api/docs/{d}/receipt", json={"project_id": lid, "category": "Material"})
    dbx("UPDATE rc_receipts SET set_at=? WHERE node_id=?", (f"2026-11-05T10:0{i}:00+00:00", d), write=True)
j = Fr.get(B + f"/api/docs/{D1}/receipt").json()
check(j.get("recent") == more[::-1][:5], f"at most 5 recent projects ({j.get('recent')})")
check(Bo.get(B + f"/api/docs/{D1}/receipt").status_code in (403, 404), "bob does not read her receipt")

# ---- an organisation's receipt: the organisation's lists only
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
f = Bo.get(B + "/api/state").json()["settings"].get("features") or ""
if "docs" not in f.split(","):
    Bo.patch(B + "/api/settings", json={"features": f + ",docs"})
OL = project(Bo, "Alpha campaign", ORG)
OD = upload(Bo, "org-invoice.pdf", "Organisation invoice", ws=f"org:{ORG}")
r = Bo.get(B + f"/api/docs/{OD}/receipt")
check(r.ok, f"bob reads the organisation's receipt ({r.status_code} {r.text[:200]})")
ids = [p["id"] for p in (r.json() if r.ok else {}).get("projects", [])]
check(OL in ids and FOREIGN not in ids and OTHER not in ids, f"organisation receipt: the organisation's lists only {ids}")
check((r.json() if r.ok else {}).get("recent") == [], "organisation receipt: no recent projects of the private area")

print(f"p2540_c_rcproj: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
