#!/usr/bin/env python3
"""2.281.0 C (#3115) the office document list, own container (start.sh). Invented companies and numbers only.
 - 521 invoices: the overdue one and the partly paid one are the two oldest -> the filters "overdue" / "partial" find them
   (before: decided after the 500 newest, they were missing without a word); the filter keeps only that state
 - payment state and sums of a row are the same as in the document itself (state, status text, paid, open)
 - the status text in the person's language; the statements of the list do not grow with its rows (20 vs. 200)
 - a person without an organisation (freelancer-matrix: office): the own overdue invoice, nothing of the organisation
usage: p2281_d_officedocs_test.py <datadir>      (a fresh container; P2281D_NOSTART=1 = the server already runs)"""
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import check, done, sess, B, H, DATA  # noqa: E402

FEAT = "cal,comments,office,clients"
O, D = "/api/office", "/api/office/docs"
TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        cur = c.execute(sql, args)
        if write:
            c.commit()
            return None
        return cur.fetchall()
    finally:
        c.close()


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


def invoice(s, client, rate=100, final=True):
    r = s.post(B + D, json={"kind": "invoice", "lang": "en", "client_id": client, "items": [{"title": "Edit", "qty": 1, "rate": rate}],
                            "service_from": "2026-03-01", "service_to": "2026-03-15"})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if final:
        r = s.post(B + f"{D}/{did}/finalize")
        assert r.ok, r.text
    else:  # (an office without its company details yet: finalised in the database, the list only reads the row)
        dbx("UPDATE office_docs SET status='issued', locked_at=updated_at WHERE id=?", (did,), write=True)
    return did


def listed(s, **kw):
    r = s.get(B + D, params={"kind": "invoice", **kw})
    assert r.ok, r.text
    return r


if not os.environ.get("P2281D_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
r = A.put(B + O + "/settings", json={"pack": "XX", "home_currency": "GBP", "company": {"name": "Brightside Ltd"},
                                     "company_fields": {"name": "Brightside Ltd", "street": "1 High Street", "zip": "AB1 2CD", "city": "Exampleton",
                                                        "country": "GB", "vat_id": "GB999999973", "iban": "GB33BUKB20201555555555"}})
check(r.ok, "setup: office " + r.text[:200])
CL = A.post(B + "/api/clients", json={"name": "Example Client Ltd", "street": "2 Low Road", "zip": "EF3 4GH", "city": "Sampleford", "country": "GB"}).json()["id"]

# the two oldest: overdue (no payment, due long ago) and partly paid
OVER = invoice(A, CL)
PART = invoice(A, CL)
r = A.post(B + f"{D}/{PART}/payments", json={"amount": "10.00", "date": "2026-03-20"})
check(r.status_code in (200, 201), "setup: a part payment " + r.text[:200])
dbx("UPDATE office_docs SET date='2020-01-01', due_date='2020-01-15' WHERE id=?", (OVER,), write=True)
dbx("UPDATE office_docs SET date='2020-01-02', due_date='2099-12-31' WHERE id=?", (PART,), write=True)
# 519 newer finalised invoices (not due yet): copies of a third one, 20 in 2024, 200 in 2025, 299 in 2026
TPL = invoice(A, CL)
dbx("UPDATE office_docs SET date='2026-06-01', due_date='2099-12-31' WHERE id=?", (TPL,), write=True)
cols = [r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() "
                          "AND table_name='office_docs' AND column_name NOT IN ('id', 'number', 'date') ORDER BY ordinal_position")]
cl = ", ".join(cols)
for year, n in (("2024", 20), ("2025", 200), ("2026", 298)):
    dbx(f"INSERT INTO office_docs ({cl}, number, date) SELECT {cl}, 'C{year}-' || g, '{year}-05-' || lpad(CAST(1 + g % 28 AS TEXT), 2, '0') "
        f"FROM office_docs, generate_series(1, {n}) g WHERE id=?", (TPL,), write=True)
total = dbx("SELECT count(*) FROM office_docs WHERE org_id=? AND kind='invoice'", (ORG,))[0][0]
check(total == 521, f"setup: 521 invoices ({total})")

# ---- the derived states before the 500
ov = listed(A, status="overdue").json()["docs"]
check([d["id"] for d in ov] == [OVER], f"overdue: the oldest invoice is found (beyond the 500 newest) {[d['id'] for d in ov][:5]}")
pa = listed(A, status="partial").json()["docs"]
check([d["id"] for d in pa] == [PART], f"partly paid: found as well {[d['id'] for d in pa][:5]}")
allr = listed(A).json()["docs"]
check(len(allr) == 500 and OVER not in [d["id"] for d in allr], f"without a filter: the 500 newest as before ({len(allr)})")
check(all(d["state"] == "issued" for d in allr), "the newer ones are open and not due")

# ---- the row is the document (state, text, sums)
for did, row in ((OVER, ov[0] if ov else {}), (PART, pa[0] if pa else {})):
    full = A.get(B + f"{D}/{did}").json()
    full = full.get("doc", full)
    same = {k: (row.get(k), full.get(k)) for k in ("state", "status_text", "gross_text") if k in full}
    check(same and all(a == b for a, b in same.values()), f"row {did} = document: {same}")
check(ov and ov[0]["status_text"] == "Overdue" and ov[0]["open"] == ov[0]["gross"] and ov[0]["paid"] == "0.00",
      f"overdue row: text and sums {ov[:1]}")
check(pa and pa[0]["status_text"] == "Partly paid" and pa[0]["paid"] == "10.00", f"partly paid row: text and paid {pa[:1]}")
A.patch(B + "/api/settings", json={"lang": "de"})
ovd = listed(A, status="overdue").json()["docs"]
check(ovd and ovd[0]["status_text"] == "Überfällig", f"the status text in the person's language {ovd[:1]}")
A.patch(B + "/api/settings", json={"lang": "en"})

# ---- statements do not grow with the rows (before: one user_settings read per row)
r20, r200 = listed(A, year="2024"), listed(A, year="2025")
n20, n200 = nstmt(r20), nstmt(r200)
check(len(r20.json()["docs"]) == 20 and len(r200.json()["docs"]) == 200, "setup: 20 / 200 rows of a year")
check(0 < n20 and n200 <= n20 + 5, f"statements of the list do not grow per row: {n20} (20 rows) vs. {n200} (200 rows)")

# ---- a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A, "fred", features=FEAT)
FC = Fr.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]
FO = invoice(Fr, FC, final=False)
FN = invoice(Fr, FC, final=False)
dbx("UPDATE office_docs SET date='2021-01-01', due_date='2021-01-15' WHERE id=?", (FO,), write=True)
dbx("UPDATE office_docs SET due_date='2099-12-31' WHERE id=?", (FN,), write=True)
fo = listed(Fr, status="overdue").json()["docs"]
check([d["id"] for d in fo] == [FO], f"freelancer: the own overdue invoice only {[d['id'] for d in fo]}")
check(FN in [d["id"] for d in listed(Fr).json()["docs"]] and OVER not in [d["id"] for d in listed(Fr).json()["docs"]],
      "freelancer: the own list, nothing of the organisation")

sys.exit(done("p2281_d_officedocs"))
