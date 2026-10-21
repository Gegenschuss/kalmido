#!/usr/bin/env python3
"""2.90.0 API tests, part B (#1921, office: bank reconciliation), own container (start.sh, org encryption on). Invented
companies, people, accounts and figures only. tenant-matrix: office
 - import: a German CSV (account lines above the header, 1.234,56, DD.MM.YYYY) -> columns + guess, the checked rows,
   the import; the same file again = only duplicates; a CAMT.053 XML made here (credit / debit, counterpart, IBAN,
   reference, another currency refused per row); a DOCTYPE / ENTITY is refused; amounts and texts encrypted at rest
 - matching: the suggestion for money in = the open invoice (number in the purpose, same amount); match -> paid; a smaller
   booking -> partly paid; the undo removes the payment again; matched twice / too much / the wrong direction = 409;
   private / ignored; a payment deleted on the invoice opens the booking again
 - imports: the take-back is refused (409) while a booking is matched, else the bookings go and come back with restore
 - receipts (part A's bk_receipts): money out -> the receipt with the same amount; match sets its payment day, the undo
   removes it (skipped while part A is not merged into this branch)
 - rights: a member 403, another organisation 404 (booking, import, a foreign invoice / receipt), an agent 403, a person
   without organisation (personal office) uses all of it, another person sees nothing
usage: p290_b_api_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time
from datetime import timedelta

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS, SKIPS = [], [0], []


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


if not (os.environ.get("P290B_NOSTART") or os.environ.get("KMT_NOSTART")):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Frei"), ("erik", "Erik Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do, Er = sess("bob"), sess("carol"), sess("dora"), sess("erik")
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo, Ca, Do, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
O = "/api/office"
D = O + "/docs"
K = O + "/bank"
TODAY = testclock.today()
DAY = [(TODAY - timedelta(days=n)).isoformat() for n in range(0, 40)]
de = lambda iso: f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
for s, name in ((A, "Beispiel Film GmbH"), (Ca, "Andere Firma GmbH"), (Do, "Dora Film")):
    s.put(B + O + "/settings", json={"company_fields": {"name": name, **COMPANY}})


def invoice(s, client, rate):
    r = s.post(B + D, json={"kind": "invoice", "client_id": client, "service_from": DAY[30], "items": [{"title": "Schnitt", "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    j = r.json()
    return {"id": did, "number": j["number"], "gross": j["totals"]["gross"]}


def doc(s, did):
    return s.get(B + f"{D}/{did}").json()


CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Weg 2", "zip": "10115", "city": "Berlin", "country": "DE"}).json()["id"]
I1 = invoice(A, CL, 1000)
I2 = invoice(A, CL, 500)
check(float(I1["gross"]) == 1190 and float(I2["gross"]) == 595 and I1["number"], f"two finalised invoices {I1} {I2}")

CSV = ("Kontoinhaber;Beispiel Film GmbH\nKonto;DE02120300000000202051\n\n"
       "Buchungstag;Valuta;Auftraggeber/Empfänger;Verwendungszweck;IBAN;Betrag\n"
       f"{de(DAY[3])};{de(DAY[3])};Kunde Eins GmbH;Rechnung {I1['number']} vielen Dank;DE89370400440532013000;1.190,00\n"
       f"{de(DAY[2])};{de(DAY[2])};Kunde Eins GmbH;Abschlag;DE89370400440532013000;300,00\n"
       f"{de(DAY[5])};{de(DAY[5])};Software Beispiel GmbH;Abo Oktober;;-119,00\n"
       f"{de(DAY[1])};{de(DAY[1])};Bäckerei Beispiel;Brötchen;;-4,50\n"
       "kein Datum;;Jemand;Text;;12,00\n")

# ---------------------------------------------------------------- CSV import
r = A.post(B + K + "/import/preview", json={"text": CSV, "filename": "konto.csv"})
j = r.json()
g = j.get("guess") or {}
check(r.ok and j["fmt"] == "csv" and j["columns"][0] == "Buchungstag" and len(j["sample"]) == 5, "csv: columns and sample below the account lines " + r.text[:200])
check((g.get("date"), g.get("amount"), g.get("title"), g.get("counterpart"), g.get("decimal"), g.get("date_format")) == (0, 5, 3, 2, ",", "DD.MM.YYYY"), f"csv: the guess {g}")
MAP = {k: g.get(k) for k in ("date", "amount", "amount_in", "amount_out", "title", "counterpart", "decimal", "date_format")}
r = A.post(B + K + "/import/preview", json={"text": CSV, "filename": "konto.csv", "mapping": MAP})
j = r.json()
rows = j.get("rows") or []
check(r.ok and j["count"] == 4 and j["dup_count"] == 0 and j["skipped"] == 1 and [x["amount"] for x in rows[:4]] == ["1190.00", "300.00", "-119.00", "-4.50"]
      and rows[0]["day"] == DAY[3] and rows[0]["iban"] == "DE89370400440532013000" and rows[0]["counterpart"] == "Kunde Eins GmbH" and rows[4]["error"],
      "csv: the checked rows (German amounts and dates, IBAN, an unreadable row) " + r.text[:300])
check(sql("SELECT COUNT(*) FROM office_bank_tx")[0][0] == 0, "csv: the preview stores nothing")
check(A.post(B + K + "/import", json={"text": CSV, "filename": "konto.csv"}).status_code == 400, "csv: the import needs the mapping")
r = A.post(B + K + "/import", json={"text": CSV, "filename": "konto.csv", "mapping": MAP})
check(r.status_code == 201 and r.json()["count"] == 4 and r.json()["skipped"] == 1, "csv: imported " + r.text[:200])
IMP1 = r.json()["import"]["id"]
r = A.post(B + K + "/import", json={"text": CSV, "filename": "konto.csv", "mapping": MAP})
check(r.status_code == 201 and r.json()["count"] == 0 and r.json()["dup_count"] == 4, "csv: the same file again = duplicates only " + r.text[:200])
enc = sql("SELECT amount, counterpart, purpose, iban FROM office_bank_tx WHERE org_id=? AND iban IS NOT NULL", (ORG,))
check(enc and all(str(v).startswith("kenc1:") for row in enc for v in row), f"csv: amount, counterpart, purpose, IBAN encrypted at rest {enc[:1]}")

j = A.get(B + K + "/tx").json()
TX = {t["purpose"]: t for t in j["items"]}
check(len(j["items"]) == 4 and j["counts"] == {"open": 4, "matched": 0} and j["items"][0]["day"] == DAY[1], f"tx: four open bookings, newest first {j.get('counts')}")
t1, t2, t3, t4 = TX[f"Rechnung {I1['number']} vielen Dank"], TX["Abschlag"], TX["Abo Oktober"], TX["Brötchen"]
s1 = t1["suggestions"]
check(s1 and s1[0]["kind"] == "invoice" and s1[0]["id"] == I1["id"] and len(s1) <= 3, f"suggest: the invoice whose number is in the purpose first {s1}")
check(t2["suggestions"] and all(x["kind"] == "invoice" for x in t2["suggestions"]), f"suggest: a part payment of the customer offers its invoices {t2['suggestions']}")
check(not any(x["kind"] == "invoice" for x in t3["suggestions"]), "suggest: money out never offers an invoice")

# ---------------------------------------------------------------- matching invoices
r = A.post(B + f"{K}/tx/{t1['id']}/match", json={"kind": "invoice", "id": I1["id"]})
check(r.ok and r.json()["match"]["kind"] == "invoice" and r.json()["match"]["id"] == I1["id"] and I1["number"] in r.json()["match"]["label"], "match: booking -> invoice " + r.text[:200])
d1 = doc(A, I1["id"])
check(d1["status"] == "paid" and d1["open"] == "0.00" and d1["payments"][0]["date"] == DAY[3] and d1["payments"][0]["method"] == "transfer",
      f"match: the invoice is paid on the booking day {d1.get('status')} {d1.get('payments')}")
check(A.post(B + f"{K}/tx/{t1['id']}/match", json={"kind": "private"}).status_code == 409, "match: a matched booking is refused (409)")
r = A.post(B + f"{K}/tx/{t2['id']}/match", json={"kind": "invoice", "id": I2["id"]})
d2 = doc(A, I2["id"])
check(r.ok and d2["state"] == "partial" and d2["open"] == "295.00", f"match: a smaller booking = partly paid {d2.get('state')} {d2.get('open')}")
r = A.post(B + f"{K}/tx/{t2['id']}/unmatch")
d2 = doc(A, I2["id"])
check(r.ok and r.json()["was"] == {"kind": "invoice", "id": I2["id"]} and r.json()["item"]["match"] is None and d2["open"] == "595.00"
      # 2.152.0 (#2168): the payment is reversed (a second line with the negative amount), not deleted
      and len(d2["payments"]) == 2 and d2["payments"][1]["reverses_id"] == d2["payments"][0]["id"] and sum(float(p["amount"]) for p in d2["payments"]) == 0,
      "unmatch: the payment is reversed, the booking open again " + r.text[:200])
check(A.post(B + f"{K}/tx/{t2['id']}/unmatch").status_code == 409, "unmatch: an open booking is refused (409)")
check(A.post(B + f"{K}/tx/{t2['id']}/match", json={"kind": "invoice", "id": I2["id"]}).ok and doc(A, I2["id"])["open"] == "295.00", "match again (the redo)")
check(A.post(B + f"{K}/tx/{t3['id']}/match", json={"kind": "invoice", "id": I2["id"]}).status_code == 409, "match: money out cannot pay an invoice (409)")
check(A.post(B + f"{K}/tx/{t4['id']}/match", json={"kind": "invoice", "id": 999999}).status_code == 404, "match: an unknown invoice is 404")
check(A.post(B + f"{K}/tx/{t4['id']}/match", json={"kind": "nonsense"}).status_code == 400, "match: an unknown kind is 400")
r = A.post(B + f"{K}/tx/{t4['id']}/match", json={"kind": "private"})
check(r.ok and r.json()["match"]["kind"] == "private", "match: private")
j = A.get(B + K + "/tx?state=matched").json()
check({t["id"] for t in j["items"]} == {t1["id"], t2["id"], t4["id"]} and j["counts"] == {"open": 1, "matched": 3}, f"tx: the filter matched {j.get('counts')}")
check(len(A.get(B + K + "/tx?state=all").json()["items"]) == 4 and A.get(B + K + "/tx?state=x").status_code == 400, "tx: the filter all / a wrong filter")
check(len(A.get(B + K + f"/tx?state=all&from={DAY[3]}&to={DAY[2]}").json()["items"]) == 2, "tx: from / to")
# a payment deleted on the invoice opens the booking again
pid = doc(A, I1["id"])["payments"][0]["id"]
check(A.delete(B + f"{D}/{I1['id']}/payments/{pid}").ok, "the payment is deleted on the invoice")
check(any(t["id"] == t1["id"] for t in A.get(B + K + "/tx").json()["items"]), "match: the booking is open again after its payment went")
check(A.post(B + f"{K}/tx/{t1['id']}/match", json={"kind": "invoice", "id": I1["id"]}).ok, "match: matched again")
c = A.get(B + f"{K}/tx/{t3['id']}/candidates").json()["items"]
check(all(x["kind"] != "invoice" for x in c), "candidates: money out lists no invoices")

# ---------------------------------------------------------------- CAMT
CAMT = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>STMT-1</Id>
<Ntry><Amt Ccy="EUR">1000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{DAY[4]}</Dt></BookgDt><ValDt><Dt>{DAY[4]}</Dt></ValDt>
<AcctSvcrRef>REF-0001</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Dbtr><Pty><Nm>Kunde Eins GmbH</Nm></Pty></Dbtr><DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct></RltdPties>
<RmtInf><Ustrd>Teilzahlung</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="EUR">59.50</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{DAY[6]}</Dt></BookgDt><AcctSvcrRef>REF-0002</AcctSvcrRef>
<NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>Druckerei Beispiel</Nm></Pty></Cdtr><CdtrAcct><Id><IBAN>DE75512108001245126199</IBAN></Id></CdtrAcct></RltdPties>
<RmtInf><Ustrd>Flyer</Ustrd><Ustrd>Auftrag 77</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="USD">10.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>{DAY[6]}</Dt></BookgDt></Ntry>
</Stmt></BkToCstmrStmt></Document>"""
r = A.post(B + K + "/import/preview", json={"text": CAMT, "filename": "auszug.xml"})
j = r.json()
rows = j.get("rows") or []
check(r.ok and j["fmt"] == "camt" and j["count"] == 2 and j["skipped"] == 1 and rows[0]["amount"] == "1000.00" and rows[0]["counterpart"] == "Kunde Eins GmbH"
      and rows[0]["iban"] == "DE89370400440532013000" and rows[0]["ref"] == "REF-0001" and rows[1]["amount"] == "-59.50" and rows[1]["counterpart"] == "Druckerei Beispiel"
      and rows[1]["purpose"] == "Flyer Auftrag 77" and rows[2]["error"], "camt: credit / debit, counterpart, IBAN, reference, another currency refused " + r.text[:400])
# 2.90.0 (#1921, review): a declared ISO-8859-1 encoding does not garble umlauts (the client sends text); 0.004 is no amount
L1 = CAMT.replace('encoding="UTF-8"', 'encoding="ISO-8859-1"').replace("Kunde Eins GmbH", "Müller Größe").replace(">59.50<", ">0.004<")
j = A.post(B + K + "/import/preview", json={"text": L1, "filename": "latin.xml"}).json()
rows = j.get("rows") or []
check(rows and rows[0]["counterpart"] == "Müller Größe" and rows[1]["error"], f"camt: declared ISO-8859-1 keeps umlauts, 0.004 refused {str(rows)[:300]}")
BAD = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "boom">]><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><Ntry>&e;</Ntry></Document>'
check(A.post(B + K + "/import/preview", json={"text": BAD}).status_code == 400 and A.post(B + K + "/import", json={"text": BAD}).status_code == 400, "camt: DOCTYPE / ENTITY refused")
check(A.post(B + K + "/import/preview", json={"text": '<Document xmlns="urn:camt.053"><Ntry'}).status_code == 400, "camt: broken XML is 400")
check(A.post(B + K + "/import/preview", json={"text": "x" * (2 * 1024 * 1024 + 10)}).status_code in (400, 413), "import: larger than 2 MB refused")
r = A.post(B + K + "/import", json={"text": CAMT, "filename": "auszug.xml"})
check(r.status_code == 201 and r.json()["count"] == 2 and r.json()["import"]["fmt"] == "camt", "camt: imported " + r.text[:200])
IMP2 = r.json()["import"]["id"]
T5 = next(t for t in A.get(B + K + "/tx").json()["items"] if t["purpose"] == "Teilzahlung")
check(A.post(B + f"{K}/tx/{T5['id']}/match", json={"kind": "invoice", "id": I2["id"]}).status_code == 409, "match: more than the open rest is refused (409)")

# ---------------------------------------------------------------- import undo
check(A.post(B + f"{K}/imports/{IMP1}/undo").status_code == 409, "imports: the take-back is refused while bookings are matched (409)")
r = A.post(B + f"{K}/imports/{IMP2}/undo")
check(r.ok and r.json()["item"]["undone_at"] and not any(t["purpose"] in ("Teilzahlung", "Flyer Auftrag 77") for t in A.get(B + K + "/tx?state=all").json()["items"]),
      "imports: taken back, its bookings are gone " + r.text[:200])
check(A.post(B + f"{K}/imports/{IMP2}/undo").status_code == 409, "imports: twice is 409")
r = A.post(B + f"{K}/imports/{IMP2}/restore")
check(r.ok and r.json()["item"]["undone_at"] is None and r.json()["item"]["count"] == 2 and sum(1 for t in A.get(B + K + "/tx").json()["items"] if t["purpose"] in ("Teilzahlung", "Flyer Auftrag 77")) == 2,
      "imports: restore brings them back (the undo) " + r.text[:200])
imps = A.get(B + K + "/imports").json()["items"]
check([i["id"] for i in imps][:3] == [IMP2, IMP1 + 1, IMP1] and imps[0]["filename"] == "auszug.xml", f"imports: the list, newest first {imps[:3]}")

# ---------------------------------------------------------------- receipts (part A)
nid = None
r = A.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files={"files": ("abo.pdf", tiny_pdf("Software Abo"), "application/pdf")})
if r.ok:
    jj = r.json()
    nid = (jj.get("ids") or [x["id"] for x in jj.get("docs") or jj.get("items") or []] or [None])[0]
RC_READY = bool(nid) and A.put(B + f"/api/docs/{nid}", json={"amount": "119.00", "date": DAY[5]}).ok \
    and A.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "vat_pct": "19"}).ok
if not RC_READY:
    SKIPS.append("receipts: part A (bk_receipts, rc_receipts.vat_pct / paid_at) is not in this branch yet")
    print("SKIP:", SKIPS[-1], flush=True)
else:
    t3 = next(t for t in A.get(B + K + "/tx").json()["items"] if t["id"] == t3["id"])
    check(t3["suggestions"] and t3["suggestions"][0] == {**t3["suggestions"][0], "kind": "receipt", "id": nid}, f"receipt: money out suggests the receipt with the same amount {t3['suggestions']}")
    c = A.get(B + f"{K}/tx/{t3['id']}/candidates").json()["items"]
    check(any(x["kind"] == "receipt" and x["id"] == nid for x in c), "candidates: the receipt")
    r = A.post(B + f"{K}/tx/{t3['id']}/match", json={"kind": "receipt", "id": nid})
    check(r.ok and r.json()["match"]["kind"] == "receipt" and sql("SELECT paid_at FROM rc_receipts WHERE node_id=?", (nid,))[0][0] == DAY[5], "receipt: match sets its payment day " + r.text[:200])
    t6 = next(t for t in A.get(B + K + "/tx").json()["items"] if t["purpose"] == "Flyer Auftrag 77")
    check(A.post(B + f"{K}/tx/{t6['id']}/match", json={"kind": "receipt", "id": nid}).status_code == 409, "receipt: matched with another booking already (409)")
    r = A.post(B + f"{K}/tx/{t3['id']}/unmatch")
    check(r.ok and sql("SELECT paid_at FROM rc_receipts WHERE node_id=?", (nid,))[0][0] is None, "receipt: the undo removes the payment day")
    check(A.post(B + f"{K}/tx/{t3['id']}/match", json={"kind": "receipt", "id": nid}).ok, "receipt: matched again")

# ---------------------------------------------------------------- rights
check(all(x.status_code == 403 for x in (Bo.get(B + K + "/tx"), Bo.post(B + K + "/import/preview", json={"text": CSV}), Bo.post(B + K + "/import", json={"text": CAMT}),
                                          Bo.post(B + f"{K}/tx/{t4['id']}/unmatch"), Bo.post(B + f"{K}/tx/{T5['id']}/match", json={"kind": "ignored"}),
                                          Bo.get(B + K + "/imports"), Bo.post(B + f"{K}/imports/{IMP2}/undo"))), "rights: a member gets 403 everywhere")
check(Ca.get(B + K + "/tx?state=all").json()["items"] == [] and Ca.get(B + K + "/imports").json()["items"] == [], "rights: another organisation sees nothing")
check(all(x.status_code == 404 for x in (Ca.post(B + f"{K}/tx/{T5['id']}/match", json={"kind": "ignored"}), Ca.post(B + f"{K}/tx/{t1['id']}/unmatch"),
                                          Ca.get(B + f"{K}/tx/{T5['id']}/candidates"), Ca.post(B + f"{K}/imports/{IMP2}/undo"), Ca.post(B + f"{K}/imports/{IMP2}/restore"))),
      "rights: another organisation reaches no booking / import (404)")
r = Ca.post(B + K + "/import", json={"text": CAMT, "filename": "c.xml"})
check(r.status_code == 201 and r.json()["count"] == 2 and r.json()["dup_count"] == 0, "rights: duplicates are counted per office area " + r.text[:160])
CT = Ca.get(B + K + "/tx").json()["items"]
ct_in = next(t for t in CT if float(t["amount"]) > 0)
ct_out = next(t for t in CT if float(t["amount"]) < 0)
check(Ca.post(B + f"{K}/tx/{ct_in['id']}/match", json={"kind": "invoice", "id": I2["id"]}).status_code == 404 and doc(A, I2["id"])["open"] == "295.00",
      "rights: an invoice of another organisation cannot be matched (404)")
check(not any(s["id"] in (I1["id"], I2["id"]) for s in ct_in["suggestions"]) and Ca.get(B + f"{K}/tx/{ct_in['id']}/candidates").json()["items"] == [],
      "rights: no foreign invoice among suggestions / candidates")
if RC_READY:
    check(Ca.post(B + f"{K}/tx/{ct_out['id']}/match", json={"kind": "receipt", "id": nid}).status_code == 404, "rights: a receipt of another organisation cannot be matched (404)")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "bankbot", "display_name": "Bank Bot"})
AG = {**H, "Authorization": "Bearer " + r.json()["token"]}
check(all(x.status_code in (401, 403) for x in (requests.get(B + K + "/tx", headers=AG), requests.post(B + K + "/import", headers=AG, json={"text": CAMT}),
                                                 requests.post(B + f"{K}/tx/{T5['id']}/match", headers=AG, json={"kind": "ignored"}))), "rights: an agent gets 403")

# ---------------------------------------------------------------- personal office (person without organisation)
check(Do.get(B + O + "/settings").json().get("role") == "admin", "personal office: the person is its admin")
CLP = Do.post(B + "/api/clients", json={"name": "Privatkunde Eins", "street": "Weg 3", "zip": "10115", "city": "Berlin", "country": "DE"}).json()["id"]
PI = invoice(Do, CLP, 200)
PCSV = f"Buchungstag;Name;Verwendungszweck;Betrag\n{de(DAY[2])};Privatkunde Eins;{PI['number']};238,00\n{de(DAY[2])};Copyshop;Kopien;-12,00\n"
pv = Do.post(B + K + "/import/preview", json={"text": PCSV}).json()
r = Do.post(B + K + "/import", json={"text": PCSV, "filename": "p.csv", "mapping": {k: pv["guess"].get(k) for k in MAP}})
check(r.status_code == 201 and r.json()["count"] == 2, "personal office: import " + r.text[:200])
PT = Do.get(B + K + "/tx").json()["items"]
pin = next(t for t in PT if float(t["amount"]) > 0)
check(pin["suggestions"] and pin["suggestions"][0]["id"] == PI["id"], f"personal office: the own invoice is suggested {pin['suggestions']}")
check(Do.post(B + f"{K}/tx/{pin['id']}/match", json={"kind": "invoice", "id": PI["id"]}).ok and doc(Do, PI["id"])["status"] == "paid", "personal office: match -> paid")
check(Do.post(B + f"{K}/tx/{pin['id']}/match", json={"kind": "invoice", "id": I2["id"]}).status_code == 409, "personal office: a matched booking stays (409)")
pout = next(t for t in PT if float(t["amount"]) < 0)
check(Do.post(B + f"{K}/tx/{pout['id']}/match", json={"kind": "invoice", "id": I2["id"]}).status_code == 404, "personal office: an organisation's invoice is 404")
check(Er.get(B + K + "/tx?state=all").json()["items"] == [] and Er.post(B + f"{K}/tx/{pout['id']}/match", json={"kind": "private"}).status_code == 404
      and Er.post(B + f"{K}/tx/{pin['id']}/unmatch").status_code == 404, "personal office: another person sees and reaches nothing (404)")
check(not any(t["id"] in (pin["id"], pout["id"]) for t in A.get(B + K + "/tx?state=all").json()["items"]), "personal office: not in an organisation's list")

# 2.90.0 (#1921, review): a booking dated tomorrow cannot pay an invoice yet (409 with its own reason, not a date error)
import datetime as _dt
TOM = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()
FUT = CAMT.replace(DAY[4], TOM).replace("REF-0001", "REF-FUT1").replace("Teilzahlung", "Vorgemerkt")
Do.post(B + K + "/import", json={"text": FUT, "filename": "future.xml"})
ft = next((t for t in Do.get(B + K + "/tx").json()["items"] if t["day"] == TOM and float(t["amount"]) > 0), None)
r = Do.post(B + f"{K}/tx/{ft['id']}/match", json={"kind": "invoice", "id": PI["id"]}) if ft else None
check(ft and r.status_code == 409 and ("future" in r.text or "Zukunft" in r.text), f"future booking: match refused with its own reason {r.text[:200] if r is not None else ft}")

if SKIPS:
    print("skipped:", "; ".join(SKIPS))
print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
