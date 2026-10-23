#!/usr/bin/env python3
"""2.121.0 API tests, part C: agents suggest amount / currency / VAT rate of a receipt (#2096) and receipts are billed on to a
client as outlays (#2094). Own container (start.sh, org encryption on). Invented companies, people and figures only.
tenant-matrix: office
freelancer-matrix: office
 - #2096: an agent the document is shared with suggests amount (comma or dot, > 0, two decimals at most), currency, VAT rate
   (at least one of project / category / amount / VAT rate); invalid values 400; a document not shared 404; a person accepts
   (with changed values) and the document has the amount + the receipt the VAT rate; reopen brings the old values back; an
   amount-only suggestion leaves project / category alone; an agent sets nothing directly; a person without organisation
 - #2094: receipts of the office billed on to a draft quotation (net with a VAT rate, gross without / as a small business),
   markup, one position for all, never twice (409), unbill = undo, the list of billed receipts; a member without the office
   admin role 403, another organisation 404, a receipt in the trash 404; a person without organisation (personal office)
usage: p2121_c_api_test.py <datadir>      (P2121C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
D = O + "/docs"
RB = O + "/receipts"


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t, "X-Requested-With": "kalmido"})
    return s


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
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


def upload(s, name, text, ws):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf(text), "application/pdf")})
    assert r.ok, r.text
    j = r.json()
    nid = (j.get("ids") or [x["id"] for x in j.get("docs") or j.get("items") or []])[0]
    for _ in range(60):  # the recognition must be over, else it may overwrite what the test sets
        if s.get(B + f"/api/docs/{nid}").json().get("state") not in ("wait", "run"):
            break
        time.sleep(0.5)
    return nid


def receipt(s, name, ws, amount, vat, cat, day="2026-03-05"):
    """A document of the documents space with amount, date, category and VAT rate = a receipt of the office."""
    nid = upload(s, name, "Receipt " + name, ws)
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day, "currency": "EUR"})
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"project_id": None, "category": cat, "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def new_agent(admin, owner, org, name):
    r = admin.post(B + "/api/admin/agents", json={"username": name, "display_name": name.title()})
    assert r.status_code == 201, r.text
    aid, t = r.json()["id"], r.json().get("token") or ""
    sql("DELETE FROM org_members WHERE user_id=?", (aid,), write=True)
    sql("UPDATE agents SET org_id=?, owner_id=? WHERE user_id=?", (org, owner, aid), write=True)
    if org:
        sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (org, aid), write=True)
    return aid, tok(t)


if os.environ.get("P2121C_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
WS = f"org:{ORG}"
A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Beispiel Studio GmbH", "street": "Musterweg 1",
                                                                                   "zip": "12345", "city": "Musterstadt", "country": "DE"}})
Ca.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Fremd GmbH", "street": "Weg 2", "zip": "12345", "city": "Stadt", "country": "DE"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH"}).json()["id"]

# ================================================================ #2096 agents suggest amount and VAT rate
OAG, OAGS = new_agent(A, ALICE, ORG, "alphabot")
cols = {r[0] for r in sql("SELECT column_name FROM information_schema.columns WHERE table_name='rc_suggest'")}
check({"amount", "currency", "vat_pct", "prev_amount", "prev_currency", "prev_vat_pct"} <= cols, "#2096: new columns of rc_suggest")
DA = upload(A, "invoice-fair.pdf", "Fair invoice", WS)
DB = upload(A, "invoice-other.pdf", "Another invoice", WS)
check(A.post(B + f"/api/files/nodes/{DA}/shares", json={"agent_id": OAG, "role": "view"}).ok, "setup: DA shared with the agent")
SG = V + f"/documents/{DA}/receipt-suggestion"
check(OAGS.post(V + f"/documents/{DB}/receipt-suggestion", json={"amount": "10.00"}).status_code == 404, "#2096: not shared: 404")
for bad, why in (({"amount": "abc"}, "text"), ({"amount": "-5"}, "negative"), ({"amount": "0"}, "zero"), ({"amount": "1.234"}, "three decimals"),
                 ({"amount": 100000001}, "too big"), ({"amount": True}, "bool"), ({"amount": "10", "currency": "EURO"}, "currency"),
                 ({"vat_pct": "20"}, "VAT rate"), ({"note": "only a note"}, "nothing to suggest"), ({"currency": "EUR"}, "currency alone")):
    r = OAGS.post(SG, json=bad)
    check(r.status_code == 400, f"#2096: invalid {why} refused ({r.status_code} {r.text[:120]})")
check(OAGS.post(SG, json={"amount": "10", "shoe_size": 3}).status_code == 400, "#2096: unknown field refused")
r = OAGS.post(SG, json={"amount": "119,00", "currency": "eur", "vat_pct": "19", "note": "Total of the fair invoice"})
j = r.json()
check(r.status_code == 201 and j["amount"] == "119.00" and j["currency"] == "EUR" and j["vat_pct"] == "19" and j["category"] is None and j["project"] is None,
      f"#2096: the agent suggests amount + VAT rate ({r.status_code} {r.text[:200]})")
SID = j["id"]
r = OAGS.post(SG, json={"amount": 12.5})
check(r.status_code == 201 and r.json()["amount"] == "12.50" and r.json()["vat_pct"] is None, "#2096: a number works, a new suggestion replaces the open one")
SID = r.json()["id"]
check(sql("SELECT COUNT(*) FROM rc_suggest WHERE node_id=? AND state='open'", (DA,))[0][0] == 1, "#2096: one open suggestion per agent")
r = OAGS.post(SG, json={"amount": "119.00", "currency": "EUR", "vat_pct": "19"})
SID = r.json()["id"]
check(OAGS.get(V + "/receipt-suggestions").json()["data"][0]["amount"] == "119.00", "#2096: the agent reads it back with the amount")
# the agent sets nothing
for m, path, body in (("PUT", f"/api/docs/{DA}/receipt", {"vat_pct": "7"}), ("POST", f"/api/receipt-suggestions/{SID}/accept", {"amount": "1.00"})):
    r = OAGS.request(m, B + path, json=body)
    check(r.status_code in (401, 403, 404), f"#2096: the agent cannot {m} {path} ({r.status_code})")
check(not A.get(B + f"/api/docs/{DA}").json().get("amount"), "#2096: nothing set by the agent")
# the person sees it and accepts with a changed VAT rate
j = A.get(B + f"/api/docs/{DA}/receipt").json()
s0_ = j["suggestions"][0]
check(s0_["amount"] == "119.00" and s0_["currency"] == "EUR" and s0_["vat_pct"] == "19", f"#2096: the person sees amount / VAT rate ({s0_})")
A.patch(B + f"/api/docs/{DA}", json={"amount": "50.00", "currency": "USD"})
A.put(B + f"/api/docs/{DA}/receipt", json={"project_id": None, "category": "Old", "vat_pct": "7"})
r = A.post(B + f"/api/receipt-suggestions/{SID}/accept", json={"amount": "120.00", "vat_pct": "0"})
d = A.get(B + f"/api/docs/{DA}").json()
check(r.ok and d["amount"] == "120.00" and d["currency"] == "EUR" and r.json()["receipt"]["vat_pct"] == "0", f"#2096: accepted with changed values ({r.text[:200]})")
check(r.json()["receipt"]["category"] == "Old", "#2096: an amount-only suggestion leaves the category alone")
r = A.post(B + f"/api/receipt-suggestions/{SID}/reopen")
d = A.get(B + f"/api/docs/{DA}").json()
check(r.ok and d["amount"] == "50.00" and d["currency"] == "USD" and r.json()["receipt"]["vat_pct"] == "7" and len(r.json()["suggestions"]) == 1,
      f"#2096: reopen brings the old amount, currency and VAT rate back ({d.get('amount')} {d.get('currency')} {r.text[:160]})")
r = A.post(B + f"/api/receipt-suggestions/{SID}/accept", json={})
d = A.get(B + f"/api/docs/{DA}").json()
check(r.ok and d["amount"] == "119.00" and d["currency"] == "EUR" and r.json()["receipt"]["vat_pct"] == "19", "#2096: accepted as suggested")
check(A.post(B + f"/api/receipt-suggestions/{SID}/accept", json={}).status_code == 409, "#2096: decided once")
# 2.121.0 review M2: an amount-only accept / its reopen keep a receipt that is one only by "keep" (no project, category, rate)
A.put(B + f"/api/docs/{DA}/receipt", json={"project_id": None, "category": "", "vat_pct": None, "keep": True})
r = OAGS.post(V + f"/documents/{DA}/receipt-suggestion", json={"amount": "33.00"})
S3 = r.json()["id"]
r = A.post(B + f"/api/receipt-suggestions/{S3}/accept", json={})
check(r.ok and r.json()["receipt"]["is_receipt"], f"review M2: an amount-only accept keeps the receipt row ({r.text[:160]})")
r = A.post(B + f"/api/receipt-suggestions/{S3}/reopen")
check(r.ok and r.json()["receipt"]["is_receipt"], f"review M2: its reopen keeps the receipt row ({r.text[:160]})")
A.post(B + f"/api/receipt-suggestions/{S3}/reject")
# a document without amount / receipt row before: reopen leaves none
r = OAGS.post(V + f"/documents/{DB}/receipt-suggestion", json={"amount": "5.00", "vat_pct": "7"})
check(r.status_code == 404, "#2096: DB is not shared")
A.post(B + f"/api/files/nodes/{DB}/shares", json={"agent_id": OAG, "role": "view"})
S2 = OAGS.post(V + f"/documents/{DB}/receipt-suggestion", json={"amount": "5.00", "vat_pct": "7"}).json()["id"]
check(A.post(B + f"/api/receipt-suggestions/{S2}/accept", json={}).ok and A.get(B + f"/api/docs/{DB}").json()["amount"] == "5.00", "#2096: accepted on a fresh document")
r = A.post(B + f"/api/receipt-suggestions/{S2}/reopen")
check(r.ok and not A.get(B + f"/api/docs/{DB}").json().get("amount") and r.json()["receipt"]["vat_pct"] is None and not r.json()["receipt"]["is_receipt"],
      "#2096: reopen of a fresh document: no amount, no VAT rate, no receipt row again")
r = A.post(B + f"/api/receipt-suggestions/{S2}/accept", json={"amount": "abc"})
check(r.status_code == 400, "#2096: a person's invalid amount at accept is refused")
check(Bo.get(B + f"/api/docs/{DA}/receipt").status_code in (403, 404), "#2096: a member without a share does not see it")
check(Ca.post(B + f"/api/receipt-suggestions/{S2}/accept", json={}).status_code == 404, "#2096: another organisation: 404")
spec = A.get(B + "/api/v1/openapi.json").json()
check("amount" in spec["components"]["schemas"]["ReceiptSuggestion"]["properties"], "#2096: OpenAPI schema carries the amount")

# ================================================================ #2094 receipts billed on to a client
R1 = receipt(A, "Baumarkt.pdf", WS, "119.00", "19", "Material")
R2 = receipt(A, "Taxi.pdf", WS, "50.00", None, "Travel", "2026-03-06")
R3 = receipt(A, "Buch.pdf", WS, "107.00", "7", "Books", "2026-03-07")
Q = A.post(B + D, json={"project_title": "Film eins", "client_id": CL}).json()
docs = A.get(B + O + f"/trips/bill-docs?client_id={CL}").json()["docs"]
check(docs and docs[0]["id"] == Q["id"], "#2094: the draft quotation is offered")
check(A.get(B + RB + f"/billed?ids={R1},{R2}").json()["billed"] == {}, "#2094: nothing billed yet")
r = A.post(B + RB + "/bill", json={"doc_id": Q["id"], "node_ids": [R1, R2], "markup_pct": 10})
check(r.ok and len(r.json()["positions"]) == 2 and sorted(r.json()["items"]) == sorted([R1, R2]), "#2094: billed on " + r.text[:200])
BJ = r.json()
its = [(i["title"], i["rate"], i.get("cost"), i["intext"], i["unit"]) for i in A.get(B + f"{D}/{Q['id']}").json()["items"]]
check(its == [("Material: Baumarkt", 110.0, 100.0, "extern", "flat"), ("Travel: Taxi", 55.0, 50.0, "extern", "flat")],
      f"#2094: net with a VAT rate (119 -> 100), gross without (50), rate + 10 % {its}")
bj = A.get(B + RB + f"/billed?ids={R1},{R2},{R3}").json()["billed"]
check(set(bj) == {str(R1), str(R2)} and bj[str(R1)]["doc_id"] == Q["id"], f"#2094: the receipts show where they were billed {bj}")
check(A.post(B + RB + "/bill", json={"doc_id": Q["id"], "node_ids": [R2, R3]}).status_code == 409, "#2094: a receipt is never billed twice")
check(len(A.get(B + f"{D}/{Q['id']}").json()["items"]) == 2, "#2094: the refused billing added nothing")
r = A.post(B + RB + "/unbill", json={"node_ids": BJ["items"], "positions": BJ["positions"]})
check(r.ok and r.json()["removed"] == 2 and A.get(B + f"{D}/{Q['id']}").json()["items"] == []
      and A.get(B + RB + f"/billed?ids={R1},{R2}").json()["billed"] == {}, "#2094: unbill takes positions and marks back")
r = A.post(B + RB + "/bill", json={"doc_id": Q["id"], "node_ids": [R1, R3], "one": 1})
it = A.get(B + f"{D}/{Q['id']}").json()["items"]
check(r.ok and len(it) == 1 and it[0]["cost"] == 200.0, f"#2094: one position for all (net 100 + 100) {it}")
A.post(B + RB + "/unbill", json={"node_ids": [R1, R3], "positions": r.json()["positions"]})
A.put(B + O + "/settings", json={"small_business": 1})
r = A.post(B + RB + "/bill", json={"doc_id": Q["id"], "node_ids": [R1]})
it = A.get(B + f"{D}/{Q['id']}").json()["items"]
check(r.ok and it[0]["cost"] == 119.0, f"#2094: a small business bills gross {it}")
A.post(B + RB + "/unbill", json={"node_ids": [R1], "positions": r.json()["positions"]})
A.put(B + O + "/settings", json={"small_business": 0})
check(A.post(B + RB + "/bill", json={"doc_id": 999999, "node_ids": [R1]}).status_code == 404, "#2094: an unknown document 404")
for bad in ({"doc_id": Q["id"], "node_ids": []}, {"doc_id": Q["id"], "node_ids": ["x"]}, {"doc_id": Q["id"], "node_ids": [R1], "markup_pct": -1},
            {"doc_id": Q["id"]}):
    check(A.post(B + RB + "/bill", json=bad).status_code == 400, f"#2094: invalid input refused {bad}")
check(A.post(B + RB + "/bill", json={"doc_id": Q["id"], "node_ids": [R1, DA + 9999]}).status_code == 404, "#2094: an unknown receipt 404")
# a document that is no receipt (no rc_receipts row / no amount)
NR = upload(A, "plain.pdf", "No receipt", WS)
check(A.post(B + RB + "/bill", json={"doc_id": Q["id"], "node_ids": [NR]}).status_code == 404, "#2094: a document without receipt row is no receipt")
# rights
check(Bo.post(B + RB + "/bill", json={"doc_id": Q["id"], "node_ids": [R1]}).status_code == 403, "#2094: a member without the office admin role: 403")
check(Bo.get(B + RB + f"/billed?ids={R1}").status_code == 403 and Bo.post(B + RB + "/unbill", json={"node_ids": [R1]}).status_code == 403, "#2094: 403 on the other routes")
CQ = Ca.post(B + D, json={"project_title": "Fremdfilm"}).json()
check(Ca.post(B + RB + "/bill", json={"doc_id": Q["id"], "node_ids": [R1]}).status_code == 404, "#2094: another organisation cannot use our document")
check(Ca.post(B + RB + "/bill", json={"doc_id": CQ["id"], "node_ids": [R1]}).status_code == 404, "#2094: another organisation cannot bill our receipt")
check(Ca.get(B + RB + f"/billed?ids={R1}").json()["billed"] == {}, "#2094: another organisation sees nothing of ours")
# trash
check(A.delete(B + f"/api/files/nodes/{R3}").ok, "setup: R3 into the trash")
check(A.post(B + RB + "/bill", json={"doc_id": Q["id"], "node_ids": [R3]}).status_code == 404, "#2094: a receipt in the trash cannot be billed")
# a finalised document keeps the receipt billed
r = A.post(B + RB + "/bill", json={"doc_id": Q["id"], "node_ids": [R2]})
PJ = r.json()
sql("UPDATE office_docs SET locked_at='2026-03-10T10:00:00Z' WHERE id=?", (Q["id"],), write=True)
r = A.post(B + RB + "/unbill", json={"node_ids": [R2], "positions": PJ["positions"]})
check(r.ok and r.json()["removed"] == 0 and str(R2) in A.get(B + RB + f"/billed?ids={R2}").json()["billed"], "#2094: a finalised document keeps its positions and the receipt stays billed")
check(A.post(B + RB + "/bill", json={"doc_id": Q["id"], "node_ids": [R1]}).status_code == 409, "#2094: a finalised document takes no positions")
# 2.121.0 review M1: a sent document counts as final for the undo too (positions stay, the receipt stays billed)
Q3 = A.post(B + D, json={"project_title": "Film drei", "client_id": CL}).json()
r = A.post(B + RB + "/bill", json={"doc_id": Q3["id"], "node_ids": [R1]})
check(r.ok, f"review M1: billed on a fresh draft ({r.text[:160]})")
sql("UPDATE office_docs SET status='sent' WHERE id=?", (Q3["id"],), write=True)
r = A.post(B + RB + "/unbill", json={"node_ids": [R1], "positions": r.json()["positions"]})
check(r.ok and r.json()["removed"] == 0 and str(R1) in A.get(B + RB + f"/billed?ids={R1}").json()["billed"],
      f"review M1: a sent document keeps its positions and the receipt stays billed ({r.text[:160]})")

# ================================================================ a person without organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
Fr.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Frida Film", "street": "Weg 3", "zip": "12345", "city": "Stadt", "country": "DE"}})
FAG, FAGS = new_agent(A, FID, None, "fridabot")
FD = upload(Fr, "freelance-invoice.pdf", "Freelance invoice", "private")
check(Fr.post(B + f"/api/files/nodes/{FD}/shares", json={"agent_id": FAG, "role": "view"}).ok, "freelancer: shares with her agent")
r = FAGS.post(V + f"/documents/{FD}/receipt-suggestion", json={"amount": "23.80", "vat_pct": "19"})
check(r.status_code == 201, f"freelancer: her agent suggests amount + VAT rate ({r.status_code} {r.text[:160]})")
r2 = Fr.post(B + f"/api/receipt-suggestions/{r.json().get('id')}/accept", json={})
check(r2.ok and Fr.get(B + f"/api/docs/{FD}").json()["amount"] == "23.80" and r2.json()["receipt"]["vat_pct"] == "19", "freelancer: she accepts")
check(FAGS.post(V + f"/documents/{DA}/receipt-suggestion", json={"amount": "1.00"}).status_code == 404, "freelancer: her agent never reaches the organisation's documents")
FR = receipt(Fr, "privat-beleg.pdf", "private", "119.00", "19", "Material")
FQ = Fr.post(B + D, json={"project_title": "Privatfilm"}).json()
r = Fr.post(B + RB + "/bill", json={"doc_id": FQ["id"], "node_ids": [FR], "markup_pct": 0})
check(r.ok and len(r.json()["positions"]) == 1 and Fr.get(B + f"{D}/{FQ['id']}").json()["items"][0]["cost"] == 100.0, "freelancer: billed on in the personal office " + r.text[:160])
check(Fr.post(B + RB + "/bill", json={"doc_id": FQ["id"], "node_ids": [FR]}).status_code == 409, "freelancer: never twice")
check(Fr.get(B + RB + f"/billed?ids={FR}").json()["billed"].get(str(FR), {}).get("doc_id") == FQ["id"], "freelancer: the billed list")
Q2 = A.post(B + D, json={"project_title": "Film zwei", "client_id": CL}).json()
check(A.post(B + RB + "/bill", json={"doc_id": Q2["id"], "node_ids": [FR]}).status_code == 404, "freelancer: the organisation's admin does not reach the receipt")
r = Fr.post(B + RB + "/unbill", json={"node_ids": [FR], "positions": r.json()["positions"]})
check(r.ok and r.json()["removed"] == 1 and Fr.get(B + f"{D}/{FQ['id']}").json()["items"] == [], "freelancer: unbill")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
