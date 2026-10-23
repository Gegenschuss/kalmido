#!/usr/bin/env python3
"""2.187.0 API tests, part B (#2476, office rights in the office's own routes), own container (start.sh). Invented people,
companies and figures only.
 (a) a member without a group ("Previous access") answers as before: quotes & invoices yes, bank 403, figures 403
 (b) staff: only the own receipts / trips / drives / entertainment receipts / times, somebody else's entry 404 (read,
     change, delete), new entries allowed, reports / exports / billing 403, no bank, no figures, no invoices
 (c) finance: bank, bookkeeping and settings yes, manages the rights of others, never more than they have (own groups,
     own person, a group above their levels 403), invites nobody (403 as before)
 (d) bookkeeping without "release": finalising / sending 403; with "export": the DATEV export works
 (e) an organisation admin cannot be restricted (409); the rights log has the changes, also in the tax auditor's export
 (f) a person without an organisation: the rights page, an own group, the own agent in it
 (g) an own group: its level counts (bank read yes, bank matching needs edit + pay)
usage: p2187_b_rights_test.py <datadir>      (P2187B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)
freelancer-matrix: office  tenant-matrix: office"""
import csv
import io
import os
import subprocess
import sys
import time
import zipfile
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,time,docs,files,travel"
O = "/api/office"
R = O + "/rights"


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


def upload(s, name):
    r = s.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    check(r.status_code == 201, f"upload {name}: {r.status_code} {r.text[:200]}")
    return r.json()["ids"][0] if r.status_code == 201 else None


def receipt(nid, amount):
    """The admin gives the uploaded document an amount, today's date and a category (who uploaded it stays)."""
    assert A.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": TD}).ok
    r = A.put(B + f"/api/docs/{nid}/receipt", json={"category": "Material", "vat_pct": "19", "keep": True})
    assert r.ok, r.text


def put_groups(s, uid, refs):
    return s.put(B + f"{R}/people/{uid}", json={"groups": refs})


if not (os.environ.get("P2187B_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ids, S = {}, {}
for u, n in (("bob", "Bob Member"), ("sam", "Sam Staff"), ("fin", "Fina Finance"), ("bk", "Bea Books"), ("gus", "Gus Group")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
    S[u] = sess(u)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
for s in S.values():
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
Bo, Sa, Fi, Bk, Gu = S["bob"], S["sam"], S["fin"], S["bk"], S["gus"]
TD = testclock.today().isoformat()
GP = {"from": (testclock.today() - timedelta(days=2)).isoformat(), "to": (testclock.today() + timedelta(days=2)).isoformat()}  # the log is in UTC
Y = TD[:4]

# ---------------------------------------------------------------- data of the admin (before any group)
C1 = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "org_id": ORG, "city": "Köln", "country": "DE"}).json()["id"]
r = A.post(B + O + "/docs", json={"kind": "invoice", "client_id": C1, "items": [{"title": "Schnitt", "qty": 1, "rate": 1000}]})
assert r.status_code == 201, r.text
INV = r.json()["id"]
TA = A.post(B + O + "/trips", json={"date_from": TD, "date_to": TD, "dest": "Kunde Beispiel", "country": "DE", "project": "Geheimprojekt"})
assert TA.status_code == 201, TA.text
TA = TA.json()["id"]
VEH = A.post(B + O + "/vehicles", json={"name": "Van", "plate": "B-XX 1", "kind": "company"})
assert VEH.status_code == 201, VEH.text
VEH = VEH.json()["id"]
DA = A.post(B + O + "/drives", json={"vehicle_id": VEH, "day": TD, "dest": "Kunde", "purpose": "Dreh", "km": 30, "kind": "business"})
assert DA.status_code == 201, DA.text
DA = DA.json()["id"]
MA = A.post(B + O + "/meals", json={})
assert MA.status_code == 201, MA.text
MA = MA.json()["id"]
RA = upload(A, "admin-beleg.pdf")
receipt(RA, "119.00")
LID = A.post(B + "/api/lists", json={"name": "Projekt Hafen", "org_id": ORG, "time_tracking": True}).json()["id"]
A.patch(B + f"/api/lists/{LID}", json={"client_id": C1})
r = A.put(B + f"/api/lists/{LID}/members", json={"user_id": ids["sam"], "role": "edit"})
check(r.ok, "setup: sam edits the project " + r.text[:160])
assert A.post(B + "/api/time/entries", json={"list_id": LID, "start": TD + "T08:00:00Z", "minutes": 120}).ok

# ---------------------------------------------------------------- (a) no group = exactly as before
check(Bo.get(B + O + "/docs").status_code == 200, "(a) a member without a group: quotes & invoices 200")
check(Bo.get(B + O + "/bank/tx").status_code == 403, "(a) a member without a group: bank 403")
check(Bo.get(B + O + "/kpi").status_code == 403, "(a) a member without a group: figures 403")
check(Bo.get(B + O + "/trips").status_code == 403, "(a) a member without a group: travel expenses (admins only) 403")
mine = Bo.get(B + R).json()
check(mine.get("mine", {}).get("legacy") is True and "people" not in mine, f"(a) the rights page: previous access, no management {mine.get('mine')}")

# ---------------------------------------------------------------- groups by the admin
for u, t in (("sam", "staff"), ("fin", "finance"), ("bk", "bookkeeping")):
    r = put_groups(A, ids[u], [f"tpl:{t}"])
    check(r.ok, f"admin: {u} -> {t} " + r.text[:160])
r = A.post(B + R + "/groups", json={"from": "tpl:readonly", "name": "Bank lesen"})
check(r.status_code == 201, "admin: an own group " + r.text[:160])
GG = r.json().get("id")
r = A.patch(B + f"{R}/groups/{GG}", json={"levels": {"bank": "view", "kpi": "none"}})
check(r.ok and r.json()["levels"]["bank"] == "view" and r.json()["levels"]["kpi"] == "none", "admin: the own group's levels " + r.text[:160])
check(put_groups(A, ids["gus"], [f"g:{GG}"]).ok, "admin: gus -> the own group")

# ---------------------------------------------------------------- (b) staff: only the own entries
check(Sa.get(B + O + "/bank/tx").status_code == 403, "(b) staff: bank 403")
check(Sa.get(B + O + "/kpi").status_code == 403, "(b) staff: figures 403")
check(Sa.get(B + O + "/docs").status_code == 403, "(b) staff: the invoices 403")
check(Sa.get(B + O + f"/docs/{INV}").status_code == 403, "(b) staff: an invoice by id 403")
# travel
r = Sa.post(B + O + "/trips", json={"date_from": TD, "date_to": TD, "dest": "Messe Beispiel", "country": "DE"})
check(r.status_code == 201, "(b) staff: a new trip " + r.text[:160])
TS = r.json().get("id") if r.status_code == 201 else None
r = Sa.get(B + O + "/trips")
tr_ = r.json().get("trips", []) if r.ok else []
check(r.ok and [t["id"] for t in tr_] == [TS], f"(b) staff: only the own trip {r.status_code} {[t.get('id') for t in tr_]}")
check(r.ok and "Geheimprojekt" not in (r.json().get("projects") or []), "(b) staff: no project names of others")
check(Sa.patch(B + O + f"/trips/{TA}", json={"dest": "X"}).status_code == 404, "(b) staff: somebody else's trip change 404")
check(Sa.delete(B + O + f"/trips/{TA}").status_code == 404, "(b) staff: somebody else's trip delete 404")
check(Sa.post(B + O + f"/trips/{TA}/items", json={"date": TD, "category": "taxi", "amount": 5}).status_code == 404,
      "(b) staff: a receipt on somebody else's trip 404")
check(Sa.patch(B + O + f"/trips/{TS}", json={"dest": "Messe Beispiel 2"}).ok, "(b) staff: the own trip change")
check(Sa.post(B + O + f"/trips/{TS}/items", json={"date": TD, "category": "taxi", "amount": 12}).status_code == 201, "(b) staff: a receipt on the own trip")
check(Sa.get(B + O + "/trips/report").status_code == 403, "(b) staff: the travel report 403")
check(Sa.post(B + O + "/trips/bill", json={}).status_code == 403, "(b) staff: billing trips 403")
check(Sa.get(B + O + "/trips/vma.csv").status_code == 403, "(b) staff: the allowance export 403")
check(Sa.post(B + O + "/trips/purposes", json={"name": "Messe"}).status_code == 403, "(b) staff: the purposes (settings of the area) 403")
check(A.get(B + O + "/trips").ok and len(A.get(B + O + "/trips").json()["trips"]) == 2, "(b) the admin sees both trips")
# logbook
check(Sa.get(B + O + "/vehicles").ok, "(b) staff: the logbook's start (vehicles)")
check(Sa.post(B + O + "/vehicles", json={"name": "Rad", "kind": "company"}).status_code == 403, "(b) staff: a vehicle (manage) 403")
r = Sa.post(B + O + "/drives", json={"vehicle_id": VEH, "day": TD, "dest": "Lager", "purpose": "Material", "km": 12, "kind": "business"})
check(r.status_code == 201, "(b) staff: a new drive " + r.text[:160])
DS = r.json().get("id") if r.status_code == 201 else None
r = Sa.get(B + O + "/drives")
check(r.ok and [d["id"] for d in r.json().get("drives", [])] == [DS], f"(b) staff: only the own drive {r.text[:200]}")
check(Sa.patch(B + O + f"/drives/{DA}", json={"km": 31}).status_code == 404, "(b) staff: somebody else's drive change 404")
check(Sa.delete(B + O + f"/drives/{DA}").status_code == 404, "(b) staff: somebody else's drive delete 404")
check(Sa.get(B + O + f"/drives/{DA}/log").status_code == 404, "(b) staff: somebody else's drive log 404")
check(Sa.post(B + O + "/drives", json={"vehicle_id": VEH, "day": TD, "dest": "Lager", "purpose": "X", "km": 3, "kind": "business",
                                      "user_id": ALICE}).status_code == 400, "(b) staff: a drive for somebody else 400")
check(Sa.get(B + O + "/logbook/report").status_code == 403, "(b) staff: the logbook report 403")
check(Sa.get(B + O + "/logbook.csv").status_code == 403, "(b) staff: the logbook export 403")
# entertainment receipts
r = Sa.post(B + O + "/meals", json={})
check(r.status_code == 201, "(b) staff: a new entertainment receipt " + r.text[:160])
MS = r.json().get("id") if r.status_code == 201 else None
r = Sa.get(B + O + "/meals")
check(r.ok and [m["id"] for m in r.json().get("meals", [])] == [MS], f"(b) staff: only the own entertainment receipt {r.text[:200]}")
check(Sa.get(B + O + f"/meals/{MA}").status_code == 404, "(b) staff: somebody else's entertainment receipt 404")
check(Sa.patch(B + O + f"/meals/{MA}", json={"note": "x"}).status_code == 404, "(b) staff: somebody else's entertainment receipt change 404")
check(Sa.get(B + O + f"/meals/{MA}/pdf").status_code == 404, "(b) staff: somebody else's entertainment receipt PDF 404")
check(Sa.get(B + O + "/meals/report").status_code == 403, "(b) staff: the entertainment report 403")
# receipts
RS = upload(Sa, "sam-beleg.pdf")
if RS:
    receipt(RS, "23.80")
r = Sa.get(B + O + "/books/receipts", params={"from": f"{Y}-01-01", "to": f"{Y}-12-31"})
check(r.ok and [x["node_id"] for x in r.json().get("rows", [])] == [RS], f"(b) staff: only the own receipt {r.status_code} {r.text[:200]}")
ra = A.get(B + O + "/books/receipts", params={"from": f"{Y}-01-01", "to": f"{Y}-12-31"})
check(ra.ok and {x["node_id"] for x in ra.json().get("rows", [])} >= {RA, RS}, "(b) the admin sees both receipts")
check(Sa.get(B + O + "/books/receipts.csv").status_code == 403, "(b) staff: the receipts export 403")
check(Sa.get(B + O + "/books").status_code == 403, "(b) staff: the bookkeeping 403")
# times
r = Sa.post(B + "/api/time/entries", json={"list_id": LID, "start": TD + "T10:00:00Z", "minutes": 30})
check(r.ok, "(b) staff: an own time entry " + r.text[:200])
P = {"client_id": C1, "from": TD, "to": TD}
r = Sa.get(B + O + "/time-open", params=P)
check(r.ok and r.json().get("open_seconds") == 1800, f"(b) staff: only the own hours {r.status_code} {r.text[:200]}")
r = A.get(B + O + "/time-open", params=P)
check(r.ok and r.json().get("open_seconds") == 9000, f"(b) the admin: all hours {r.text[:200]}")
m = Sa.get(B + R).json()
check(m["mine"]["levels"]["travel"] == "own" and m["mine"]["levels"]["bank"] == "none" and "people" not in m, f"(b) staff: the own rights {m.get('mine')}")
# 2.187.0 (#2476, review): the admins-only reads of an area members could use need "manage"; the office log too
check(Sa.get(B + O + "/equipment/value").status_code == 403, "(b) staff: the equipment value (admins only before) 403")
check(Sa.get(B + O + "/equipment/policies").status_code == 403, "(b) staff: the insurance list 403")
check(Sa.get(B + O + "/log").status_code == 403, "(b) staff: the office log 403")
r = Sa.get(B + O + "/meals/choices")
check(r.ok, "(b) staff: the own choices of the entertainment receipts " + r.text[:120])

# ---------------------------------------------------------------- (c) finance
check(Fi.get(B + O + "/bank/tx").ok, "(c) finance: bank 200")
check(Fi.get(B + O + "/equipment/value").ok, "(c) finance: the equipment value 200 (manages equipment)")
check(Fi.get(B + O + "/books").ok, "(c) finance: bookkeeping 200")
check(Fi.get(B + O + "/trips").ok and len(Fi.get(B + O + "/trips").json()["trips"]) == 2, "(c) finance: all trips")
j = Fi.get(B + R).json()
check(j.get("mine", {}).get("manager") == "group" and "people" in j, f"(c) finance manages the rights {j.get('mine')}")
check(put_groups(Fi, ids["fin"], ["tpl:orgadmin"]).status_code == 403, "(c) finance: the own person 403")
check(put_groups(Fi, ids["sam"], ["tpl:readonly"]).ok, "(c) finance: another person within the own rights")
check(put_groups(Fi, ids["sam"], ["tpl:orgadmin"]).status_code == 403, "(c) finance: a group above the own levels 403")
check(put_groups(Fi, ids["bob"], ["tpl:none"]).status_code == 403, "(c) finance: a member with more (previous access) 403")
check(Fi.post(B + R + "/groups", json={"from": "tpl:orgadmin"}).status_code == 403, "(c) finance: a group copied from office admin 403")
check(put_groups(Fi, ids["sam"], ["tpl:staff"]).ok, "(c) finance: back to staff")
r = A.post(B + R + "/groups", json={"from": "tpl:finance", "name": "Controlling"})
GF = r.json().get("id")
check(put_groups(A, ids["fin"], [f"g:{GF}"]).ok, "admin: finance into an own copy")
check(Fi.patch(B + f"{R}/groups/{GF}", json={"levels": {"pipeline": "manage"}}).status_code == 403, "(c) finance: the own group 403")
check(Fi.delete(B + f"{R}/groups/{GF}").status_code == 403, "(c) finance: deleting the own group 403")
check(Fi.post(B + f"/api/orgs/{ORG}/invites", json={"email": "neu@example.com"}).status_code == 403, "(c) finance: no invitation (403)")
check(Fi.put(B + f"/api/orgs/{ORG}/members", json={"email": "neu2@example.com", "role": "member"}).status_code == 403, "(c) finance: no members (403)")

# ---------------------------------------------------------------- (d) bookkeeping
check(Bk.get(B + O + "/docs").ok, "(d) bookkeeping: the invoices 200")
check(Bk.post(B + O + f"/docs/{INV}/finalize").status_code == 403, "(d) bookkeeping without release: finalise 403")
check(Bk.post(B + O + f"/docs/{INV}/send", json={}).status_code == 403, "(d) bookkeeping without release: send 403")
r = Bk.get(B + O + "/datev/extf", params={"from": f"{Y}-01-01", "to": f"{Y}-12-31"})
check(r.status_code != 403 and r.status_code < 500, f"(d) bookkeeping with export: DATEV export {r.status_code} {r.text[:160]}")
check(Bk.post(B + O + "/periods/lock", json={"through": "2000-01", "confirm": "01/2000"}).status_code != 403, "(d) bookkeeping with lock: not refused by the rights")
check(Bk.get(B + R).json().get("mine", {}).get("manager") == "", "(d) bookkeeping does not manage rights")
check(Bk.put(B + f"{R}/people/{ids['sam']}", json={"groups": ["tpl:none"]}).status_code == 403, "(d) bookkeeping: changing rights 403")

# ---------------------------------------------------------------- (g) an own group
check(Gu.get(B + O + "/bank/tx").ok, "(g) the own group: bank read 200")
check(Gu.get(B + O + "/kpi").status_code == 403, "(g) the own group: figures none 403")
check(Gu.post(B + O + "/bank/tx/1/match", json={"kind": "private"}).status_code == 403, "(g) the own group: bank matching 403")
check(Gu.post(B + O + "/docs", json={"kind": "offer", "client_id": C1}).status_code == 403, "(g) read only: a new quote 403")

# ---------------------------------------------------------------- (e) admins stay, the log
check(put_groups(A, ALICE, ["tpl:none"]).status_code == 409, "(e) the admin cannot be restricted (409)")
check(put_groups(Fi, ALICE, ["tpl:none"]).status_code == 409, "(e) not by finance either (409)")
lg = A.get(B + R + "/log")
items = lg.json().get("items", []) if lg.ok else []
check(lg.ok and sum(1 for x in items if x["action"] == "member_groups") >= 7 and any(x["action"] == "group_change" for x in items),
      f"(e) the rights log {len(items)} {[x['action'] for x in items][:12]}")
check(any(x["action"] == "member_groups" and x["user"] == ids["sam"] and x["by"] == ids["fin"] for x in items), "(e) the log names who changed whom")
check(Sa.get(B + R + "/log").status_code == 403, "(e) staff: the rights log 403")
r = A.get(B + O + "/gobd/export", params=GP)
check(r.ok, f"(e) the tax auditor's export {r.status_code}")
if r.ok:
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    check("rights_log.csv" in names and b"rights_log.csv" in z.read("index.xml"), f"(e) rights_log.csv in the ZIP and index.xml {sorted(names)}")
    if "rights_log.csv" in names:
        rows = list(csv.reader(io.StringIO(z.read("rights_log.csv").decode("utf-8"), newline=""), delimiter=";", quotechar='"'))
        check(len(rows) == len(items) and all(len(x) == 8 for x in rows),
              f"(e) rights_log.csv: one line per change, 8 columns {len(rows)}")
        check(any("Sam Staff" in x and "Fina Finance" in x and "member_groups" in x for x in rows), "(e) rights_log.csv: who, whom, what")
check(Bk.get(B + O + "/gobd/export", params=GP).ok, "(d) bookkeeping with export: the tax auditor's export")
check(Gu.get(B + O + "/gobd/export", params=GP).status_code == 403, "(g) read only without export: 403")

# ---------------------------------------------------------------- (f) a person without an organisation  freelancer-matrix: office
FID, Fr = freelancer(B, A, "erin", features=FEAT)
r = Fr.get(B + R)
j = r.json() if r.ok else {}
check(r.ok and j.get("personal") == 1 and j.get("mine", {}).get("manager") == "admin" and "templates" in j, f"freelancer: the rights page {r.text[:200]}")
check(Fr.get(B + O + "/trips").ok, "freelancer: the own office as before")
r = Fr.post(B + R + "/groups", json={"from": "tpl:bookkeeping", "name": "Buchhaltung Agent"})
check(r.status_code == 201, "freelancer: an own group " + r.text[:160])
FG = r.json().get("id") if r.status_code == 201 else None
ag = Fr.post(B + "/api/my/agents", json={"username": "erinbot", "display_name": "Erin's bot", "scopes": ["read"]})
check(ag.status_code in (200, 201), "freelancer: an own agent " + ag.text[:160])
FA = ag.json().get("id") if ag.ok else None
pp = {p["id"]: p for p in Fr.get(B + R).json().get("people", [])}
check(FA in pp and pp[FA]["agent"] and pp[FA]["groups"] == ["tpl:none"], f"freelancer: the agent starts without office access {pp.get(FA)}")
check(put_groups(Fr, FA, [f"g:{FG}"]).ok, "freelancer: the agent into the own group")
check(put_groups(Fr, FA, ["tpl:orgadmin"]).status_code == 400, "freelancer: an agent never manages rights (400)")
check(put_groups(Fr, FID, ["tpl:none"]).status_code == 409, "freelancer: the own person stays the admin (409)")
check(Fr.get(B + R + "/log").ok and len(Fr.get(B + R + "/log").json()["items"]) >= 2, "freelancer: the own rights log")
check(not any(x.get("user") == FA for x in items), "Alpha's log has nothing of the freelancer")
check(put_groups(Fr, ids["sam"], ["tpl:none"]).status_code == 404, "tenant-matrix: office -- a person of another office 404")
check(Fr.patch(B + f"{R}/groups/{GG}", json={"name": "X"}).status_code == 404, "tenant-matrix: office -- a group of another office 404")
check(Fr.delete(B + f"{R}/groups/{GG}").status_code == 404, "tenant-matrix: office -- deleting a group of another office 404")
check(not any(p["id"] == ids["sam"] for p in Fr.get(B + R).json().get("people", [])), "tenant-matrix: office -- nobody of Alpha on the own rights page")

print(f"\np2187_b_rights: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
