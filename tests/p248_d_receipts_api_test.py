#!/usr/bin/env python3
"""2.48.0 API tests, part D (#1356): agents suggest project and category of a receipt (a document), a person confirms.
Invented names only, generated file contents.
 - an agent the document is shared with suggests (v1 + its own list of suggestions); the document goes to To review
 - a person accepts (also changed) -> the assignment is set; reject; reopen = the undo of both
 - the agent can never set it: no v1 field, the app routes refuse agents; without a share 404; a project it cannot see,
   of another workspace or outside its list restriction is refused
 - organisation boundary: an organisation's agent never reaches a private project; a person without an organisation
 - rollback: only new tables
usage: p248_d_receipts_api_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


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


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
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


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
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


def agent(owner, org=None, name="bot"):
    r = A.post(B + "/api/admin/agents", json={"username": name, "display_name": name.title()})
    assert r.status_code == 201, r.text
    aid, t = r.json()["id"], r.json().get("token") or ""
    dbx("DELETE FROM org_members WHERE user_id=?", (aid,), write=True)
    dbx("UPDATE agents SET org_id=?, owner_id=? WHERE user_id=?", (org, owner, aid), write=True)
    if org:
        dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (org, aid), write=True)
    return aid, tok(t)


def project(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, "kind": "project", "org_id": org})
    assert r.ok, r.text
    return r.json()["id"]


def member(lid, uid):
    dbx("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,'edit','2026-01-01T00:00:00+00:00') ON CONFLICT DO NOTHING", (lid, uid), write=True)


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, ERIN = ids["bob"], ids["carol"], ids["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok, "setup: carol joins Alpha")
dbx("DELETE FROM org_members WHERE org_id=? AND user_id NOT IN (?,?)", (ORG, BOB, CAROL), write=True)
dbx("DELETE FROM org_members WHERE user_id IN (1, ?)", (ERIN,), write=True)
PAG, PAGS = agent(1, None, "alicebot")
OAG, OAGS = agent(BOB, ORG, "alphabot")
EAG, EAGS = agent(ERIN, None, "erinbot")
for s in (A, Bo):
    s.post(B + "/api/auth/logout")
A, Bo, Ca, Er = sess("alice"), sess("bob"), sess("carol"), sess("erin")
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    f = s.get(B + "/api/state").json()["settings"].get("features") or ""
    if "docs" not in f.split(","):
        s.patch(B + "/api/settings", json={"features": f + ",docs"})

# ---- rollback: only new tables
cols = {r[0] for r in dbx("SELECT table_name FROM information_schema.columns WHERE table_name IN ('rc_receipts', 'rc_suggest')")}
check(cols == {"rc_receipts", "rc_suggest"}, f"two new tables ({sorted(cols)})")

# ---- alice (private), her agent, her projects
D1 = upload(A, "invoice-hotel.pdf", "Hotel invoice total 120.00 EUR")
D2 = upload(A, "invoice-other.pdf", "Another invoice")
P1 = project(A, "Trade fair")
P2 = project(A, "Secret project")       # not shared with the agent
member(P1, PAG)
r = A.post(B + f"/api/files/nodes/{D1}/shares", json={"agent_id": PAG, "role": "view"})
check(r.ok, f"setup: D1 shared with the agent ({r.status_code} {r.text[:200]})")

r = PAGS.post(V + f"/documents/{D2}/receipt-suggestion", json={"project_id": P1, "category": "Travel"})
check(r.status_code == 404, f"no share: 404 ({r.status_code})")
r = PAGS.post(V + f"/documents/{D1}/receipt-suggestion", json={"project_id": P2, "category": "Travel"})
check(r.status_code == 400, f"a project the agent cannot see: refused ({r.status_code} {r.text[:200]})")
r = PAGS.post(V + f"/documents/{D1}/receipt-suggestion", json={})
check(r.status_code == 400, "nothing to suggest: refused")
r = PAGS.post(V + f"/documents/{D1}/receipt-suggestion", json={"project_id": P1, "status": "accepted"})
check(r.status_code == 400, "unknown field refused")
r = PAGS.post(V + f"/documents/{D1}/receipt-suggestion", json={"project_id": P1, "category": "Travel", "note": "Hotel of the fair"})
check(r.status_code == 201 and r.json()["state"] == "open" and r.json()["project"]["id"] == P1, f"the agent suggests ({r.status_code} {r.text[:200]})")
SID = r.json().get("id")
check(r.json().get("note") == "Hotel of the fair", "the note comes back")
r = PAGS.post(V + f"/documents/{D1}/receipt-suggestion", json={"project_id": P1, "category": "Travel costs"})
check(r.status_code == 201 and r.json()["id"] != SID, "a new suggestion replaces the agent's open one")
SID = r.json()["id"]
check(dbx("SELECT COUNT(*) FROM rc_suggest WHERE node_id=? AND state='open'", (D1,))[0][0] == 1, "only one open suggestion per agent")
j = PAGS.get(V + "/receipt-suggestions").json()
check([x["id"] for x in j.get("data", [])] == [SID], f"the agent reads its open suggestions ({j})")

# the agent cannot set anything itself
r = PAGS.patch(V + f"/documents/{D1}", json={"project_id": P1})
check(r.status_code in (400, 403), f"v1 PATCH knows no project ({r.status_code})")
for m, path, body in (("PUT", f"/api/docs/{D1}/receipt", {"project_id": P1}), ("POST", f"/api/receipt-suggestions/{SID}/accept", {}),
                      ("GET", f"/api/docs/{D1}/receipt", None)):
    r = PAGS.request(m, B + path, json=body)
    check(r.status_code in (401, 403, 404), f"agent on the app route {m} {path}: refused ({r.status_code})")
check(not dbx("SELECT 1 FROM rc_receipts"), "nothing set by the agent")
r = A.post(V + f"/documents/{D1}/receipt-suggestion", json={"project_id": P1})
check(r.status_code in (401, 403), "a person's session is no agent")

# the person decides
d = A.get(B + f"/api/docs/{D1}").json()
check(d.get("review") is True, "the document waits in To review")
j = A.get(B + f"/api/docs/{D1}/receipt").json()
check(j["receipt"]["project"] is None and [s["id"] for s in j["suggestions"]] == [SID] and j["suggestions"][0]["agent"]["name"] == "Alicebot",
      f"the person sees the suggestion ({j})")
check({p["id"] for p in j["projects"]} >= {P1, P2}, "the person's projects are offered")
r = A.post(B + f"/api/receipt-suggestions/{SID}/accept", json={})
j = r.json()
check(r.ok and j["receipt"]["project"]["id"] == P1 and j["receipt"]["category"] == "Travel costs" and not j["suggestions"],
      f"accepted: project + category set ({r.status_code} {r.text[:300]})")
check(j["categories"] == ["Travel costs"], f"the category is offered from now on ({j['categories']})")
check(PAGS.get(V + "/receipt-suggestions?state=accepted").json()["data"][0]["id"] == SID, "the agent sees that it was accepted")
r = A.post(B + f"/api/receipt-suggestions/{SID}/accept", json={})
check(r.status_code == 409, "decided once")
r = A.post(B + f"/api/receipt-suggestions/{SID}/reopen")
check(r.ok and r.json()["receipt"]["project"] is None and len(r.json()["suggestions"]) == 1, "undo: the assignment before + the open suggestion")
r = A.post(B + f"/api/receipt-suggestions/{SID}/accept", json={"project_id": P2, "category": "Fair"})
check(r.ok and r.json()["receipt"]["project"]["id"] == P2 and r.json()["receipt"]["category"] == "Fair", "accepted with changed values")
r = PAGS.post(V + f"/documents/{D1}/receipt-suggestion", json={"category": "Lodging"})
S2 = r.json()["id"]
r = A.post(B + f"/api/receipt-suggestions/{S2}/reject")
check(r.ok and r.json()["receipt"]["category"] == "Fair" and not r.json()["suggestions"], "rejected: the assignment stays")
check(A.post(B + f"/api/receipt-suggestions/{S2}/reopen").ok and dbx("SELECT state FROM rc_suggest WHERE id=?", (S2,))[0][0] == "open",
      "undo of a reject")
r = A.put(B + f"/api/docs/{D1}/receipt", json={"project_id": None, "category": ""})
check(r.ok and r.json()["receipt"]["project"] is None, "a person clears it directly")

# ---- event document_added: a new document in a folder shared with the agent (after its first recognition)
ROOT = A.get(B + "/api/docs/settings?ws=private").json().get("root_id")
check(ROOT and A.post(B + f"/api/files/nodes/{ROOT}/shares", json={"agent_id": PAG, "role": "view"}).ok, "setup: the documents folder shared")


def ev_added(nid):
    evs = PAGS.get(V + "/agent/events").json().get("data") or []
    return [e for e in evs if e.get("event") == "document_added" and (e.get("data") or {}).get("document", {}).get("id") == nid]


D3 = upload(A, "invoice-train.pdf", "Train ticket 49.00 EUR")
for _ in range(120):
    if ev_added(D3):
        break
    time.sleep(0.5)
ev = ev_added(D3)
check(len(ev) == 1 and ev[0]["data"]["document"]["url"] == f"/api/v1/documents/{D3}", f"document_added once for the new document ({ev})")
check(not EAGS.get(V + "/agent/events").json().get("data") or not any(e.get("event") == "document_added" for e in EAGS.get(V + "/agent/events").json().get("data")),
      "an agent without a share hears nothing")
r = A.post(B + f"/api/docs/{D3}/redo")
time.sleep(4)
check(len(ev_added(D3)) == 1, "Recognise again sends no second event")

# ---- organisation: its agent, its project; never a private one
OD = upload(Bo, "org-invoice.pdf", "Organisation invoice", ws=f"org:{ORG}")
OP = project(Bo, "Alpha campaign", ORG)
member(OP, OAG)
check(Bo.post(B + f"/api/files/nodes/{OD}/shares", json={"agent_id": OAG, "role": "view"}).ok, "setup: org document shared with the org agent")
BP = project(Bo, "Bob private")
member(BP, OAG)
r = OAGS.post(V + f"/documents/{OD}/receipt-suggestion", json={"project_id": BP})
check(dbx("SELECT org_id FROM lists WHERE id=?", (BP,))[0][0] is None and r.status_code == 400, f"a private project for an organisation's document: refused ({r.status_code})")
r = OAGS.post(V + f"/documents/{OD}/receipt-suggestion", json={"project_id": P1})
check(r.status_code == 400, "a project of another workspace: refused")
dbx("UPDATE agents SET list_ids=? WHERE user_id=?", (str(BP), OAG), write=True)
r = OAGS.post(V + f"/documents/{OD}/receipt-suggestion", json={"project_id": OP})
check(r.status_code == 400, f"outside the agent's list restriction: refused ({r.status_code})")
dbx("UPDATE agents SET list_ids='' WHERE user_id=?", (OAG,), write=True)
r = OAGS.post(V + f"/documents/{OD}/receipt-suggestion", json={"project_id": OP, "category": "Marketing"})
check(r.status_code == 201, f"the org agent suggests the org project ({r.status_code} {r.text[:200]})")
OS = r.json().get("id")
# tenant-matrix: receipt
check(Ca.get(B + f"/api/docs/{OD}/receipt").status_code == 404, "carol (document not shared with her) does not see it")
check(A.post(B + f"/api/receipt-suggestions/{OS}/accept", json={}).status_code == 404, "alice (outside the organisation): 404")
check(PAGS.get(V + "/receipt-suggestions?state=all").json()["data"] and all(x["document_id"] == D1 for x in PAGS.get(V + "/receipt-suggestions?state=all").json()["data"]),
      "an agent only lists its own suggestions")
r = Bo.post(B + f"/api/receipt-suggestions/{OS}/accept", json={})
check(r.ok and r.json()["receipt"]["project"]["id"] == OP, "the organisation's admin accepts")

# ---- a person without an organisation
ED = upload(Er, "freelance-receipt.pdf", "Train ticket")
EP = project(Er, "Client job")
member(EP, EAG)
check(Er.post(B + f"/api/files/nodes/{ED}/shares", json={"agent_id": EAG, "role": "view"}).ok, "setup: erin shares with her agent")
r = EAGS.post(V + f"/documents/{ED}/receipt-suggestion", json={"project_id": EP, "category": "Travel"})
check(r.status_code == 201, f"freelancer: her agent suggests ({r.status_code} {r.text[:200]})")
r = Er.post(B + f"/api/receipt-suggestions/{r.json().get('id')}/accept", json={})
check(r.ok and r.json()["receipt"]["project"]["id"] == EP, "freelancer: she accepts")
check(EAGS.post(V + f"/documents/{D1}/receipt-suggestion", json={"category": "x"}).status_code == 404, "erin's agent never reaches alice's documents")

# ---- OpenAPI
spec = A.get(B + "/api/v1/openapi.json").json()
check(spec["paths"].get("/documents/{id}/receipt-suggestion", {}).get("post", {}).get("x-kalmido-scope") == "files:read", "OpenAPI: suggestion route + scope")
check("/receipt-suggestions" in spec["paths"], "OpenAPI: list route")

print(f"p248_d_receipts_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
