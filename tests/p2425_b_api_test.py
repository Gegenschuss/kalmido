#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.425.0 B (#3451) API tests: recurring providers of the bank bookings, own container (start.sh, org encryption on). Invented
companies, accounts and figures only; every statement / document is made here. tenant-matrix: office  freelancer-matrix: office
 - found by rhythm: monthly with an IBAN (3+ bookings, one skipped month allowed), monthly by name without an IBAN; a single
   booking and two bookings of one shop are no provider; the portal link suggested for a known name
 - the hint "Invoice <provider> <month> missing": only for open bookings older than the days (default 5, set 7 -> the one of
   six days ago goes), shown in GET /api/office/bank/noreceipt (missing) and bundled into the ONE reminder task (its text,
   the portal link), no task of its own; a provider switched off: no hint, its bookings stay on the list
 - "No receipt needed": its bookings leave the list and the counter (the reminder's count follows), taken back: there again
 - portal: https only (400 else), a provider neither found nor set: 404, bad days: 400
 - a document that comes later (recognised again after its amount / date were set): exactly one fitting booking of a
   provider -> matched by itself (payment day = the booking's day, no person); a second open receipt of the same amount
   around it -> only a receipt, the booking stays open and suggests it; a booking of no provider is never matched
 - rights: a member 403, another organisation sees none of it; a person without organisation (personal office) the same
usage: p2425_b_api_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time
from datetime import date, timedelta

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
from kt import FAILS, OKS, check, sess, until, B, H, DATA  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
KEY = base64.b64encode(os.urandom(32)).decode()
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
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


if not os.environ.get("KMT_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,office,clients,docs"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
O = "/api/office"
K = O + "/bank"
NR = K + "/noreceipt"
V = K + "/vendors"
TODAY = testclock.today()
d = lambda n: (TODAY - timedelta(days=n)).isoformat()
MON = lambda day: f"{MONTHS[date.fromisoformat(day).month - 1]} {day[:4]}"
IBAN_ACCT = "DE02120300000000202051"
IBAN_SOFT = "DE44500105175407324931"
for s, name in ((A, "Beispiel Film GmbH"), (Ca, "Andere Firma GmbH")):
    s.put(B + O + "/settings", json={"company_fields": {"name": name, "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"}})


def ntry(amt, day, ref, name, iban=""):
    acct = f"<CdtrAcct><Id><IBAN>{iban}</IBAN></Id></CdtrAcct>" if iban else ""
    return (f'<Ntry><Amt Ccy="EUR">{amt}</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{day}</Dt></BookgDt>'
            f'<AcctSvcrRef>{ref}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>{name}</Nm></Pty></Cdtr>{acct}</RltdPties>'
            f'<RmtInf><Ustrd>Buchung {ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>')


def camt(acct, close_day, entries):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>STMT-{acct[-4:]}</Id>
<Acct><Id><IBAN>{acct}</IBAN></Id><Ccy>EUR</Ccy></Acct><Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">1000.00</Amt>
<CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{close_day}</Dt></Dt></Bal>{"".join(entries)}</Stmt></BkToCstmrStmt></Document>"""


def imp(s, text, name):
    r = s.post(B + K + "/import", json={"text": text, "filename": name})
    assert r.status_code == 201, r.text
    return r.json()


SOFT = "Adobe Systems Beispiel Ltd"  # monthly, with IBAN, one month skipped (d 95 -> 35 = two periods)
TEL = "Telefon Beispiel AG"  # monthly, no IBAN
FEE = "Kontoentgelt Beispielbank"  # monthly fee, later "no receipt needed"
imp(A, camt(IBAN_ACCT, d(1), [ntry("29.99", d(124), "S-0", SOFT, IBAN_SOFT), ntry("29.99", d(95), "S-1", SOFT, IBAN_SOFT), ntry("29.99", d(35), "S-2", SOFT, IBAN_SOFT),
                              ntry("29.99", d(6), "S-3", SOFT, IBAN_SOFT),
                              ntry("40.00", d(70), "T-1", TEL), ntry("40.00", d(40), "T-2", TEL), ntry("40.00", d(10), "T-3", TEL),
                              ntry("5.00", d(62), "F-1", FEE), ntry("5.00", d(32), "F-2", FEE), ntry("5.00", d(2), "F-3", FEE),
                              ntry("77.00", d(20), "E-1", "Einmal Haendler Beispiel"),
                              ntry("12.00", d(50), "M-1", "Markt Beispiel"), ntry("12.00", d(20), "M-2", "Markt Beispiel")]), "konto.xml")
TX = {t["purpose"]: t for t in A.get(B + K + "/tx?state=all").json()["items"]}
check(len(TX) == 13, f"thirteen bookings imported {sorted(TX)}")
tx = lambda ref: TX[f"Buchung {ref}"]["id"]

# ---------------------------------------------------------------- found by rhythm
j = A.get(B + V).json()
vs = {v["name"]: v for v in j["items"]}
check(set(vs) == {SOFT, TEL, FEE}, f"three providers: monthly with IBAN, by name, the fee; no single booking, no shop twice {sorted(vs)}")
sv, tv = vs.get(SOFT, {}), vs.get(TEL, {})
check(sv.get("kind") == "iban" and sv.get("match") == IBAN_SOFT and sv.get("every") == "month" and sv.get("count") == 4
      and sv.get("last_day") == d(6) and sv.get("amount") == "29.99" and sv.get("active") is True and sv.get("noreceipt") is False, f"provider with IBAN {sv}")
check(sv.get("portal", "").startswith("https://") and "adobe" in sv.get("portal", "") and sv.get("portal_suggested") is True, f"known name: portal suggested {sv}")
check(tv.get("kind") == "cp" and tv.get("every") == "month" and tv.get("portal") == "" and tv.get("portal_suggested") is False, f"provider by name {tv}")
check(j["days"] == 5 and j["days_default"] == 5, f"days: default 5 {j['days']}")

# ---------------------------------------------------------------- the hints
def missing():
    return {h["id"]: h for h in A.get(B + NR).json()["missing"]}


m = missing()
check(set(m) == {tx("S-0"), tx("S-1"), tx("S-2"), tx("S-3"), tx("T-1"), tx("T-2"), tx("T-3"), tx("F-1"), tx("F-2")},
      f"hints: open provider bookings older than 5 days (not the fee of 2 days ago, no single booking) {sorted(m)}")
h = m.get(tx("S-3"), {})
check(h.get("text") == f"Invoice {SOFT} {MON(d(6))} missing" and h.get("portal") == sv.get("portal") and h.get("amount") == "29.99" and h.get("day") == d(6),
      f"hint text with month and portal {h}")
check(A.get(B + NR + "?dir=in").json()["missing"] == [], "money in: no hints")
check(A.put(B + V + "/settings", json={"days": 7}).ok and tx("S-3") not in missing() and tx("T-3") in missing(), "days 7: the booking of six days ago waits")
check(A.put(B + V + "/settings", json={"days": 5}).json()["days"] == 5 and tx("S-3") in missing(), "days back to 5")
for bad in (-1, 91, "5", True, None):
    check(A.put(B + V + "/settings", json={"days": bad}).status_code == 400, f"days {bad!r}: 400")
A.put(B + O + "/settings", json={"bank_vendors": {"days": 30}})
check(A.get(B + V).json()["days"] == 5, "the general settings route ignores bank_vendors")

# switched off: no hint, the bookings stay on the list
r = A.put(B + V, json={"kind": "cp", "match": tv["match"], "active": False})
check(r.ok and not any(v["active"] for v in r.json()["items"] if v["name"] == TEL), "provider switched off " + r.text[:200])
check(not {tx("T-1"), tx("T-2"), tx("T-3")} & set(missing()) and tx("T-3") in [t["id"] for t in A.get(B + NR).json()["items"]],
      "switched off: no hint, the booking still without a receipt")
check(A.put(B + V, json={"kind": "cp", "match": tv["match"], "active": True}).ok and tx("T-3") in missing(), "switched on again: the hint is back")

# "no receipt needed": off the list and the counter
cnt0 = A.get(B + NR + "/count").json()["out"]
fv = vs[FEE]
r = A.put(B + V, json={"kind": fv["kind"], "match": fv["match"], "noreceipt": True})
check(r.ok, "no receipt needed " + r.text[:200])
items = [t["id"] for t in A.get(B + NR).json()["items"]]
check(not {tx("F-1"), tx("F-2"), tx("F-3")} & set(items) and A.get(B + NR + "/count").json()["out"] == cnt0 - 3,
      f"no receipt needed: its bookings leave the list and the counter {cnt0}")
check(not {tx("F-1"), tx("F-2")} & set(missing()), "no receipt needed: no hint")
check(A.put(B + V, json={"kind": fv["kind"], "match": fv["match"], "noreceipt": False}).ok and A.get(B + NR + "/count").json()["out"] == cnt0,
      "taken back: the bookings are there again")
A.put(B + V, json={"kind": fv["kind"], "match": fv["match"], "noreceipt": True})

# portal, unknown provider, bad input
check(A.put(B + V, json={"kind": "iban", "match": IBAN_SOFT, "portal": "http://portal.example.com"}).status_code == 400, "portal: http 400")
check(A.put(B + V, json={"kind": "iban", "match": IBAN_SOFT, "portal": "javascript:alert(1)"}).status_code == 400, "portal: script 400")
r = A.put(B + V, json={"kind": "iban", "match": IBAN_SOFT, "portal": "https://portal.example.com/rechnungen"})
sv2 = next((v for v in r.json().get("items", []) if v["name"] == SOFT), {}) if r.ok else {}
check(sv2.get("portal") == "https://portal.example.com/rechnungen" and sv2.get("portal_suggested") is False and sv2.get("stored") is True, f"portal saved {sv2}")
check(missing().get(tx("S-3"), {}).get("portal") == "https://portal.example.com/rechnungen", "the hint carries the own portal")
check(A.put(B + V, json={"kind": "cp", "match": "einmal haendler beispiel", "active": False}).status_code == 404, "a booking of no provider: 404")
check(A.put(B + V, json={"kind": "x", "match": "a"}).status_code == 400 and A.put(B + V, json={"kind": "iban", "match": IBAN_SOFT, "active": "no"}).status_code == 400,
      "bad kind / flag: 400")
check(sql("SELECT match, portal FROM office_bank_vendors WHERE org_id=? AND kind='iban'", (ORG,))[0][0] != IBAN_SOFT, "match / portal encrypted at rest")

# ---------------------------------------------------------------- bundled into the ONE reminder task
r = A.put(B + NR + "/reminder", json={"every": "month"})
check(r.ok and r.json()["task"], "reminder on " + r.text[:200])
rt = sql("SELECT id, title, content FROM tasks WHERE created_by=? AND deleted_at IS NULL AND url LIKE ?", (ALICE, "%#office/bank/norc"))
body = rt[0][2] if rt else ""
check(len(rt) == 1, f"one reminder task, no task per provider {rt}")
check(f"Invoice {SOFT} {MON(d(6))} missing" in body and "(https://portal.example.com/rechnungen)" in body and f"Invoice {TEL} {MON(d(10))} missing" in body,
      "the task lists the missing invoices with the portal link")
check(FEE not in body, "no line for a provider that needs no receipt")
check(rt and rt[0][1] == f"{A.get(B + NR + '/count').json()['out']} bookings without a receipt", f"title = count without the fee {rt}")
# 2.425.0 (#3451 review): a note the person writes into the reminder's text stays through the next run (only the title follows)
if rt:
    A.patch(B + f"/api/tasks/{rt[0][0]}", json={"content": body + "\n\nNote: ask the accountant first"})
    run = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\n"
                          "from kalmido.office.banknorc import bnr_area\nc = connect()\nwith system_ctx(c):\n    bnr_area(c, %d)\nc.close()\n" % ORG],
                         capture_output=True, text=True)
    rt2 = sql("SELECT content FROM tasks WHERE id=?", (rt[0][0],))
    check(rt2 and rt2[0][0].endswith("Note: ask the accountant first") and f"Invoice {SOFT}" in rt2[0][0],
          f"the person's note in the reminder stays after a run {run.stderr[-300:]} {rt2}")

# ---------------------------------------------------------------- the document that comes later
WSO = f"org:{ORG}"


def doc(name, amount, day, text="Rechnung"):
    r = A.post(B + "/api/docs", data={"ws": WSO}, files={"files": (name, tiny_pdf(text), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    until(lambda: (sql("SELECT state FROM doc_meta WHERE node_id=?", (nid,)) or [["wait"]])[0][0] in ("done", "failed"), 30)
    r = A.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day})
    assert r.ok, r.text
    return nid


def redo(nid):
    assert A.post(B + f"/api/docs/{nid}/redo").ok
    return until(lambda: (sql("SELECT state FROM doc_meta WHERE node_id=?", (nid,)) or [["wait"]])[0][0] in ("done", "failed"), 40)


def txrow(ref):
    return sql("SELECT match_kind, match_id, matched_by FROM office_bank_tx WHERE id=?", (tx(ref),))[0]


# exactly one booking fits: matched by itself
n1 = doc("adobe-rechnung.pdf", "29.99", d(7), "Rechnung Adobe Systems Beispiel")
redo(n1)
ok1 = until(lambda: txrow("S-3")[0] == "receipt", 30)
check(ok1 and txrow("S-3")[1] == n1 and txrow("S-3")[2] is None, f"one fitting booking: matched by itself, by no person {txrow('S-3')}")
if not ok1:  # what the server said about it
    lg = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    print([x for x in (lg.stdout + lg.stderr).splitlines() if "bank provider" in x or "recognition" in x][-10:])
    print(A.get(B + f"/api/docs/{n1}").text[:600])
    print(subprocess.run(["docker", "exec", CT, "python", "-c", "import app, traceback\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\n"
                          "from kalmido.office import bankvend as bv\nc = connect()\ntry:\n    with system_ctx(c):\n        print('hooked', bv.bv_on_done in bv.doc_on_done, bv.bv_autolink(c, %d))\n"
                          "except Exception:\n    traceback.print_exc()\nc.rollback()" % n1], capture_output=True, text=True))
    print(sql("SELECT state, doc_date, currency, sender_id FROM doc_meta WHERE node_id=?", (n1,)), sql("SELECT name FROM fs_nodes WHERE id=?", (n1,)))
check([tuple(x) for x in sql("SELECT paid_at FROM rc_receipts WHERE node_id=?", (n1,))] == [(d(6),)], "the receipt has the booking's day as payment day")
check(txrow("S-2")[0] is None and txrow("S-1")[0] is None and txrow("S-0")[0] is None, "the older bookings of the provider stay open")
check(tx("S-3") not in missing(), "the hint is gone")

# a second receipt of the same amount around it: only a suggestion
n2 = doc("telefon-rechnung-a.pdf", "40.00", d(12), "Rechnung Telefon Beispiel")
check(A.put(B + f"/api/docs/{n2}/receipt", json={"keep": True}).ok, "a first receipt of the same amount, not recognised again")
n3 = doc("telefon-rechnung-b.pdf", "40.00", d(11), "Rechnung Telefon Beispiel Nr 2")
redo(n3)
time.sleep(1)
check(txrow("T-3")[0] is None, f"two receipts fit: the booking stays open {txrow('T-3')}")
check(sql("SELECT 1 FROM rc_receipts WHERE node_id=?", (n3,)) != [], "it became a receipt of the office")
sug = next((t for t in A.get(B + K + "/tx?state=open").json()["items"] if t["id"] == tx("T-3")), {}).get("suggestions", [])
check({n2, n3} & {s["id"] for s in sug}, f"the booking suggests the receipts {sug}")

# a booking of no provider is never matched
n4 = doc("einmal-haendler-rechnung.pdf", "77.00", d(20), "Rechnung Einmal Haendler Beispiel")
redo(n4)
time.sleep(1)
check(txrow("E-1")[0] is None, "a single booking (no provider): never matched by itself")

# ---------------------------------------------------------------- rights
check(Bo.get(B + V).status_code == 403 and Bo.put(B + V, json={"kind": "iban", "match": IBAN_SOFT, "active": False}).status_code == 403
      and Bo.put(B + V + "/settings", json={"days": 3}).status_code == 403, "a member: 403")
check(Ca.get(B + V).json()["items"] == [] and Ca.get(B + NR).json()["missing"] == [], "another organisation sees no provider")
check(Ca.put(B + V, json={"kind": "iban", "match": IBAN_SOFT, "active": False}).status_code == 404, "another organisation: a provider of Alpha 404")

# ---------------------------------------------------------------- a person without organisation (personal office)
# freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.put(B + O + "/settings", json={"company_fields": {"name": "Frida Film", "street": "Weg 3", "zip": "10115", "city": "Berlin", "country": "DE"}})
imp(Fr, camt("DE12500105170648489890", d(1), [ntry("9.99", d(68), "P-1", "Speicher Beispiel"), ntry("9.99", d(38), "P-2", "Speicher Beispiel"),
                                             ntry("9.99", d(8), "P-3", "Speicher Beispiel")]), "f.xml")
j = Fr.get(B + V).json()
check([v["name"] for v in j["items"]] == ["Speicher Beispiel"] and len(Fr.get(B + NR).json()["missing"]) == 3, f"freelancer: own provider and hints {j}")
fv = j["items"][0] if j["items"] else {}
check(Fr.put(B + V, json={"kind": fv.get("kind"), "match": fv.get("match"), "noreceipt": True}).ok and Fr.get(B + NR + "/count").json()["out"] == 0,
      "freelancer: no receipt needed")
check(SOFT in [v["name"] for v in A.get(B + V).json()["items"]] and "Speicher Beispiel" not in [v["name"] for v in A.get(B + V).json()["items"]],
      "the freelancer's providers never reach the organisation")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
