#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.666.0 (#3461) API tests: the balance sheet with double-entry bookkeeping (office/ledger_dbl.py), worked out from the
documents of an example year. Own container (start.sh, org encryption on). Invented companies, people and figures only.
The year before (Y), the same in both offices: invoice A 1000.00 + 19 % paid through the bank, invoice B 500.00 + 19 % open at
the year end, receipt R1 119.00 at 19 % paid through the bank, 50.00 received on the bank without an invoice (clearing), 200.00
withdrawn into the cash box, 23.80 at 19 % out of the cash box without a receipt, a device 1200.00 net bought in January without
a receipt (capitalised, depreciated), a provision of 500.00 as an adjusting entry by hand.
 - setting: default income statement, a GmbH gets the balance sheet suggested, entries refused (409) until it is chosen, 400 on a
   wrong value; the books page names the method
 - the reports: debit = credit in the trial balance, assets = equity and liabilities, the result of the profit and loss account =
   the net income in the balance sheet = the expected figure; the balances of debtor, bank, cash, VAT, input tax, clearing
 - entries by hand: debit = credit account 400, amount 0 400, a stale version 409, CSV of the four lists
 - year-end closing: the year closes (opening entries of the next year, months locked), a second closing / this year 409, an entry
   in the closed year 409; the next year opens with the balances and the result on the profit / loss carried forward
 - SKR03 in an organisation, SKR04 for a person without an organisation (freelancer-matrix: office); a member of the
   organisation never sees it (403 / 404); the entries of another office area: 404 (tenant-matrix: office)
usage: p2666_c_bilanz_test.py <datadir>"""
import base64
import os
import sys
from decimal import Decimal

import testclock

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer, login, org_join  # noqa: E402
from kt import B, check  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"
L = O + "/books/ledger"
FEAT = "cal,comments,collab,office,clients,docs"
TODAY = testclock.today()
Y = TODAY.year - 1
D = Decimal
# the accounts of the example per chart
ACC = {"SKR03": {"bank": "1200", "cash": "1000", "vat19": "1776", "in19": "1576", "clearing": "1590", "transit": "1360",
                 "asset": "0490", "afa": "4830", "carry": "0860", "prov": "0970", "fees": "4950", "creditor": "70000"},
       "SKR04": {"bank": "1800", "cash": "1600", "vat19": "3806", "in19": "1406", "clearing": "1370", "transit": "1460",
                 "asset": "0690", "afa": "6220", "carry": "2970", "prov": "3070", "fees": "6825", "creditor": "70000"}}


def pdf(lines):
    """A PDF with a text layer, one line of text per entry (hand-written, no library)."""
    body_ = "\n".join(f"({x}) Tj T*" for x in lines)
    stream = f"BT /F1 10 Tf 12 TL 40 760 Td\n{body_}\nET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def camt(entries):
    return ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>S</Id>'
            '<Acct><Id><IBAN>DE02120300000000202051</IBAN></Id><Ccy>EUR</Ccy></Acct>' + "".join(entries) + '</Stmt></BkToCstmrStmt></Document>')


def ntry(amt, day, ref, cd="DBIT"):
    who = "Dbtr" if cd == "CRDT" else "Cdtr"
    return (f'<Ntry><Amt Ccy="EUR">{amt}</Amt><CdtDbtInd>{cd}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{day}</Dt></BookgDt><AcctSvcrRef>{ref}</AcctSvcrRef>'
            f'<NtryDtls><TxDtls><RltdPties><{who}><Pty><Nm>Partner {ref}</Nm></Pty></{who}></RltdPties><RmtInf><Ustrd>Buchung {ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>')


def doc(s, ws, name, amount, day, vat, cat):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, pdf(["Rechnung " + name]), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    kt.until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 30)
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": cat, "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def invoice(s, cl, rate, day):
    r = s.post(B + O + "/docs", json={"kind": "invoice", "client_id": cl, "project_title": f"Job {rate}", "date": day, "service_from": day,
                                       "items": [{"title": "Schnitt", "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if s.get(B + O + f"/docs/{did}").json().get("date") != day:
        assert s.patch(B + O + f"/docs/{did}", json={"date": day}).ok
    r = s.post(B + O + f"/docs/{did}/finalize")
    assert r.ok, r.text
    d = s.get(B + O + f"/docs/{did}").json()
    assert d["date"] == day, d["date"]
    return did, d["totals"]["gross"]


def acct(rep, a):
    return next((x for x in rep["susa"] if x["account"] == a), None)


def bal(rep, a):
    x = acct(rep, a)
    return D(x["balance"]) if x else D(0)


def cls(rep, k, f="balance"):
    """The sum of field f of every account of class k (the debtors: a client's customer number may be its own debtor account)."""
    return sum((D(x[f]) for x in rep["susa"] if x["class"] == k), D(0))


def bs(rep, key):
    x = next((r for r in rep["bs"] if r["key"] == key), None)
    return D(x["amount"]) if x else D(0)


def office(s, who, ws, chart):
    """The whole flow in the office s works in (an organisation or the personal office), with the chart."""
    a = ACC[chart]
    check(s.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "datev_extf": {"chart": chart},
                                           "company_fields": {"name": f"{who} Beispiel GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt",
                                                              "country": "DE", "tax_number": "12/345/67890", "iban": "DE02120300000000202051"}}).ok,
          f"{who}: office settings")
    # ---- the setting
    st = s.get(B + "/api/office/books/ledger/settings").json()
    check(st.get("method") == "euer" and st.get("suggest") == "balance" and st.get("chart") == chart,
          f"{who}: default income statement, a GmbH gets the balance sheet suggested {st}")
    check(s.post(B + "/api/office/books/ledger/entries", json={"day": f"{Y}-12-31", "debit": a["fees"], "credit": a["prov"], "amount": "1.00"}).status_code == 409,
          f"{who}: no entry while the income statement is chosen")
    check(s.put(B + "/api/office/books/ledger/settings", json={"method": "nonsense"}).status_code == 400, f"{who}: a wrong method 400")
    r = s.put(B + "/api/office/books/ledger/settings", json={"method": "balance", "size": "small"})
    check(r.ok and r.json()["method"] == "balance", f"{who}: balance sheet chosen {r.text[:200]}")
    check(s.get(B + O + "/books").json().get("ledger") == "balance", f"{who}: the books page names the method")
    # ---- the data of Y
    cl = s.post(B + "/api/clients", json={"name": f"{who} Kunde GmbH", "street": "Kundenweg 2", "zip": "54321", "city": "Kundenstadt", "country": "DE"}).json()["id"]
    ia, ga = invoice(s, cl, 1000, f"{Y}-02-10")
    ib, gb = invoice(s, cl, 500, f"{Y}-11-20")
    check(D(str(ga)) == D("1190") and D(str(gb)) == D("595"), f"{who}: the invoices {ga} {gb}")
    r1 = doc(s, ws, "r1-software.pdf", "119.00", f"{Y}-04-01", "19", "Software")
    xml = camt([ntry("1190.00", f"{Y}-03-01", "INVA", "CRDT"), ntry("119.00", f"{Y}-04-05", "R1"), ntry("200.00", f"{Y}-06-01", "CASH"),
                ntry("50.00", f"{Y}-07-01", "IN50", "CRDT")])
    r = s.post(B + O + "/bank/import", json={"text": xml, "filename": "konto.xml"})
    check(r.status_code == 201, f"{who}: bank import {r.status_code} {r.text[:200]}")
    tx = {t["purpose"].split()[-1]: t["id"] for t in s.get(B + O + "/bank/tx?state=all").json()["items"]}
    m = lambda tid, b: s.post(B + O + f"/bank/tx/{tid}/match", json=b)  # noqa: E731
    check(m(tx["INVA"], {"kind": "invoice", "id": ia}).ok, f"{who}: invoice A paid through the bank")
    check(m(tx["R1"], {"kind": "receipt", "id": r1}).ok, f"{who}: R1 paid through the bank")
    check(m(tx["CASH"], {"kind": "cash"}).ok, f"{who}: cash withdrawal")
    r = s.post(B + O + "/cashbooks", json={"name": "Handkasse", "opening": "0.00", "opening_day": f"{Y}-01-01"})
    check(r.status_code == 201, f"{who}: a cash box {r.text[:200]}")
    E = O + f"/cashbooks/{r.json()['id']}/entries"
    check(s.post(B + E, json={"day": f"{Y}-06-01", "dir": "in", "amount": "200.00", "text": "Barentnahme"}).status_code == 201, f"{who}: cash in from the bank")
    check(s.post(B + E, json={"day": f"{Y}-06-02", "dir": "out", "amount": "23.80", "vat_pct": "19", "text": "Porto", "category": "Porto"}).status_code == 201,
          f"{who}: cash out without a receipt")
    r = s.post(B + O + "/equipment", json={"name": "Kamera", "purchase_date": f"{Y}-01-15", "purchase_net": "1200", "life_months": 36})
    check(r.status_code == 201, f"{who}: a device {r.text[:200]}")
    # ---- entries by hand
    r = s.post(B + "/api/office/books/ledger/entries", json={"day": f"{Y}-12-31", "debit": a["fees"], "credit": a["prov"], "amount": "500.00", "text": "Rückstellung Abschluss"})
    check(r.status_code == 201 and r.json()["amount"] == "500.00", f"{who}: the provision {r.text[:200]}")
    prov = r.json()
    check(s.post(B + "/api/office/books/ledger/entries", json={"day": f"{Y}-12-31", "debit": a["fees"], "credit": a["fees"], "amount": "1"}).status_code == 400,
          f"{who}: debit = credit account 400")
    check(s.post(B + "/api/office/books/ledger/entries", json={"day": f"{Y}-12-31", "debit": a["fees"], "credit": a["prov"], "amount": "0"}).status_code == 400, f"{who}: amount 0 400")
    r = s.post(B + "/api/office/books/ledger/entries", json={"day": f"{Y}-12-30", "debit": a["fees"], "credit": a["prov"], "amount": "9.99", "text": "Probe"})
    tmp = r.json()
    check(s.put(B + f"/api/office/books/ledger/entries/{tmp['id']}", json={"amount": "8.00", "expect_updated_at": "2000-01-01T00:00:00+00:00"}).status_code == 409,
          f"{who}: a stale version 409")
    r = s.put(B + f"/api/office/books/ledger/entries/{tmp['id']}", json={"amount": "8.00", "expect_updated_at": tmp["updated_at"]})
    check(r.ok and r.json()["amount"] == "8.00", f"{who}: the entry changed {r.text[:200]}")
    check(s.delete(B + f"/api/office/books/ledger/entries/{tmp['id']}").ok, f"{who}: the entry deleted")

    # ---- the reports of Y
    rep = s.get(B + f"/api/office/books/ledger?year={Y}&journal=1").json()
    ch = rep.get("checks") or {}
    check(ch.get("balanced") and ch["debit"] == ch["credit"], f"{who}: trial balance debit = credit {ch}")
    check(ch.get("difference") == "0.00" and ch["assets"] == ch["liabilities"], f"{who}: assets = equity and liabilities {ch}")
    afa = sum((D(x["amount"]) for x in rep.get("journal", []) if x["src"] == "afa"), D(0))
    check(D(0) < afa <= D("400.00"), f"{who}: a depreciation of the device {afa}")
    want = D("1500.00") - D("100.00") - D("20.00") - afa - D("500.00")
    check(D(rep["result"]) == want and bs(rep, "P.A.V") == want, f"{who}: the result {rep['result']} = net income in the balance sheet {bs(rep, 'P.A.V')} = {want}")
    pl = {x["key"]: D(x["amount"]) for x in rep["pl"]}
    check(pl.get("1") == D("1500.00") and pl.get("7") == afa, f"{who}: revenue and depreciation in the profit and loss account {pl}")
    check(cls(rep, "bs:B.II.1") == D("595.00"), f"{who}: invoice B open on the debtors {[x for x in rep['susa'] if x['class'] == 'bs:B.II.1']}")
    check(bal(rep, a["bank"]) == D("921.00"), f"{who}: bank 1190 - 119 - 200 + 50 {acct(rep, a['bank'])}")
    check(bal(rep, a["cash"]) == D("176.20"), f"{who}: cash 200 - 23.80 {acct(rep, a['cash'])}")
    check(bal(rep, a["vat19"]) == D("-285.00") and bal(rep, a["in19"]) == D("22.80"), f"{who}: VAT 190 + 95, input tax 19 + 3.80")
    check(bal(rep, a["creditor"]) == 0 and bal(rep, a["transit"]) == 0, f"{who}: R1 booked and paid, the withdrawal through transit")
    check(bal(rep, a["clearing"]) == D("-1250.00"), f"{who}: clearing: 50 received + the device without receipt {acct(rep, a['clearing'])}")
    check(bal(rep, a["asset"]) == D("1200.00") - afa and bal(rep, a["afa"]) == afa, f"{who}: the device capitalised and depreciated")
    check(bs(rep, "B.II.1") == D("595.00") and bs(rep, "B.IV") == D("1097.20") and bs(rep, "P.B") == D("500.00"),
          f"{who}: receivables, cash and bank, provisions {rep['bs']}")
    check(bs(rep, "P.C.8") == D("1512.20"), f"{who}: other liabilities: VAT netted 262.20 + clearing 1250 {bs(rep, 'P.C.8')}")
    check(not rep.get("closed") and any(e["id"] == prov["id"] for e in rep.get("entries", [])), f"{who}: the provision listed, the year open")
    for what in ("susa", "pl", "bs", "journal"):
        r = s.get(B + f"/api/office/books/ledger/{what}.csv?year={Y}")
        check(r.ok and "text/csv" in r.headers.get("Content-Type", "") and (what != "susa" or a["bank"] in r.text), f"{who}: CSV {what}")
    check(s.get(B + "/api/office/books/ledger/nonsense.csv").status_code == 404, f"{who}: an unknown list 404")
    r = s.put(B + "/api/office/books/ledger/settings", json={"size": "micro"})
    mic = s.get(B + f"/api/office/books/ledger?year={Y}").json()
    check(r.ok and mic["size"] == "micro" and all(x["level"] == 0 for x in mic["bs"]) and mic["result"] == rep["result"]
          and mic["checks"]["difference"] == "0.00", f"{who}: micro size: the letters only, the same result")
    s.put(B + "/api/office/books/ledger/settings", json={"size": "small"})

    # ---- year-end closing
    check(s.post(B + "/api/office/books/ledger/close", json={"year": TODAY.year}).status_code == 409, f"{who}: this year cannot be closed")
    r = s.post(B + "/api/office/books/ledger/close", json={"year": Y})
    check(r.ok and r.json()["result"] == rep["result"] and r.json()["opening"] > 0, f"{who}: {Y} closed {r.text[:200]}")
    check(s.post(B + "/api/office/books/ledger/close", json={"year": Y}).status_code == 409, f"{who}: closed twice 409")
    check(s.post(B + "/api/office/books/ledger/entries", json={"day": f"{Y}-12-31", "debit": a["fees"], "credit": a["prov"], "amount": "1.00"}).status_code == 409,
          f"{who}: no entry in the closed year")
    check(s.delete(B + f"/api/office/books/ledger/entries/{prov['id']}").status_code == 409, f"{who}: the provision of the closed year stays")
    per = s.get(B + O + "/periods").json()
    check(per.get("through") == f"{Y}-12", f"{who}: every month of {Y} locked {per.get('through')}")
    nx = s.get(B + f"/api/office/books/ledger?year={TODAY.year}").json()
    check(nx.get("opening") == "entries" and nx["checks"]["balanced"] and nx["checks"]["difference"] == "0.00", f"{who}: {TODAY.year} opens balanced {nx.get('checks')}")
    oa = lambda k: D((acct(nx, a[k]) or {}).get("open") or "0")  # noqa: E731
    check(oa("bank") == D("921.00") and cls(nx, "bs:B.II.1", "open") == D("595.00") and oa("prov") == D("-500.00"), f"{who}: the balances carried forward")
    check(oa("carry") == -want, f"{who}: the result on the profit / loss carried forward {oa('carry')} = {-want}")
    check(s.get(B + f"/api/office/books/ledger?year={Y}").json().get("closed") is True, f"{who}: {Y} shows as closed")


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2666C")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})

office(A, "org", f"org:{ORG}", "SKR03")

# a member of the organisation (no office admin) never sees the balance sheet
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": []})
check(r.ok, "setup: bob " + r.text[:120])
A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"})
org_join(B, "bob", ORG)
Bo = login(B, "bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
check(Bo.get(B + f"/api/office/books/ledger?year={Y}").status_code in (403, 404), "a member does not see the balance sheet")
check(Bo.post(B + "/api/office/books/ledger/entries", json={"day": f"{TODAY.year}-01-02", "debit": "4950", "credit": "0970", "amount": "1"}).status_code in (403, 404),
      "a member cannot book")

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
office(Fr, "freelancer", "private", "SKR04")
check(A.get(B + "/api/office/books/ledger/settings").json()["chart"] == "SKR03", "the organisation keeps its own chart")
# tenant-matrix: office -- the entries of another office area: 404, nothing changed; the settings route works on the own office only
OE = A.get(B + f"/api/office/books/ledger?year={TODAY.year}").json()["entries"][0]
check(Fr.put(B + f"/api/office/books/ledger/entries/{OE['id']}", json={"amount": "1.00"}).status_code == 404, "another office's entry cannot be changed: 404")
check(Fr.delete(B + f"/api/office/books/ledger/entries/{OE['id']}").status_code == 404, "another office's entry cannot be deleted: 404")
# no id in these two routes: they work on the office of the person only (the organisation keeps its own settings and closing)
# tenant: PUT /api/office/books/ledger/settings
# tenant: POST /api/office/books/ledger/close
check(Fr.put(B + "/api/office/books/ledger/settings", json={"size": "micro"}).ok and A.get(B + "/api/office/books/ledger/settings").json()["size"] == "small", "the settings route changes the own office only")
check(A.get(B + f"/api/office/books/ledger?year={TODAY.year}").json()["entries"][0]["amount"] == OE["amount"], "the organisation's entry unchanged")

sys.exit(kt.done("p2666_c_bilanz"))
