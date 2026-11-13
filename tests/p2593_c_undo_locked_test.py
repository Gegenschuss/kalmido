#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.593.0 Teil C (#4864): the undo of an account import never takes a document the import brought as finalised (locked_at
set, also long before the import): it stays with its client, its positions, its import log entries and its stored PDF;
the plan (GET /api/imports/<id>/undo-plan) names it under "stays" and counts it as the undo does. Invented names only
(example.com); the person is one without an organisation (freelancer-matrix: office), the office is the personal one.
 - the import (8 days ago) recorded: invoice 1 (finalised 9 days ago, client 1, one position, its log entries, its PDF),
   invoice 2 (a draft, client 2, its PDF); every row unchanged since
 - the plan: kept_final names the finalised document and its client, kept_final_docs 1, kept_rows as the undo says
 - the undo: invoice 1, client 1, the position, the log entries and the PDF stay; invoice 2, its log entries and its PDF are
   gone
 - review F7: the office's number counter (office_numbers, recorded by the import) stays with the finalised invoice, the plan
   names it ("Number ranges"); the next invoice gets the number after it, the series does not start again below it
usage: p2593_c_undo_locked_test.py <datadir>"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

D = "/api/office/docs"


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


def ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(timespec="seconds")


def in_app(code):
    """Lines of Python inside the container; prints the JSON of `out`."""
    head = "import json, os\nimport app\nfrom kalmido.core.config import OFFICE_DIR\n"
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", kt.CT, "python", "-c", head + code + "\nprint('OUT' + json.dumps(out))"],
                       capture_output=True, text=True, timeout=200)
    for line in r.stdout.splitlines():
        if line.startswith("OUT"):
            return json.loads(line[3:])
    raise AssertionError(r.stdout[-800:] + r.stderr[-1500:])


OLD = ago(days=9)


def backdate(table, where, args):
    """Every time column of the rows that holds a value to OLD: they look unchanged since the import of 8 days ago."""
    # 2.1112.2 (#5987): + the TIMESTAMPTZ columns (created_at / updated_at / deleted_at since #5306): left out, the draft looked
    # changed since the import and stayed; '' is no point in time, so only the text columns compare with it
    cols = [r for r in kt.dbx("SELECT column_name, data_type FROM information_schema.columns WHERE table_name=? "
                              "AND data_type IN ('text', 'timestamp with time zone')", (table,))
            if r[0].endswith("_at") or r[0] == "at"]
    for k, typ in cols:
        empty = f" AND {k}!=''" if typ == "text" else ""
        kt.dbx(f"UPDATE {table} SET {k}=? WHERE ({where}) AND {k} IS NOT NULL{empty}", (OLD, *args))


def kids(table, ids):
    """[(child table, id)] of the rows with a foreign key on table.id in ids (as the import would have recorded them),
    backdated; a child without an id column is backdated only."""
    out = []
    refs = kt.dbx("SELECT cl.relname, a.attname FROM pg_constraint con JOIN pg_class cl ON cl.oid=con.conrelid "
                  "JOIN pg_class rf ON rf.oid=con.confrelid JOIN pg_attribute a ON a.attrelid=con.conrelid AND a.attnum=con.conkey[1] "
                  "WHERE con.contype='f' AND rf.relname=? AND array_length(con.conkey,1)=1", (table,))
    for ct, cc in refs:
        q = f"{cc} IN ({','.join('?' * len(ids))})"
        backdate(ct, q, ids)
        if one("SELECT 1 FROM information_schema.columns WHERE table_name=? AND column_name='id'", (ct,)):
            out += [(ct, x[0]) for x in kt.dbx(f"SELECT id FROM {ct} WHERE {q}", ids)]
    return out


kt.fresh(prefix="P2593C")
A = kt.setup()
FID, Fr = freelancer(B, A)
check(Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Studio Beispiel", "street": "Hafenweg 2", "zip": "12345",
                                                                  "city": "Musterstadt", "iban": "DE02120300000000202051",
                                                                  "tax_number": "12/345/67890"},
                                               "lang": "en", "currency": "EUR"}).ok, "office settings")
CL = [Fr.post(B + "/api/clients", json={"name": f"Kunde {n}", "email": f"kunde{n}@example.com", "street": "Musterweg 1", "zip": "12345",
                                        "city": "Musterstadt"}).json()["id"] for n in (1, 2)]
INV = []
for t, cl in (("Eins", CL[0]), ("Zwei", CL[1])):
    r = Fr.post(B + D, json={"kind": "invoice", "client_id": cl, "project_title": t, "service_from": "2026-05-01",
                             "items": [{"title": "Beratung", "qty": 1, "rate": 300}]})
    check(r.status_code in (200, 201), f"invoice {t} {r.text[:200]}")
    INV.append(r.json().get("id"))
I1, I2 = INV
r = Fr.post(B + f"{D}/{I1}/finalize")
check(r.ok and r.json().get("locked"), f"invoice 1 finalised {r.status_code} {r.text[:300]}")
OID = one("SELECT org_id FROM office_docs WHERE id=?", (I1,))
ITEM = one("SELECT id FROM office_doc_items WHERE doc_id=?", (I1,))
LOG1 = [x[0] for x in kt.dbx("SELECT id FROM office_doc_log WHERE doc_id=?", (I1,))]
LOG2 = [x[0] for x in kt.dbx("SELECT id FROM office_doc_log WHERE doc_id=?", (I2,))]
check(ITEM and LOG1 and LOG2, f"setup: a position and log entries {ITEM} {LOG1} {LOG2}")
backdate("office_docs", "id IN (?, ?)", INV)
backdate("clients", "id IN (?, ?)", CL)
backdate("office_doc_log", "doc_id IN (?, ?)", INV)
MORE = sorted({*kids("office_docs", INV), *kids("clients", CL)} - {("office_docs", I1), ("office_docs", I2)})
check(("office_doc_items", ITEM) in MORE, f"setup: the position is recorded {MORE}")
check(one("SELECT locked_at FROM office_docs WHERE id=?", (I1,)) == OLD, "setup: invoice 1 was finalised before the import")

j = in_app(f"""
d = os.path.join(OFFICE_DIR, str({OID}))
os.makedirs(d, exist_ok=True)
out = {{}}
for k, i in (("p1", {I1}), ("p2", {I2})):
    p = os.path.realpath(os.path.join(d, f"doc{{i}}-p2593.pdf"))
    with open(p, "wb") as fh:
        fh.write(b"invented")
    out[k] = p
""")
P1, P2 = j["p1"], j["p2"]
NUMS = kt.dbx("SELECT kind, period FROM office_numbers WHERE org_id=?", (OID,))
check(NUMS, "setup: the office has a number counter")
kt.dbx("UPDATE office_numbers SET last=41 WHERE org_id=?", (OID,))  # as the import brought it (review F7)
oi = [["clients", CL[0], OID], ["clients", CL[1], OID], ["office_docs", I1, OID], ["office_docs", I2, OID]] \
    + [[t, i, OID] for t, i in MORE] + [["office_doc_log", i, OID] for i in LOG1 + LOG2] \
    + [["office_numbers", {"org_id": OID, "kind": k, "period": pd}, OID] for k, pd in NUMS]
created = {"tasks": [], "oi": oi, "oi_files": [P1, P2], "oi_file_rows": {P1: [["office_docs", I1]], P2: [["office_docs", I2]]}}
IMP = one("INSERT INTO imports(user_id, source, file_name, created, report, created_at) VALUES(?,?,?,?,?,?) RETURNING id",
          (FID, "Kalmido", "datei.zip", json.dumps(created), "{}", ago(days=8)))

# ---------------------------------------------------------------- the plan names what stays and counts it as the undo
r = Fr.get(B + f"/api/imports/{IMP}/undo-plan")
p = r.json() if r.ok else {}
check(r.ok, f"the plan {r.status_code} {r.text[:300]}")
kf = {x["what"]: x["count"] for x in p.get("kept_final") or []}
# 2.593.0 (#4864): review F7 - the number counter stays with it
check(kf == {"Finalised documents": 1, "Clients": 1, "Number ranges": len(NUMS)} and p.get("kept_final_docs") == 1,
      f"the plan names the finalised invoice and its client under 'stays' {p}")
check((p.get("kept_rows") or 0) >= 2, f"the plan counts them among what stays {p}")
check(sum(x["count"] for x in p.get("for_good") or []) >= 1, f"the draft goes for good {p}")

# ---------------------------------------------------------------- the undo
r = Fr.post(B + f"/api/imports/{IMP}/undo")
u = r.json() if r.ok else {}
check(r.ok, f"the undo {r.status_code} {r.text[:300]}")
check(u.get("kept_rows") == p.get("kept_rows") and u.get("kept_final_docs") == 1, f"the undo counts what stays as the plan did {u} {p}")
check(one("SELECT locked_at FROM office_docs WHERE id=?", (I1,)) == OLD, "the finalised invoice stays")
check(one("SELECT deleted_at FROM clients WHERE id=?", (CL[0],)) in (None, ""), "its client stays (not in the trash)")
check(one("SELECT client_id FROM office_docs WHERE id=?", (I1,)) == CL[0], "the invoice still names its client")
check(one("SELECT 1 FROM office_doc_items WHERE id=?", (ITEM,)), "its position stays")
check(len(kt.dbx(f"SELECT id FROM office_doc_log WHERE id IN ({','.join('?' * len(LOG1))})", LOG1)) == len(LOG1), "its log entries stay")
check(not one("SELECT 1 FROM office_docs WHERE id=?", (I2,)), "the draft is gone")
check(not kt.dbx(f"SELECT id FROM office_doc_log WHERE id IN ({','.join('?' * len(LOG2))})", LOG2), "the draft's log entries are gone")
j = in_app(f"out = {{'p1': os.path.exists({P1!r}), 'p2': os.path.exists({P2!r})}}")
check(j["p1"] and not j["p2"], f"the PDF of the finalised invoice stays, the draft's goes {j}")
check(Fr.get(B + f"{D}/{I1}").ok, "the finalised invoice still opens")

# ---------------------------------------------------------------- review F7: the number series goes on after the invoice that stays
check(sorted(x[0] for x in kt.dbx("SELECT last FROM office_numbers WHERE org_id=?", (OID,))) == [41] * len(NUMS),
      "review F7: the office's number counter stays")
r = Fr.post(B + D, json={"kind": "invoice", "client_id": CL[0], "project_title": "Drei", "service_from": "2026-06-01",
                         "items": [{"title": "Beratung", "qty": 1, "rate": 100}]})
I3 = r.json().get("id") if r.status_code in (200, 201) else None
r = Fr.post(B + f"{D}/{I3}/finalize")
check(I3 and r.ok and r.json().get("locked"), f"a new invoice is finalised {r.status_code} {r.text[:300]}")
check(max(x[0] for x in kt.dbx("SELECT last FROM office_numbers WHERE org_id=?", (OID,))) == 42
      and one("SELECT number FROM office_docs WHERE id=?", (I3,)) != one("SELECT number FROM office_docs WHERE id=?", (I1,)),
      "review F7: the next invoice gets the number after the counter that stayed")

sys.exit(kt.done("p2593_c_undo_locked"))
