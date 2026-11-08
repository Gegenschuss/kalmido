#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.702.0 (#5183) API tests: the balance sheet (office/ledger_dbl.py) with two bank accounts -- the rest of #5128. Own
container (start.sh, org encryption on). Invented companies, people and figures only. In both offices (an organisation with
SKR03, a person without an organisation with SKR04), the year before (Y):
 - (1) the collective payout of the online payment provider lands on the second account (its statement): the invoice's payment
   is booked on the default account (as DATEV does), the payout line moves the money onto the second account
 - (2) a CSV statement names no account: with two bank accounts the preview offers them, the import without a choice is
   refused (400), with the second account chosen its lines land on the second account (was: silently the default); a CSV
   mixed with a CAMT statement in one import is refused (one choice cannot hold for both)
 - (3) a restaurant bill 59.50 that is a receipt (matched with its bank line) and an approved entertainment receipt on the same
   line counts once: the meal books 70 / 30 + input tax, the receipt is not booked, the bank line goes against the clearing
   account (was: the receipt's expense on top)
Every year: debit = credit, assets = equity and liabilities.
usage: p2702_bilanz_test.py <datadir>"""
import base64
import json
import os
import sys
from decimal import Decimal

import testclock

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"
L = O + "/books/ledger"
FEAT = "cal,comments,collab,office,clients,docs"
Y = testclock.today().year - 1
D = Decimal
IBAN1, IBAN2 = "DE02120300000000202051", "DE89370400440532013000"
ACC = {"SKR03": {"bank": "1200", "bank2": "1201", "clearing": "1590", "in19": "1576", "meal": "4650", "meal_nd": "4654"},
       "SKR04": {"bank": "1800", "bank2": "1801", "clearing": "1370", "in19": "1406", "meal": "6640", "meal_nd": "6644"}}


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


def camt(iban, entries):
    """A CAMT.053 statement of account iban with a closing balance (the balance names the account: office_bank_balances)."""
    bal = f'<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">0.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{Y}-12-31</Dt></Dt></Bal>'
    return ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>S</Id>'
            f'<Acct><Id><IBAN>{iban}</IBAN></Id><Ccy>EUR</Ccy></Acct>' + bal + "".join(entries) + '</Stmt></BkToCstmrStmt></Document>')


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
    return did


def bal(rep, a):
    x = next((x for x in rep["susa"] if x["account"] == a), None)
    return D(x["balance"]) if x else D(0)


def office(s, who, ws, chart, me):
    a = ACC[chart]
    check(s.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "datev_extf": {"chart": chart},
                                           "company_fields": {"name": f"{who} Beispiel GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt",
                                                              "country": "DE", "tax_number": "12/345/67890", "iban": IBAN1}}).ok, f"{who}: office settings")
    check(s.put(B + L + "/settings", json={"method": "balance"}).ok, f"{who}: balance sheet chosen")
    s.get(B + O + "/settings/bank-accounts")  # the default account from the company's IBAN (first look)
    r = s.post(B + O + "/settings/bank-accounts", json={"label": "Tagesgeld", "iban": IBAN2})
    check(r.status_code in (200, 201), f"{who}: a second bank account {r.status_code} {r.text[:200]}")
    cl = s.post(B + "/api/clients", json={"name": f"{who} Kunde GmbH", "street": "Kundenweg 2", "zip": "54321", "city": "Kundenstadt", "country": "DE"}).json()["id"]

    # ---- (1) an invoice paid through the provider (booked on the default account), its payout on the second account
    ip = invoice(s, cl, 1000, f"{Y}-04-01")
    r = s.post(B + O + f"/docs/{ip}/payments", json={"date": f"{Y}-04-02", "amount": "1190.00", "method": "other"})
    check(r.ok, f"{who}: the invoice paid {r.status_code} {r.text[:200]}")
    r = s.post(B + O + "/bank/import", json={"text": camt(IBAN2, [ntry("1190.00", f"{Y}-04-05", "PAYOUT", "CRDT")]), "filename": "konto2.xml"})
    check(r.status_code == 201, f"{who}: the second account's statement {r.status_code} {r.text[:200]}")
    # ---- (3) a restaurant bill: a receipt matched with its bank line (default account) and an approved meal on the same line
    rc = doc(s, ws, "trattoria.pdf", "59.50", f"{Y}-06-10", "19", "Bewirtung")
    r = s.post(B + O + "/bank/import", json={"text": camt(IBAN1, [ntry("59.50", f"{Y}-06-10", "MEAL2")]), "filename": "konto1.xml"})
    check(r.status_code == 201, f"{who}: the default account's statement {r.status_code} {r.text[:200]}")
    tx = {t["purpose"].split()[-1]: t["id"] for t in s.get(B + O + "/bank/tx?state=all").json()["items"]}
    m = lambda tid, b: s.post(B + O + f"/bank/tx/{tid}/match", json=b)  # noqa: E731
    r = m(tx["PAYOUT"], {"kind": "payout"})
    check(r.ok, f"{who}: the line marked as the provider's payout {r.status_code} {r.text[:200]}")
    r = m(tx["MEAL2"], {"kind": "receipt", "id": rc})
    check(r.ok, f"{who}: the bill's receipt matched with its bank line {r.status_code} {r.text[:200]}")
    r = s.post(B + O + "/meals", json={"date": f"{Y}-06-10", "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
                                        "occasion": "Planning of the next shoot", "host": {"id": me},
                                        "guests": [{"name": "Gina Gast", "extra": "Example GmbH"}],
                                        "amounts": [{"kind": "food", "rate": 19, "gross": "59.50"}]})
    check(r.status_code == 201, f"{who}: a meal {r.status_code} {r.text[:200]}")
    mid = r.json()["id"]
    check(s.post(B + O + f"/meals/{mid}/approve").ok, f"{who}: the meal approved")
    r = s.put(B + O + f"/meals/{mid}/payment", json={"kind": "bank", "id": tx["MEAL2"]})
    check(r.ok, f"{who}: the meal linked to the same bank line {r.status_code} {r.text[:200]}")

    # ---- (2) a CSV statement: no account of its own
    csv = f"Buchungstag;Auftraggeber/Empfänger;Verwendungszweck;Betrag\n15.07.{Y};Druckerei Beispiel;Buchung CSVOUT;-30,00\n"
    pv = s.post(B + O + "/bank/import/preview", json={"text": csv}).json()
    accts = pv.get("bank_accounts") or []
    check(len(accts) == 2 and sum(1 for x in accts if x["default"]) == 1 and any(x["label"] == "Tagesgeld" and x["iban_end"] == IBAN2[-4:] for x in accts),
          f"{who}: the preview offers both bank accounts {accts}")
    mapping = {k: (pv.get("guess") or {}).get(k) for k in ("date", "amount", "amount_in", "amount_out", "title", "counterpart", "decimal", "date_format")}
    r = s.post(B + O + "/bank/import", json={"text": csv, "filename": "konto2.csv", "mapping": mapping})
    check(r.status_code == 400, f"{who}: a CSV without a chosen account is refused {r.status_code} {r.text[:200]}")
    two = next((x["id"] for x in accts if not x["default"]), None)
    r = s.post(B + O + "/bank/import", json={"text": csv, "filename": "konto2.csv", "mapping": mapping, "bank_account": 999999})
    check(r.status_code == 400, f"{who}: an unknown bank account is refused {r.status_code}")
    # a CSV together with a CAMT statement (several files): one choice cannot hold for both -> 400, import them one by one
    mixed = [("files", ("konto2.csv", csv.encode(), "text/csv")), ("files", ("konto1.xml", camt(IBAN1, [ntry("12.00", f"{Y}-08-01", "MIXED")]).encode(), "text/xml"))]
    r = s.post(B + O + "/bank/import", files=mixed, data={"mapping": json.dumps(mapping), "bank_account": str(two)})
    check(r.status_code == 400, f"{who}: a mixed CSV + CAMT import with a chosen account is refused {r.status_code} {r.text[:200]}")
    r = s.post(B + O + "/bank/import", files=mixed, data={"mapping": json.dumps(mapping)})
    check(r.status_code == 400, f"{who}: a mixed CSV + CAMT import without a choice is refused {r.status_code} {r.text[:200]}")
    r = s.post(B + O + "/bank/import", json={"text": csv, "filename": "konto2.csv", "mapping": mapping, "bank_account": two})
    check(r.status_code == 201 and r.json().get("count") == 1, f"{who}: the CSV imported into the second account {r.status_code} {r.text[:200]}")
    tx = {t["purpose"].split()[-1]: t["id"] for t in s.get(B + O + "/bank/tx?state=all").json()["items"]}

    # ---- the report of Y
    rep = s.get(B + L + f"?year={Y}&journal=1").json()
    ch = rep.get("checks") or {}
    check(ch.get("balanced") and ch.get("difference") == "0.00", f"{who}: debit = credit, assets = equity and liabilities {ch}")
    jr = rep.get("journal", [])
    # (1) the payout moves the money from the default account onto the second one
    po = [x for x in jr if x["doc"] == f"BK{tx['PAYOUT']}"]
    check(len(po) == 1 and po[0]["debit"] == a["bank2"] and po[0]["credit"] == a["bank"] and D(po[0]["amount"]) == D("1190.00"),
          f"{who}: the payout: second account against the default account {po}")
    # (2) the CSV line on the second account
    cv = [x for x in jr if x["doc"] == f"BK{tx['CSVOUT']}"]
    check(len(cv) == 1 and cv[0]["credit"] == a["bank2"] and D(cv[0]["amount"]) == D("30.00"), f"{who}: the CSV line leaves the second account {cv}")
    check(bal(rep, a["bank2"]) == D("1160.00") and bal(rep, a["bank"]) == D("-59.50"),
          f"{who}: second account 1190 - 30, default account 1190 - 1190 - 59.50 {[x for x in rep['susa'] if x['class'] == 'liquid']}")
    # (3) the bill counts once: the meal, not the receipt
    check(not [x for x in jr if x["doc"] == f"B{rc}"], f"{who}: the receipt of the meal is not booked a second time {[x for x in jr if x['doc'] == f'B{rc}']}")
    ml = [x for x in jr if x["doc"] == f"BK{tx['MEAL2']}"]
    check(len(ml) == 1 and ml[0]["debit"] == a["clearing"] and ml[0]["credit"] == a["bank"] and D(ml[0]["amount"]) == D("59.50"),
          f"{who}: the meal's bank line: clearing against bank {ml}")
    check(bal(rep, a["meal"]) == D("35.00") and bal(rep, a["meal_nd"]) == D("15.00") and bal(rep, a["in19"]) == D("9.50"),
          f"{who}: the meal 70 % / 30 % of 50.00 + 9.50 input tax {[x for x in rep['susa'] if x['account'] in (a['meal'], a['meal_nd'], a['in19'])]}")
    check(bal(rep, a["clearing"]) == D("30.00"), f"{who}: clearing: the unmatched CSV line only (the meal and its line net out) {bal(rep, a['clearing'])}")
    return rep


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2702")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
office(A, "org", f"org:{ORG}", "SKR03", ALICE)

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
office(Fr, "freelancer", "private", "SKR04", FID)

sys.exit(kt.done("p2702_bilanz"))
