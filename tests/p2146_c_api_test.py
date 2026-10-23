#!/usr/bin/env python3
"""2.146.0 API tests, part C (#2469 CAMT.052 day reports, #2455 the household import), own container (start.sh, org
encryption on). Invented accounts, names and figures only: every statement (CAMT.052 / .053 XML, CSV, ZIP) is made here.
freelancer-matrix: office, personal
tenant-matrix: office, budget
 - #2469 office (a person without organisation, its own admin): two CAMT.052 day reports in one upload -- a pending entry
   (Sts PDNG, and Sts/Cd PDNG of camt.052.001.08) is shown apart and never imported; the same AcctSvcrRef in both files
   counts once; a pending entry booked in the next report (other day, other text, the same EndToEndId) is imported once;
   EndToEndId NOTPROVIDED is no reference; the references are kept as keyed hashes only; a CAMT.053 of the same booking
   with another day and text is found again by its reference; camt052 tells the dialog to recommend CAMT.053
 - #2455 shared reader: the S/H mark column (guessed next to the amount, by its name, the Volksbank layout with S/H),
   an unreadable mark = an error row, DD-MM-YYYY and YYYYMMDD
 - #2455 household (the person without organisation in its private space, and an organisation's member): several files and
   a ZIP in one multipart parse, pending rows apart and refused on commit, duplicates across files by reference, a CSV row
   with the counterpart IBAN found again in a CAMT file with another text (day + amount + IBAN), more than 3000 rows read
   and taken over in two parts under one run, 20001 rows refused; an import run listed and taken back (an entry changed
   after the import is named and kept, then deleted when asked); another person gets 404 on the list's runs
usage: p2146_c_api_test.py <datadir>"""
import base64
import io
import os
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,home,budget,contracts"
K = "/api/office/bank"
IBAN1, IBAN2, IBAN3 = "DE02120300000000202051", "DE89370400440532013000", "DE75512108001245126199"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


if not (os.environ.get("P2146C_NOSTART") or os.environ.get("KMT_NOSTART")):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A, features=FEAT)  # freelancer-matrix: office, personal (the personal office + the private budget)


# ---------------------------------------------------------------- statements made here
def ntry(amt, ind, day, sts="BOOK", svc=None, e2e=None, name="Shop Example", iban=IBAN2, text="Purchase", v8=False):
    st = f"<Sts><Cd>{sts}</Cd></Sts>" if v8 else f"<Sts>{sts}</Sts>"
    side, acct = ("Dbtr", "DbtrAcct") if ind == "CRDT" else ("Cdtr", "CdtrAcct")
    return (f'<Ntry><Amt Ccy="EUR">{amt}</Amt><CdtDbtInd>{ind}</CdtDbtInd>{st}<BookgDt><Dt>{day}</Dt></BookgDt><ValDt><Dt>{day}</Dt></ValDt>'
            + (f"<AcctSvcrRef>{svc}</AcctSvcrRef>" if svc else "")
            + "<NtryDtls><TxDtls>" + (f"<Refs><EndToEndId>{e2e}</EndToEndId></Refs>" if e2e else "")
            + f"<RltdPties><{side}><Nm>{name}</Nm></{side}><{acct}><Id><IBAN>{iban}</IBAN></Id></{acct}></RltdPties>"
            + f"<RmtInf><Ustrd>{text}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>")


def c052(rid, entries, v8=False):
    ns = "camt.052.001.08" if v8 else "camt.052.001.02"
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<Document xmlns="urn:iso:std:iso:20022:tech:xsd:{ns}"><BkToCstmrAcctRpt><Rpt><Id>{rid}</Id>'
            f'<Acct><Id><IBAN>{IBAN1}</IBAN></Id><Ccy>EUR</Ccy></Acct>{"".join(entries)}</Rpt></BkToCstmrAcctRpt></Document>')


def c053(entries):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>S-1</Id>'
            f'<Acct><Id><IBAN>{IBAN1}</IBAN></Id><Ccy>EUR</Ccy></Acct>{"".join(entries)}</Stmt></BkToCstmrStmt></Document>')


def zipped(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files:
            z.writestr(name, text)
    return b.getvalue()


def up(s, url, files, **form):
    fl = [("files", (n, d if isinstance(d, bytes) else d.encode(), "application/octet-stream")) for n, d in files]
    return s.post(B + url, files=fl, data=form)


# day report 1: R1 booked (bank reference), P1 pending (EndToEndId only), X1 booked without any reference (NOTPROVIDED)
D1 = c052("R-1", [ntry("12.50", "DBIT", "2026-09-01", svc="REF-A1", e2e="E2E-A1", text="Bakery"),
                  ntry("30.00", "DBIT", "2026-09-01", sts="PDNG", e2e="E2E-P1", name="Fuel Example", text="Card pending"),
                  ntry("7.00", "DBIT", "2026-09-01", e2e="NOTPROVIDED", name="Kiosk Example", text="Paper")])
# day report 2 (camt.052.001.08, Sts/Cd): R1 again (other text), P1 now booked (other day, other text, its bank reference),
# P2 pending, X2 = another 7.00 without reference on another day
D2 = c052("R-2", [ntry("12.50", "DBIT", "2026-09-02", sts="BOOK", svc="REF-A1", e2e="E2E-A1", text="Bakery 2 Sep", v8=True),
                  ntry("30.00", "DBIT", "2026-09-02", sts="BOOK", svc="REF-P1", e2e="E2E-P1", name="Fuel Example", text="Fuel station", v8=True),
                  ntry("55.00", "DBIT", "2026-09-02", sts="PDNG", e2e="E2E-P2", text="Pending order", v8=True),
                  ntry("7.00", "DBIT", "2026-09-02", sts="BOOK", e2e="NOTPROVIDED", name="Kiosk Example", text="Paper", v8=True)], v8=True)

# ================================================================ #2469 office
Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Beispiel Studio", "street": "Weg 1", "zip": "12345", "city": "Musterstadt",
                                                              "country": "DE"}})
r = up(Fr, K + "/import/preview", [("tag1.xml", D1), ("tag2.xml", D2)])
check(r.ok, "office: two day reports in one preview " + r.text[:300])
p = r.json() if r.ok else {}
rows = p.get("rows") or []
pend = [x for x in rows if x.get("pending")]
check(len(pend) == 2 and {x["amount"] for x in pend} == {"-30.00", "-55.00"}, f"office: the two pending entries are marked (PDNG and Sts/Cd PDNG) {pend}")
check(p.get("pending_count") == 2 and p.get("count") == 4 and p.get("dup_count") == 1 and p.get("camt052") is True,
      f"office: 4 new (R1, X1, P1 booked, X2), R1 of the second report a duplicate, 2 pending, camt052 {[p.get(k) for k in ('count', 'dup_count', 'pending_count', 'camt052')]}")
r1 = [x for x in rows if x["amount"] == "-12.50"]
check(len(r1) == 2 and [x["dup"] for x in sorted(r1, key=lambda x: x["day"])] == [False, True], "office: the same AcctSvcrRef in the next report counts once")
p1 = [x for x in rows if x["amount"] == "-30.00"]
check(sorted((x["pending"], x["dup"]) for x in p1) == [(False, False), (True, False)], f"office: P1 pending in report 1, booked in report 2 = one new booking {p1}")
x7 = [x for x in rows if x["amount"] == "-7.00"]
check(len(x7) == 2 and not any(x["dup"] for x in x7), "office: NOTPROVIDED is no reference (two kiosk payments on two days stay two)")
r = up(Fr, K + "/import", [("tag1.xml", D1), ("tag2.xml", D2)])
check(r.status_code == 201 and r.json().get("count") == 4 and r.json().get("pending_count") == 2, "office: imported 4, pending left out " + r.text[:200])
IMP = r.json()["import"]["id"] if r.status_code == 201 else 0
tx = sql("SELECT ref, rkeys FROM office_bank_tx WHERE import_id=?", (IMP,))
check(len(tx) == 4 and sum(1 for t in tx if t[1]) == 2 and not any("REF-" in (t[1] or "") or "E2E" in (t[1] or "") for t in tx),
      f"office: reference keys stored as hashes only ({[(t[0], len(t[1] or '')) for t in tx]})")
check(not sql("SELECT 1 FROM office_bank_tx WHERE import_id=? AND rkeys LIKE ?", (IMP, "%E2E-P2%")), "office: nothing of a pending entry stored")
r = up(Fr, K + "/import/preview", [("tag2.xml", D2)])
j = r.json()
check(r.ok and j["count"] == 0 and j["dup_count"] == 3 and j["pending_count"] == 1, f"office: the second report again: all there, the pending one apart {j.get('count')} {j.get('dup_count')}")
# a CAMT.053 statement of P1 with another day and text: the bank reference finds it again
S3 = c053([ntry("30.00", "DBIT", "2026-09-03", svc="REF-P1", text="FUEL 0815", name="Fuel Example AG")])
j = up(Fr, K + "/import/preview", [("auszug.xml", S3)]).json()
check(j.get("dup_count") == 1 and j.get("count") == 0 and j.get("camt052") is False, f"office: CAMT.053, other day and text, same reference = there already {j.get('rows')}")
# take back + restore: a booking imported again meanwhile by its reference stays away
check(Fr.post(B + K + f"/imports/{IMP}/undo").ok, "office: the import taken back")
r = up(Fr, K + "/import", [("auszug.xml", S3)])
check(r.status_code == 201 and r.json()["count"] == 1, "office: P1 again from the statement while the day reports are taken back")
r = Fr.post(B + K + f"/imports/{IMP}/restore")
check(r.ok and r.json()["item"]["count"] == 3, f"office: restored without P1 twice ({r.json().get('item', {}).get('count') if r.ok else r.text[:100]})")
# another area never sees the references of this one
j = up(A, K + "/import/preview", [("tag1.xml", D1)]).json()
check(j.get("count") == 2 and j.get("dup_count") == 0, f"office: the organisation's office has its own references {j.get('count')} {j.get('dup_count')}")

# ================================================================ #2455 the shared reader: S/H, date formats
VB = ("Buchungstag;Valuta;Auftraggeber/Zahlungsempfänger;Empfänger/Zahlungspflichtiger;Konto-Nr.;IBAN;BLZ;BIC;Vorgang/Verwendungszweck;"
      "Kundenreferenz;Währung;Umsatz;\n"
      f"03.09.2026;03.09.2026;Ich;Supermarket Example;;{IBAN2};;;Groceries;;EUR;45,20;S\n"
      f"04.09.2026;04.09.2026;Ich;Employer Example;;{IBAN3};;;Salary September;;EUR;2.000,00;H\n"
      "05.09.2026;05.09.2026;Ich;Odd Example;;;;;Unknown;;EUR;9,99;X\n")
r = Fr.post(B + K + "/import/preview", json={"text": VB, "filename": "vb.csv"})
g = r.json().get("guess") or {}
check(r.ok and g.get("preset") == "volksbank_sh" and g.get("amount") == 11 and g.get("sign") == 12, f"the Volksbank layout with S/H: the mark column {g}")
r = Fr.post(B + K + "/import/preview", json={"text": VB, "filename": "vb.csv", "mapping": g})
rows = r.json().get("rows") or []
check(r.ok and [x["amount"] for x in rows[:2]] == ["-45.20", "2000.00"] and rows[2]["error"], f"office CSV: S = out, H = in, X = an error row {[(x['amount'], x['error']) for x in rows]}")
check(rows and rows[0]["iban"] == IBAN2, "office CSV: the counterpart's IBAN column")
L = Fr.post(B + "/api/budget/lists", json={}).json()["list_id"]
r = Fr.post(B + f"/api/budget/{L}/import/parse", json={"text": VB})
gb = r.json().get("guess") or {}
check(r.ok and gb.get("sign") == 12, f"budget: the same guess (one reader) {gb}")
rows = Fr.post(B + f"/api/budget/{L}/import/parse", json={"text": VB, "mapping": gb}).json()["rows"]
check([(x["amount"], x["kind"]) for x in rows[:2]] == [(45.2, "out"), (2000.0, "in")] and rows[2]["error"], f"budget: S = expense, H = income {rows}")
SH = "Datum;Text;Betrag;Soll/Haben\n01-09-2026;Rent;800,00;Soll\n02-09-2026;Refund;20,00;Haben\n"
g2 = Fr.post(B + f"/api/budget/{L}/import/parse", json={"text": SH}).json()["guess"]
check(g2.get("sign") == 3 and g2.get("date_format") == "DD-MM-YYYY", f"a column named Soll/Haben + DD-MM-YYYY {g2}")
rows = Fr.post(B + f"/api/budget/{L}/import/parse", json={"text": SH, "mapping": g2}).json()["rows"]
check([(x["day"], x["kind"]) for x in rows] == [("2026-09-01", "out"), ("2026-09-02", "in")], f"Soll = out, Haben = in {rows}")
YM = "Date;Text;Amount\n20260907;Coffee;-3.50\n20260908;Coffee;-3.50\n"
g3 = Fr.post(B + f"/api/budget/{L}/import/parse", json={"text": YM}).json()["guess"]
check(g3.get("date_format") == "YYYYMMDD" and g3.get("sign") is None, f"YYYYMMDD, no mark column {g3}")
rows = Fr.post(B + f"/api/budget/{L}/import/parse", json={"text": YM, "mapping": g3}).json()["rows"]
check([x["day"] for x in rows] == ["2026-09-07", "2026-09-08"], "YYYYMMDD read")

# ================================================================ #2455 #2469 household: several files, a ZIP, pending, runs
L = Fr.post(B + "/api/budget/lists", json={}).json()["list_id"]
r = up(Fr, f"/api/budget/{L}/import/parse", [("berichte.zip", zipped([("tag1.xml", D1), ("tag2.xml", D2), ("readme.pdf", "x")]))])
check(r.ok, "budget: a ZIP of day reports " + r.text[:300])
j = r.json() if r.ok else {}
rows = j.get("rows") or []
check(j.get("files") == 2 and j.get("camt052") is True and j.get("pending") == 2 and "readme.pdf" in (j.get("skipped_files") or []),
      f"budget: two reports from the ZIP, the PDF skipped, 2 pending {[j.get(k) for k in ('files', 'pending', 'skipped_files')]}")
check([x["day"] for x in rows] == sorted(x["day"] for x in rows) and {x["file"] for x in rows} == {"tag1.xml", "tag2.xml"}, "budget: one list by day, with the file")
take = [x for x in rows if not x["error"] and not x["pending"] and not x["dup"]]
check(len(take) == 4 and sum(1 for x in rows if x["dup"]) == 1, f"budget: 4 to take over, R1 of report 2 a duplicate {[(x['title'], x['dup'], x['pending']) for x in rows]}")
body = [{k: x[k] for k in ("day", "amount", "kind", "title", "counterpart", "iban", "ref", "e2e", "fi")} for x in take]
pr = next(x for x in rows if x["pending"])
r = Fr.post(B + f"/api/budget/{L}/import/commit", json={"rows": [{k: pr[k] for k in ("day", "amount", "kind", "title", "pending")}]})
check(r.status_code == 400, "budget: a pending row is refused on commit")
r = Fr.post(B + f"/api/budget/{L}/import/commit", json={"rows": body, "label": "berichte.zip", "fmt": "camt"})
check(r.status_code == 201 and r.json()["created"] == 4 and len(r.json().get("run") or "") == 16, "budget: 4 created under one run " + r.text[:200])
RUN = r.json().get("run")
ek = sql("SELECT rkeys, ikey, import_run FROM budget_entries WHERE list_id=?", (L,))
check(len(ek) == 4 and all(x[2] == RUN and x[1] for x in ek) and not any("REF-" in x[0] or "E2E" in x[0] for x in ek),
      "budget: run, IBAN key and reference keys stored, never the references themselves")
j = up(Fr, f"/api/budget/{L}/import/parse", [("tag2.xml", D2)]).json()
check([x["dup"] for x in j["rows"] if not x["pending"]] == [True, True, True], f"budget: report 2 again -- every booked row there already {j['rows']}")
j = up(Fr, f"/api/budget/{L}/import/parse", [("auszug.xml", S3)]).json()
check(j["rows"][0]["dup"] is True, "budget: the CAMT.053 of P1 (other day, other text) = there already by its reference")
# a CSV of the same account (counterpart IBAN column, other text) and a CAMT file: day + amount + IBAN
CSV = f"Buchungstag;Verwendungszweck;Betrag;IBAN\n05.09.2026;LASTSCHRIFT Strom;-61,00;{IBAN3}\n06.09.2026;Card;-4,00;\n"
gc = Fr.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV}).json()["guess"]
rows = Fr.post(B + f"/api/budget/{L}/import/parse", json={"text": CSV, "mapping": gc}).json()["rows"]
check(rows[0]["iban"] == IBAN3, "budget CSV: the IBAN column read")
r = Fr.post(B + f"/api/budget/{L}/import/commit", json={"rows": [{k: x[k] for k in ("day", "amount", "kind", "title", "counterpart", "iban")} for x in rows]})
check(r.status_code == 201 and r.json()["created"] == 2, "budget: the CSV taken over " + r.text[:100])
RUN2 = r.json().get("run")
S4 = c053([ntry("61.00", "DBIT", "2026-09-05", svc="REF-S1", name="Stadtwerke Example", iban=IBAN3, text="Strom Abschlag 09/2026")])
j = up(Fr, f"/api/budget/{L}/import/parse", [("auszug.xml", S4)]).json()
check(j["rows"][0]["dup"] is True, "budget: the CAMT booking with another text = the CSV row (day + amount + IBAN)")
# the runs: listed, an edited entry named and kept, then deleted when asked
j = Fr.get(B + f"/api/budget/{L}/import/runs").json()
check([x["id"] for x in j["items"]][:2] == [RUN2, RUN] and j["items"][1]["count"] == 4 and j["items"][1]["left"] == 4 and j["items"][1]["label"] == "berichte.zip",
      f"budget: the runs, newest first {j}")
eid = sql("SELECT id FROM budget_entries WHERE list_id=? AND import_run=? ORDER BY id LIMIT 1", (L, RUN))[0][0]
time.sleep(1.1)
check(Fr.patch(B + f"/api/budget/entries/{eid}", json={"title": "Bakery (checked)"}).ok, "budget: one imported entry changed")
check(Fr.get(B + f"/api/budget/{L}/import/runs").json()["items"][1]["edited"] == 1, "budget: the run counts the changed entry")
r = Fr.post(B + f"/api/budget/{L}/import/runs/{RUN}/undo", json={})
j = r.json()
check(r.ok and j["deleted"] == 3 and [e["title"] for e in j["kept"]] == ["Bakery (checked)"], f"budget: taken back, the changed entry named and kept {j}")
check(sql("SELECT COUNT(*) FROM budget_entries WHERE list_id=? AND import_run=?", (L, RUN))[0][0] == 1, "budget: exactly that run's entries went")
check(sql("SELECT COUNT(*) FROM budget_entries WHERE list_id=? AND import_run=?", (L, RUN2))[0][0] == 2, "budget: the other run stays")
r = Fr.post(B + f"/api/budget/{L}/import/runs/{RUN}/undo", json={"edited": "delete"})
check(r.ok and r.json()["deleted"] == 1 and not sql("SELECT 1 FROM budget_entries WHERE import_run=?", (RUN,)), "budget: the changed one too when asked")
check(Fr.post(B + f"/api/budget/{L}/import/runs/0123456789abcdef/undo", json={}).status_code == 404
      and Fr.post(B + f"/api/budget/{L}/import/runs/..%2Fx/undo", json={}).status_code == 404, "budget: an unknown run 404")
check(Ca.get(B + f"/api/budget/{L}/import/runs").status_code in (403, 404) and Ca.post(B + f"/api/budget/{L}/import/runs/{RUN2}/undo", json={}).status_code in (403, 404)
      and sql("SELECT COUNT(*) FROM budget_entries WHERE import_run=?", (RUN2,))[0][0] == 2, "budget: another person never reaches the runs")

# more than 3000 rows: read, taken over in two parts under one run; 20001 refused
BIG = "Datum;Text;Betrag\n" + "".join(f"{1 + i % 28:02d}.09.2026;Row {i};-1,00\n" for i in range(3001))
gb = Fr.post(B + f"/api/budget/{L}/import/parse", json={"text": BIG}).json()["guess"]
r = Fr.post(B + f"/api/budget/{L}/import/parse", json={"text": BIG, "mapping": gb})
check(r.ok and len(r.json()["rows"]) == 3001, "budget: 3001 rows read (2.146.0: no longer refused) " + r.text[:120])
rows = [{k: x[k] for k in ("day", "amount", "kind", "title")} for x in r.json().get("rows", [])]
r1 = Fr.post(B + f"/api/budget/{L}/import/commit", json={"rows": rows[:3000], "label": "big.csv"})
r2 = Fr.post(B + f"/api/budget/{L}/import/commit", json={"rows": rows[3000:], "run": r1.json().get("run")}) if r1.ok else r1
check(r1.status_code == 201 and r2.status_code == 201 and r1.json()["run"] == r2.json()["run"] and r1.json()["created"] + r2.json()["created"] == 3001,
      "budget: two parts, one run " + r2.text[:150])
it = next((x for x in Fr.get(B + f"/api/budget/{L}/import/runs").json()["items"] if x["id"] == r1.json().get("run")), {})
check(it.get("count") == 3001 and it.get("left") == 3001, f"budget: the run counts both parts {it}")
check(Fr.post(B + f"/api/budget/{L}/import/commit", json={"rows": rows[:1], "run": "ffffffffffffffff"}).status_code == 400, "budget: an unknown run on commit: 400")
check(Fr.post(B + f"/api/budget/{L}/import/runs/{it.get('id')}/undo", json={}).json().get("deleted") == 3001, "budget: the big run taken back at once")
HUGE = "Datum;Text;Betrag\n" + "01.09.2026;x;-1,00\n" * 20001
check(Fr.post(B + f"/api/budget/{L}/import/parse", json={"text": HUGE, "mapping": gb}).status_code == 400, "budget: 20001 rows refused")

# an organisation's member: the same in an organisation's budget (encrypted with the organisation's key)
LO = Bo.post(B + "/api/budget/lists", json={}).json()["list_id"]
j = up(Bo, f"/api/budget/{LO}/import/parse", [("tag1.xml", D1), ("tag2.xml", D2)]).json()
take = [x for x in j.get("rows", []) if not x["error"] and not x["pending"] and not x["dup"]]
r = Bo.post(B + f"/api/budget/{LO}/import/commit", json={"rows": [{k: x[k] for k in ("day", "amount", "kind", "title", "counterpart", "iban", "ref", "e2e", "fi")} for x in take]})
check(r.status_code == 201 and r.json()["created"] == 4, "organisation budget: the same 4 " + r.text[:100])
check(all(str(x[0]).startswith("kenc1:") for x in sql("SELECT title FROM budget_entries WHERE list_id=?", (LO,))), "organisation budget: titles encrypted at rest")
check(Ca.post(B + f"/api/budget/{LO}/import/parse", json={"text": YM}).status_code in (403, 404), "organisation budget: another person 404")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
