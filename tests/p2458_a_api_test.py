#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.458.0 (#3839) office lists over 500 documents: the server sorts before it cuts, like the list in the browser sorts.
Invented data only, as a person without an organisation.
 - no sort: the newest 500 as ever
 - client, amount, name, date in both directions; the rows without a value stay last in both directions
 - natural order and no case in the names ("Rec 9" before "Rec 10"); a delivery note has no amount
 - a derived status (open) takes the same order before it cuts
usage: p2458_a_api_test.py <datadir>"""
# freelancer-matrix: office
import json
import sys

import kt
from kt import B, check, dbx
from freelancer_fixture import freelancer

kt.fresh(prefix="P2458A")
A = kt.setup()
FID, Fr = freelancer(B, A)
r = Fr.get(B + "/api/office/docs?kind=invoice")
check(r.ok, "the own office answers " + r.text[:120])
OID = r.json()["org_id"]
TOT = 520


def fill(kind, n):
    for i in range(1, n + 1):
        rec = json.dumps({"name": f"client {i}" if i % 10 else "", "lines": []})
        tot = json.dumps({"net": i, "gross": i * 2})
        dbx("INSERT INTO office_docs(org_id, kind, number, status, lang, currency, recipient, date, project_title, due_date, rights, fields, totals, "
            "created_by, created_at, updated_at, locked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (OID, kind, f"{kind[:2].upper()}-{i}", "issued" if kind == "invoice" else "draft", "en", "EUR", rec, f"20{10 + i % 16}-01-{1 + i % 28:02d}",
             f"Rec {i}" if i % 3 else "", "2020-01-01", "{}", "[]", tot, FID, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
             "2026-01-01T00:00:00+00:00" if kind == "invoice" else None))


def docs(kind, q=""):
    r = Fr.get(B + f"/api/office/docs?kind={kind}{q}")
    check(r.ok, f"{kind}{q}: answers " + r.text[:120])
    return r.json()["docs"]


fill("invoice", TOT)
fill("delivery", TOT)
fill("offer", TOT)

d0 = docs("offer")
check(len(d0) == 500 and d0[0]["date"] >= d0[-1]["date"], "no sort: 500, the newest first")
d = docs("offer", "&sort=amount&dir=desc")
check(len(d) == 500 and d[0]["net"] == TOT and d[1]["net"] == TOT - 1, f"the largest of all {TOT}, the old cut would not have them: {d[0]['net']}")
d = docs("offer", "&sort=amount&dir=asc")
check(d[0]["net"] == 1 and d[1]["net"] == 2 and d[499]["net"] == 500, "the smallest first")
d = docs("invoice", "&sort=amount&dir=desc")
check(d[0]["gross"] == TOT * 2, "invoices by the gross amount")

d = docs("offer", "&sort=client&dir=asc")
names = [x["recipient_name"] for x in d]
check(names[:3] == ["client 1", "client 2", "client 3"] and names[8:10] == ["client 9", "client 11"], f"natural order, ascending: {names[:10]}")
d = docs("offer", "&sort=client&dir=desc")
check(d[0]["recipient_name"] == "client 519", "descending: " + d[0]["recipient_name"])
FULL = docs("offer", "&sort=name&dir=desc")
check(FULL[0]["project_title"] == "Rec 520" and FULL[1]["project_title"] == "Rec 518", "name: the project title, natural: " + FULL[0]["project_title"])
d = docs("offer", "&sort=name&dir=asc")
check(d[0]["number"] == "OF-3" and d[1]["number"] == "OF-6" and d[1]["project_title"] == "", "name: a row without a title goes by its number: " + str(d[0]["number"]))

# rows without a value: last in both directions (more of them than fit: 52 of 520 have no client)
dbx("UPDATE office_docs SET recipient=? WHERE org_id=? AND kind='offer' AND number NOT IN ('OF-1', 'OF-2', 'OF-3')", (json.dumps({"name": ""}), OID))
for dr in ("asc", "desc"):
    d = docs("offer", f"&sort=client&dir={dr}")
    check([x["number"] for x in d[:3]] == (["OF-1", "OF-2", "OF-3"] if dr == "asc" else ["OF-3", "OF-2", "OF-1"]) and not d[3]["recipient_name"], f"{dr}: the rows without a client stay last")

d = docs("delivery", "&sort=amount&dir=desc")
check(len(d) == 500, "a delivery note has no amount: the list still answers")
d = docs("invoice", "&status=open&sort=amount&dir=desc")
check(len(d) == 500 and d[0]["gross"] == TOT * 2, f"a derived status: the same order before the cut {d[0]['gross']}")
check(docs("offer", "&sort=nonsense") and docs("offer", "&sort=nonsense")[0]["date"] == d0[0]["date"], "an unknown sort: the newest first")

sys.exit(kt.done("p2458_a_api"))
