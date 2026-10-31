#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.369.0 A (#3200) the office document list in pages, own container (start.sh). Invented companies and numbers only.
 - pages of limit rows: together every row once, in the order of the list (same date, empty date); before= of a wrong
   shape = 400; without limit the 500 newest as before, now with next_cursor
 - status=open + client_id: an old open invoice behind 500 newer ones, with pages, without a stop at the first page
 - the search on the server finds a recipient stored with \\uXXXX escapes
 - which finalised quotation may go: same answer as the document (sent, signed, used), statements do not grow with the
   rows (quotations and settled reminders, 20 vs. 200)
 - a person without an organisation (freelancer-matrix: office): pages of the own documents, nothing of the organisation
usage: p2369_a_api_test.py <datadir>      (a fresh container)"""
import json
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


def newdoc(s, client, kind="invoice", final=True):
    r = s.post(B + D, json={"kind": kind, "lang": "en", "client_id": client, "items": [{"title": "Edit", "qty": 1, "rate": 100}],
                            "service_from": "2026-03-01", "service_to": "2026-03-15"})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if final:
        r = s.post(B + f"{D}/{did}/finalize")
        assert r.ok, r.text
    return did


def pages(s, **kw):
    """Every page of a list -> (rows, [page sizes])."""
    rows, sizes, cur = [], [], None
    for _ in range(100):
        r = s.get(B + D, params={**kw, **({"before": cur} if cur else {})})
        assert r.ok, r.text
        j = r.json()
        rows += j["docs"]
        sizes.append(len(j["docs"]))
        cur = j["next_cursor"]
        if not cur:
            return rows, sizes
    raise AssertionError("no end of the pages")


def copies(tpl, prefix, n, date_sql):
    cols = [r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() "
                              "AND table_name='office_docs' AND column_name NOT IN ('id', 'number', 'date') ORDER BY ordinal_position")]
    cl = ", ".join(cols)
    dbx(f"INSERT INTO office_docs ({cl}, number, date) SELECT {cl}, '{prefix}-' || g, {date_sql} "
        f"FROM office_docs, generate_series(1, {n}) g WHERE id=?", (tpl,), write=True)


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
client = lambda name: A.post(B + "/api/clients", json={"name": name, "street": "2 Low Road", "zip": "EF3 4GH", "city": "Sampleford", "country": "GB"}).json()["id"]
CL, CL2 = client("Example Client Ltd"), client("Other Client Ltd")

# ---- the old open invoice of the second client, behind everything else
OLD = newdoc(A, CL2)
dbx("UPDATE office_docs SET date='2020-01-01', due_date='2099-12-31' WHERE id=?", (OLD,), write=True)
TPL = newdoc(A, CL)
dbx("UPDATE office_docs SET date='2026-06-01', due_date='2099-12-31' WHERE id=?", (TPL,), write=True)
# 230 on one and the same day, 8 without a date, 280 others: paid ones among them would not change the order
copies(TPL, "SAME", 230, "'2026-05-05'")
copies(TPL, "NODATE", 8, "''")
copies(TPL, "OTHER", 280, "'2025-' || lpad(CAST(1 + g % 12 AS TEXT), 2, '0') || '-' || lpad(CAST(1 + g % 28 AS TEXT), 2, '0')")
total = dbx("SELECT count(*) FROM office_docs WHERE org_id=? AND kind='invoice'", (ORG,))[0][0]
check(total == 520, f"setup: 520 invoices ({total})")

# ---- pages
one = A.get(B + D, params={"kind": "invoice", "limit": 100}).json()
check(len(one["docs"]) == 100 and one["next_cursor"], f"a page of 100 with a cursor ({len(one['docs'])}, {one['next_cursor']})")
rows, sizes = pages(A, kind="invoice", limit=100)
ids = [d["id"] for d in rows]
check(len(ids) == 520 and len(set(ids)) == 520, f"all pages: every row once ({len(ids)} rows, {len(set(ids))} different)")
check(sizes == [100] * 5 + [20], f"page sizes {sizes}")
order = [(x[0], x[1]) for x in dbx("SELECT id, date FROM office_docs WHERE org_id=? AND kind='invoice' ORDER BY date DESC, id DESC", (ORG,))]
check(ids == [x[0] for x in order], "the pages keep the order of the list, also within one date")
check(rows[-1]["date"] == "" and sum(1 for d in rows if d["date"] == "") == 8, f"the rows without a date come last and all ({rows[-1]['date']!r})")
big, sizes = pages(A, kind="invoice", limit=7)
check([d["id"] for d in big] == ids, "another page size: the same rows")

j = A.get(B + D, params={"kind": "invoice"}).json()
check(len(j["docs"]) == 500 and j["next_cursor"], f"without limit: the 500 newest, and the way on ({len(j['docs'])})")
check(len(A.get(B + D, params={"kind": "invoice", "limit": 9999}).json()["docs"]) == 500, "a limit stays at 500")
check(len(A.get(B + D, params={"kind": "invoice", "limit": 0}).json()["docs"]) == 1, "limit 0 = one row, no empty page with a cursor")
for bad in ("x", "2026-01-01", ",abc", "2026-01-01,12;drop"):
    check(A.get(B + D, params={"kind": "invoice", "before": bad}).status_code == 400, f"a wrong cursor = 400: {bad}")
last = A.get(B + D, params={"kind": "invoice", "year": "2026", "limit": 500}).json()
check(last["next_cursor"] is None and len(last["docs"]) == 231, f"the last page has no cursor ({len(last['docs'])})")
# 2.369.0 (#3200 + #3839): a chosen sorting goes on by position: every row once over the pages, the old cut at 500 is gone
srt, cur, pages = [], None, 0
while pages < 12:
    j = A.get(B + D, params={"kind": "invoice", "limit": 200, "sort": "date", "dir": "asc", **({"before": cur} if cur else {})}).json()
    srt += [d["id"] for d in j["docs"]]
    pages, cur = pages + 1, j["next_cursor"]
    if not cur:
        break
days = {d["id"]: d["date"] for d in A.get(B + D, params={"kind": "invoice", "limit": 200, "sort": "date", "dir": "asc"}).json()["docs"]}
check(len(srt) == len(set(srt)) and len(srt) > 500 and not cur, f"sorted pages: every row once, past 500 ({len(srt)}, {len(set(srt))})")
check(list(days.values()) == sorted(days.values()), "sorted pages: the first page is the oldest")
check(A.get(B + D, params={"kind": "invoice", "sort": "date", "before": "2026-01-01,5"}).status_code == 400, "sorted pages: a cursor of the other shape = 400")

# ---- the open items from the server
op = A.get(B + D, params={"kind": "invoice", "status": "open", "client_id": CL2}).json()
check([d["id"] for d in op["docs"]] == [OLD] and op["next_cursor"] is None, f"the client's open invoice behind 500 newer ones {[d['id'] for d in op['docs']][:5]}")
oprows, opsizes = pages(A, kind="invoice", status="open", limit=200)
check(OLD in [d["id"] for d in oprows] and len(oprows) == 520 and opsizes == [200, 200, 120], f"open items in pages too (derived filter) {opsizes}")
r = A.post(B + f"{D}/{TPL}/payments", json={"amount": "120.00", "date": "2026-06-02"})
check(r.status_code in (200, 201), "setup: paid in full " + r.text[:200])
oprows, _ = pages(A, kind="invoice", status="open", limit=200)
check(TPL not in [d["id"] for d in oprows] and len(oprows) == 519, f"a paid invoice is no open item ({len(oprows)})")

# ---- the search on the server (a recipient written with \uXXXX escapes, as a part of the app stores it)
U = newdoc(A, CL)
dbx("UPDATE office_docs SET recipient=?, date='2019-01-01' WHERE id=?", (json.dumps({"name": "Müller Gruber", "lines": []}), U), write=True)
hit = A.get(B + D, params={"kind": "invoice", "q": "Müller", "limit": 100}).json()["docs"]
check([d["id"] for d in hit] == [U], f"the search finds the escaped name, also far behind the first page {[d['id'] for d in hit]}")
check(not A.get(B + D, params={"kind": "invoice", "q": "Mueller-nobody", "limit": 100}).json()["docs"], "a search without a match")

# ---- which finalised quotation may go (one query per check now): same answer as before, for the whole list
P = {k: newdoc(A, CL, "offer") for k in ("free", "sent_at", "logged", "signed", "used", "gen")}
dbx("UPDATE office_docs SET sent_at='2026-03-01T10:00:00Z' WHERE id=?", (P["sent_at"],), write=True)
dbx("INSERT INTO office_doc_log (org_id, doc_id, action, at) VALUES (?, ?, 'send', '2026-03-01T10:00:00Z')", (ORG, P["logged"]), write=True)
ms = dbx("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='office_signoffs' "
         "AND is_nullable='NO' AND column_default IS NULL AND is_identity='NO'")
vals = {"doc_id": P["signed"], "org_id": ORG, "state": "accepted"}
for (col,) in ms:
    vals.setdefault(col, "2026-03-01T10:00:00Z" if col.endswith("_at") else f"x{col}")
dbx(f"INSERT INTO office_signoffs ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()), write=True)
I = newdoc(A, CL, final=False)
dbx("UPDATE office_docs SET source_doc_id=? WHERE id=?", (P["used"], I), write=True)
ms = dbx("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='office_gen_docs' "
         "AND is_nullable='NO' AND column_default IS NULL AND is_identity='NO'")
vals = {"doc_id": P["gen"], "org_id": ORG}
for col, typ in ms:
    vals.setdefault(col, 0 if "int" in typ else f"x{col}")
dbx(f"INSERT INTO office_gen_docs ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()), write=True)
lst = {d["id"]: d for d in A.get(B + D, params={"kind": "offer"}).json()["docs"]}
for k, did in P.items():
    one = A.get(B + f"{D}/{did}").json()
    one = one.get("doc", one)
    want = k == "free"
    check(lst[did].get("can_delete") is want and one.get("can_delete") is want, f"quotation {k}: may go = {want} (list {lst[did].get('can_delete')}, document {one.get('can_delete')})")
    check(lst[did].get("can_unlock") is want, f"quotation {k}: undo finalising in the list = {want}")

# ---- statements do not grow with the rows
TO = newdoc(A, CL, "offer")
dbx("UPDATE office_docs SET date='2011-06-01' WHERE id=?", (TO,), write=True)
copies(TO, "OA", 19, "'2012-05-05'")
copies(TO, "OB", 200, "'2013-05-05'")
r20, r200 = A.get(B + D, params={"kind": "offer", "year": "2012"}), A.get(B + D, params={"kind": "offer", "year": "2013"})
check(len(r20.json()["docs"]) == 19 and len(r200.json()["docs"]) == 200, "setup: 19 / 200 finalised quotations")
n20, n200 = nstmt(r20), nstmt(r200)
check(0 < n20 and n200 <= n20 + 5, f"statements of the quotation list do not grow per row: {n20} vs. {n200}")

dbx("UPDATE office_docs SET due_date='2020-02-01' WHERE id=?", (TPL,), write=True)
OV = newdoc(A, CL)
dbx("UPDATE office_docs SET due_date='2020-02-01' WHERE id=?", (OV,), write=True)
rem = A.post(B + f"{D}/reminder", json={"doc_ids": [OV], "level": 1, "fee": 0})
check(rem.status_code in (200, 201), "setup: a reminder " + rem.text[:200])
RID = rem.json()["id"]
check(A.post(B + f"{D}/{RID}/finalize").ok, "setup: reminder finalised")
check(A.post(B + f"{D}/{OV}/payments", json={"amount": "120.00", "date": "2026-06-02"}).status_code in (200, 201), "setup: its invoice paid")
dbx("UPDATE office_docs SET date='2011-06-01' WHERE id=?", (RID,), write=True)
copies(RID, "RA", 19, "'2012-05-05'")
copies(RID, "RB", 200, "'2013-05-05'")
r20, r200 = A.get(B + D, params={"kind": "reminder", "year": "2012"}), A.get(B + D, params={"kind": "reminder", "year": "2013"})
check(r200.json()["docs"] and all(d["state"] == "done" and d["status_text"] == "Settled" for d in r200.json()["docs"]), "setup: the reminders are settled")
n20, n200 = nstmt(r20), nstmt(r200)
check(0 < n20 and n200 <= n20 + 5, f"statements of the reminder list do not grow per row (\"Settled\" once): {n20} vs. {n200}")

# ---- a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A, "fred", features=FEAT)
FC = Fr.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]
FD = newdoc(Fr, FC, final=False)
dbx("UPDATE office_docs SET status='issued', locked_at=updated_at, date='2026-02-02', due_date='2099-12-31' WHERE id=?", (FD,), write=True)
copies(FD, "FR", 11, "'2026-02-02'")
frows, fsizes = pages(Fr, kind="invoice", limit=5)
check(len(frows) == 12 and fsizes == [5, 5, 2], f"freelancer: the own documents in pages {fsizes}")
check(not {d["id"] for d in frows} & set(ids), "freelancer: nothing of the organisation")
fop = Fr.get(B + D, params={"kind": "invoice", "status": "open", "client_id": FC}).json()
check(len(fop["docs"]) == 12, f"freelancer: the open invoices of the client ({len(fop['docs'])})")
cur = A.get(B + D, params={"kind": "invoice", "limit": 1}).json()["next_cursor"]
far = Fr.get(B + D, params={"kind": "invoice", "before": f"2099-01-01,{10 ** 9}"}).json()["docs"]
check(len(far) == 12 and not {d["id"] for d in far} & set(ids), "freelancer: a cursor does not open the organisation")
check(cur, "a cursor exists for the organisation")

sys.exit(done("p2369_a_api"))
