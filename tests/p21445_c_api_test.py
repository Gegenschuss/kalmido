#!/usr/bin/env python3
"""2.144.5 API tests, part C (#1523 #2021), own container (start.sh). Invented names, companies and figures only.
 - #1523 formula depth: a list formula nested deeper than 64 brackets / signs or a tree deeper than 200 is refused (400,
   "nested too deeply"), a normal formula still works; also for a person without an organisation (freelancer-matrix: lists)
 - #1523 invoice positions with list_id: an invoice from times remembers the list of each position (kept when the draft is
   saved); "Delete all times" keeps those entries as billed after the list was renamed; an older position (no list_id) is
   still matched by the name; a person without an organisation in the personal office too (freelancer-matrix: office)
 - 2.144.5 A2 (review R9/R10): another organisation's invoice with the same client id does not bill a private list; the
   personal office moved into an organisation leaves the positions' list behind (list_id NULL)
 - #1523 list header sum: time_lists in /api/state shows a member only their own entries, the owner everyone's; the project
   page's "Tracked" stays everyone's
 - #2021 (a) a series without own title is named after the template's project title without placeholders
 - #2021 (b) a subscription whose last day to cancel has passed: cancel_missed + cancel_next (the next reachable last day),
   cancel_by unchanged, sorted by the next chance; also in the personal office
usage: p21445_c_api_test.py <datadir>      (P21445C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,time,fields,docs"
O = "/api/office"
D = O + "/docs"
COMPANY = {"name": "Beispiel Studio GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "tax_number": "12/345/67890", "iban": "DE02120300000000202051"}


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


if not os.environ.get("P21445C_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
me = lambda s: s.get(B + "/api/state").json()["me"]["id"]  # noqa: E731
ALICE, BOB = me(A), me(Bo)
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
assert A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": COMPANY}).ok
FID, Fr = freelancer(B, A)
assert Fr.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {**COMPANY, "name": "Frida Frei"}}).ok
T0 = testclock.today()
TODAY = T0.isoformat()


# ================================================================== #1523 formula depth
def formula_case(S, who):
    lid = S.post(B + "/api/lists", json={"name": f"Formeln {who}", "kind": "project"}).json()["id"]
    fa = S.post(B + f"/api/lists/{lid}/fields", json={"name": "Amount", "type": "number"}).json()
    check(fa.get("id"), f"{who}: setup number field")
    r = S.post(B + f"/api/lists/{lid}/fields", json={"name": "Ok", "type": "formula", "formula": "round(({Amount} + 1) * -(2 - 1), 2)"})
    check(r.status_code in (200, 201) and r.json().get("type") == "formula", f"{who}: a normal formula still works {r.status_code} {r.text[:200]}")
    for bad, what in (("(" * 70 + "{Amount}" + ")" * 70, "70 brackets"), ("-" * 80 + "1", "80 signs"), ("+".join(["1"] * 230), "a tree of 230")):
        r = S.post(B + f"/api/lists/{lid}/fields", json={"name": "Deep", "type": "formula", "formula": bad})
        check(r.status_code == 400 and "nested too deeply" in r.json().get("error", ""), f"{who}: {what} -> 400 nested too deeply {r.status_code} {r.text[:200]}")
    r = S.post(B + f"/api/lists/{lid}/fields", json={"name": "Wide", "type": "formula", "formula": "+".join(["{Amount}"] * 40)})
    check(r.status_code in (200, 201), f"{who}: 40 terms in a row stay fine {r.status_code} {r.text[:200]}")


formula_case(A, "org")
formula_case(Fr, "freelancer")  # freelancer-matrix: lists


# ================================================================== #1523 invoice positions with list_id
def entry(user_id, list_id, start, end, secs):
    sql("INSERT INTO time_entries(user_id, list_id, task_title, start, \"end\", seconds, note, source, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user_id, list_id, "Schnitt", start, end, secs, "", "manual", end, end), write=True)


def list_for(S, name, cl):
    lid = S.post(B + "/api/lists", json={"name": name, "kind": "project"}).json()["id"]
    r = S.patch(B + f"/api/lists/{lid}", json={"client_id": cl, "time_tracking": True})
    assert r.ok, r.text
    return lid


def billed(S, lid):
    r = S.get(B + f"/api/lists/{lid}/time/delete-all")
    assert r.ok, r.text
    return r.json()["billed"]


def billed_case(S, who, uid):
    cl = S.post(B + "/api/clients", json={"name": f"Kunde {who}", "street": "Kundenweg 5", "zip": "20000", "city": "Beispielstadt", "country": "DE"}).json()["id"]
    lid = list_for(S, f"Projekt {who}", cl)
    entry(uid, lid, "2026-05-04T08:00:00Z", "2026-05-04T10:00:00Z", 7200)
    entry(uid, lid, "2026-06-04T08:00:00Z", "2026-06-04T09:00:00Z", 3600)  # outside the invoice's period
    r = S.post(B + D + "/from-time", json={"client_id": cl, "from": "2026-05-01", "to": "2026-05-31"})
    check(r.status_code == 201, f"{who}: invoice from times {r.text[:200]}")
    did = r.json()["id"]
    rows = sql("SELECT title, list_id FROM office_doc_items WHERE doc_id=?", (did,))
    check([tuple(x) for x in rows] == [(f"Projekt {who}", lid)], f"{who}: the position carries the list {rows}")
    check(billed(S, lid) == 1, f"{who}: the entry in the period counts as billed")
    # the draft is saved by the editor (the position comes back with its id): list_id stays
    doc = S.get(B + f"{D}/{did}").json()
    its = [{k: x.get(k) for k in ("id", "kind", "title", "detail", "qty", "unit", "rate", "tax", "intext", "discountable")} for x in doc["items"]]
    its[0]["rate"] = 80
    r = S.put(B + f"{D}/{did}/items", json={"items": its})
    check(r.ok, f"{who}: the draft saved {r.status_code} {r.text[:200]}")
    rows = sql("SELECT rate, list_id FROM office_doc_items WHERE doc_id=?", (did,))
    check(len(rows) == 1 and float(rows[0][0]) == 80 and rows[0][1] == lid, f"{who}: the saved position keeps its list {rows}")
    r = S.patch(B + f"/api/lists/{lid}", json={"name": f"Umbenannt {who}"})
    check(r.ok, f"{who}: rename the list {r.text[:200]}")
    check(billed(S, lid) == 1, f"{who}: after the rename the entry still counts as billed")
    r = S.post(B + f"/api/lists/{lid}/time/delete-all", json={"confirm": f"Umbenannt {who}"})
    check(r.ok and r.json()["deleted"] == 1 and r.json()["billed"] == 1, f"{who}: delete all keeps the billed entry {r.text[:200]}")
    check(sql("SELECT COUNT(*) FROM time_entries WHERE list_id=?", (lid,))[0][0] == 1, f"{who}: the billed entry is still there")
    # an older invoice: a position without list_id, matched by the list's name as before
    lid2 = list_for(S, f"Altprojekt {who}", cl)
    entry(uid, lid2, "2026-07-04T08:00:00Z", "2026-07-04T10:00:00Z", 7200)
    r = S.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": "2026-07-01", "service_to": "2026-07-31",
                            "items": [{"kind": "service", "title": f"altprojekt {who} ", "qty": 2, "unit": "hour", "rate": 50}]})
    check(r.status_code == 201, f"{who}: a hand-made invoice {r.text[:200]}")
    check(sql("SELECT list_id FROM office_doc_items WHERE doc_id=?", (r.json()["id"],))[0][0] is None, f"{who}: a hand-made position has no list")
    check(billed(S, lid2) == 1, f"{who}: an older position is matched by the name")
    S.patch(B + f"/api/lists/{lid2}", json={"name": f"Neu {who}"})
    check(billed(S, lid2) == 0, f"{who}: by name only = a rename loses it (older invoices, unchanged)")
    return lid


LORG = billed_case(A, "Alpha", ALICE)
FLID = billed_case(Fr, "Frida", FID)  # freelancer-matrix: office

# 2.144.5 A2 (#1523, review R9): a private list counts only invoices of its owner's personal office, never another
# organisation's invoice that carries the same client id
FCL = sql("SELECT client_id FROM lists WHERE id=?", (FLID,))[0][0]
LR9 = list_for(Fr, "Privatprojekt R9", FCL)
entry(FID, LR9, "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z", 7200)
CLA = A.post(B + "/api/clients", json={"name": "Kunde R9", "street": "Weg 9", "zip": "20000", "city": "Beispielstadt", "country": "DE"}).json()["id"]
r = A.post(B + D, json={"kind": "invoice", "client_id": CLA, "service_from": "2026-08-01", "service_to": "2026-08-31",
                        "items": [{"kind": "service", "title": "Privatprojekt R9", "qty": 2, "unit": "hour", "rate": 50}]})
check(r.status_code == 201, f"R9: an invoice of the organisation {r.text[:200]}")
sql("UPDATE office_docs SET client_id=? WHERE id=?", (FCL, r.json()["id"]), write=True)
check(billed(Fr, LR9) == 0, "R9: another organisation's invoice does not bill a private list")

# ================================================================== #1523 the list header's time sum
LT = A.post(B + "/api/lists", json={"name": "Teamzeit", "kind": "project"}).json()["id"]
A.patch(B + f"/api/lists/{LT}", json={"time_tracking": True})
assert A.put(B + f"/api/lists/{LT}/members", json={"user_id": BOB, "role": "edit"}).ok
entry(ALICE, LT, "2026-05-04T08:00:00Z", "2026-05-04T10:00:00Z", 7200)
entry(BOB, LT, "2026-05-05T08:00:00Z", "2026-05-05T09:00:00Z", 3600)
tl = lambda S: (S.get(B + "/api/state").json().get("time_lists") or {}).get(str(LT)) or {}  # noqa: E731
check(tl(Bo).get("s") == 3600, f"a member sees only their own hours in the list header {tl(Bo)}")
check(tl(A).get("s") == 10800, f"the owner sees everyone's {tl(A)}")
r = Bo.get(B + f"/api/lists/{LT}/overview")
if r.ok and (r.json().get("time") or {}).get("seconds") is not None:
    check(r.json()["time"]["seconds"] == 10800, f"the project page's 'Tracked' stays everyone's {r.json()['time']}")

# ================================================================== #2021 (a) series name without placeholders
for S, who in ((A, "org"), (Fr, "freelancer")):
    cl = S.post(B + "/api/clients", json={"name": f"Serienkunde {who}", "street": "Weg 1", "zip": "20000", "city": "Beispielstadt", "country": "DE"}).json()["id"]
    t = S.post(B + D, json={"kind": "invoice", "lang": "de", "client_id": cl, "project_title": "Wartung {month}", "service_from": "2026-01-01",
                            "service_to": "2026-01-31", "items": [{"title": "Betreuung", "qty": 1, "rate": 100}]})
    check(t.status_code == 201, f"{who}: a template invoice {t.text[:200]}")
    r = S.post(B + O + "/series", json={"template_id": t.json()["id"], "every": "monthly", "start": "2027-01-31"})
    check(r.status_code == 201 and r.json().get("title") == "Wartung", f"{who}: the series is named without the placeholder {r.text[:200]}")
    its = S.get(B + O + "/series").json()["items"]
    check([x["title"] for x in its] == ["Wartung"], f"{who}: the series list too {[x['title'] for x in its]}")

# ================================================================== #2021 (b) missed notice period
F = "/api/office/fixed-costs"


def year_back(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def year_on(d):
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


for S, who in ((A, "org"), (Fr, "freelancer")):
    REN = T0 + timedelta(days=10)
    r = S.post(B + F, json={"label": f"Domain {who}", "amount": 120, "vat_rate": 19, "repeat": "yearly", "start": year_back(REN).isoformat(),
                            "sub": 1, "notice_days": 30})
    check(r.status_code == 201, f"{who}: a yearly subscription {r.text[:200]}")
    M = r.json()
    check(M["next_renewal"] == REN.isoformat() and M["cancel_by"] == (REN - timedelta(days=30)).isoformat(), f"{who}: cancel_by keeps its meaning {M}")
    check(M.get("cancel_missed") == 1 and M.get("cancel_next") == (year_on(REN) - timedelta(days=30)).isoformat(),
          f"{who}: missed -> the next chance = the following renewal's last day {M.get('cancel_missed')} {M.get('cancel_next')}")
    r = S.post(B + F, json={"label": f"Tool {who}", "amount": 10, "repeat": "yearly", "start": year_back(T0 + timedelta(days=60)).isoformat(),
                            "sub": 1, "notice_days": 30})
    OK = r.json()
    check(OK.get("cancel_missed") == 0 and OK.get("cancel_next") == "" and OK["cancel_by"] == (T0 + timedelta(days=30)).isoformat(),
          f"{who}: a reachable last day is not missed {OK}")
    r = S.post(B + F, json={"label": f"Monat {who}", "amount": 5, "repeat": "monthly", "start": TODAY, "sub": 1, "notice_days": 45})
    MM = r.json()
    check(MM.get("cancel_missed") == 1 and MM.get("cancel_next") >= TODAY, f"{who}: a long notice on a monthly cost skips to a reachable one {MM}")
    labels = [f["label"] for f in S.get(B + O + "/subs").json()["items"] if f["label"] in (f"Domain {who}", f"Tool {who}")]
    check(labels == [f"Tool {who}", f"Domain {who}"], f"{who}: the missed one sorts by its next chance {labels}")

# ================================================================== 2.144.5 A2 (#1523, review R10)
# the personal office into an organisation: the positions forget the list they came from (it stays behind)
FIT = sql("SELECT id FROM office_doc_items WHERE list_id=?", (FLID,))
check(len(FIT) == 1, f"R10 setup: the freelancer's position with its list {FIT}")
ZET = A.post(B + "/api/admin/orgs", json={"name": "Zeta", "admin_id": FID}).json()["id"]
Fr.patch(B + "/api/settings", json={"workspace": "private"})
r = Fr.post(B + O + "/move/org", json={"org": ZET, "confirm": True})
check(r.ok, f"R10: the personal office into the organisation {r.status_code} {r.text[:300]}")
if FIT:
    row = sql("SELECT org_id, list_id FROM office_doc_items WHERE id=?", (FIT[0][0],))
    check(row and row[0][1] is None, f"R10: the moved position has no list of the old office {row}")

print(f"p21445_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
