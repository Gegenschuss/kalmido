#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.685.0 (#5128) API tests: the balance sheet (office/ledger_dbl.py) gets what the income statement counts and an account per
bank account. Own container (start.sh, org encryption on). Invented companies, people and figures only.
The year before (Y), the same in both offices (an organisation with SKR03, a person without an organisation with SKR04):
 - (1) an approved entertainment receipt 150.40 (food 119.00 at 19 %, drinks 21.40 at 7 %, tip 10.00) paid by a bank line
   marked "no receipt": 70 % / 30 % on their accounts, the full input tax, the bank line against the clearing account (no
   second expense); the mileage allowance of 100 business km with a private car (the travel account against the clearing
   account / the private deposits of the owner); a paid reminder fee (other income, this year) -- each the figure of the income
   statement
 - (2) a second bank account: the lines of its statement (its IBAN) land on an account of their own (SKR03 1201 / SKR04 1801),
   an invoice paid through one of them too; the default account keeps its lines
 - (b) an invoice with 2 % cash discount paid in time: revenue and VAT reduced on the day of the payment, the debtor balances
 - (a) the counter account of receipts "bank": a receipt paid out of the cash box books bank against cash
 - (3) the balance sheet and the profit and loss account as PDF; a member of the organisation gets none
Every year: debit = credit, assets = equity and liabilities.
usage: p2685_b_bilanz_test.py <datadir>"""
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
T = TODAY.year
Y = T - 1
D = Decimal
IBAN1, IBAN2 = "DE02120300000000202051", "DE89370400440532013000"
# the accounts of the example per chart (meal 70 % / 30 %, the second bank account, the fee income, mileage: org / personal office)
ACC = {"SKR03": {"bank": "1200", "bank2": "1201", "cash": "1000", "clearing": "1590", "in19": "1576", "in7": "1571", "vat19": "1776",
                 "meal": "4650", "meal_nd": "4654", "fee": "2700", "km": "4663", "km_counter": "1590"},
       "SKR04": {"bank": "1800", "bank2": "1801", "cash": "1600", "clearing": "1370", "in19": "1406", "in7": "1401", "vat19": "3806",
                 "meal": "6640", "meal_nd": "6644", "fee": "4830", "km": "6673", "km_counter": "2180"}}


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


def camt(iban, entries, close="0.00", day=None):
    """A CAMT.053 statement of account iban with its closing balance (the balance names the account: office_bank_balances)."""
    bal = (f'<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">{close}</Amt><CdtDbtInd>CRDT</CdtDbtInd>'
           f'<Dt><Dt>{day or f"{Y}-12-31"}</Dt></Dt></Bal>')
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


def invoice(s, cl, rate, day, **extra):
    r = s.post(B + O + "/docs", json={"kind": "invoice", "client_id": cl, "project_title": f"Job {rate}", "date": day, "service_from": day,
                                       "items": [{"title": "Schnitt", "qty": 1, "rate": rate}], **extra})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if s.get(B + O + f"/docs/{did}").json().get("date") != day:
        assert s.patch(B + O + f"/docs/{did}", json={"date": day}).ok
    r = s.post(B + O + f"/docs/{did}/finalize")
    assert r.ok, r.text
    d = s.get(B + O + f"/docs/{did}").json()
    assert d["date"] == day, d["date"]
    return did


def bal(rep, a):
    x = next((x for x in rep["susa"] if x["account"] == a), None)
    return D(x["balance"]) if x else D(0)


def cls(rep, k):
    return sum((D(x["balance"]) for x in rep["susa"] if x["class"] == k), D(0))


def rows(rep, src):
    return [x for x in rep.get("journal", []) if x["src"] == src]


def balanced(rep, who, what):
    ch = rep.get("checks") or {}
    check(ch.get("balanced") and ch.get("difference") == "0.00", f"{who}: {what}: debit = credit, assets = equity and liabilities {ch}")


def office(s, who, ws, chart, me):
    a = ACC[chart]
    check(s.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "datev_extf": {"chart": chart},
                                           "company_fields": {"name": f"{who} Beispiel GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt",
                                                              "country": "DE", "tax_number": "12/345/67890", "iban": IBAN1}}).ok, f"{who}: office settings")
    check(s.put(B + L + "/settings", json={"method": "balance"}).ok, f"{who}: balance sheet chosen")
    # ---- (2) a second bank account next to the default one (made from the company's IBAN on the first look)
    acs = s.get(B + O + "/settings/bank-accounts").json()
    check(any(x.get("is_default") or x.get("default") for x in (acs.get("items") or acs.get("accounts") or [])) or acs, f"{who}: the default bank account {acs}")
    r = s.post(B + O + "/settings/bank-accounts", json={"label": "Tagesgeld", "iban": IBAN2})
    check(r.status_code in (200, 201), f"{who}: a second bank account {r.status_code} {r.text[:200]}")
    cl = s.post(B + "/api/clients", json={"name": f"{who} Kunde GmbH", "street": "Kundenweg 2", "zip": "54321", "city": "Kundenstadt", "country": "DE"}).json()["id"]
    # ---- (b) cash discount: 1000 + 19 %, 2 % in 10 days, 1166.20 paid on day 5
    ia = invoice(s, cl, 1000, f"{Y}-02-10", skonto_pct=2, skonto_days=10, payment_days=30)
    r = s.post(B + O + f"/docs/{ia}/payments", json={"date": f"{Y}-02-15", "amount": "1166.20", "method": "transfer"})
    check(r.ok and s.get(B + O + f"/docs/{ia}").json()["status"] == "paid", f"{who}: paid in time less 2 % = paid {r.text[:200]}")
    ib = invoice(s, cl, 500, f"{Y}-03-01")
    ic = invoice(s, cl, 200, f"{Y}-09-01")
    # ---- the bank: the default account pays the meal, the second account gets invoice B and an unmatched debit
    r = s.post(B + O + "/bank/import", json={"text": camt(IBAN1, [ntry("150.40", f"{Y}-05-14", "MEAL")]), "filename": "konto1.xml"})
    check(r.status_code == 201, f"{who}: import of the default account {r.status_code} {r.text[:200]}")
    r = s.post(B + O + "/bank/import", json={"text": camt(IBAN2, [ntry("595.00", f"{Y}-03-10", "INVB", "CRDT"), ntry("45.00", f"{Y}-03-12", "OUT45")]),
                                             "filename": "konto2.xml"})
    check(r.status_code == 201, f"{who}: import of the second account {r.status_code} {r.text[:200]}")
    tx = {t["purpose"].split()[-1]: t["id"] for t in s.get(B + O + "/bank/tx?state=all").json()["items"]}
    m = lambda tid, b: s.post(B + O + f"/bank/tx/{tid}/match", json=b)  # noqa: E731
    check(m(tx["INVB"], {"kind": "invoice", "id": ib}).ok, f"{who}: invoice B paid through the second account")
    check(m(tx["MEAL"], {"kind": "noreceipt"}).ok, f"{who}: the meal's bank line marked 'no receipt'")
    # ---- (1) the meal, approved and linked to its bank line
    r = s.post(B + O + "/meals", json={"date": f"{Y}-05-14", "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
                                        "occasion": "Negotiation of the follow-up order", "host": {"id": me},
                                        "guests": [{"name": "Gina Gast", "extra": "Example GmbH, buyer"}],
                                        "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}, {"kind": "drinks", "rate": 7, "gross": "21.40"}],
                                        "tip": "10"})
    check(r.status_code == 201, f"{who}: a meal {r.status_code} {r.text[:200]}")
    mid = r.json()["id"]
    check(s.post(B + O + f"/meals/{mid}/approve").ok, f"{who}: the meal approved")
    r = s.put(B + O + f"/meals/{mid}/payment", json={"kind": "bank", "id": tx["MEAL"]})
    check(r.ok, f"{who}: the meal linked to its bank line {r.status_code} {r.text[:200]}")
    # ---- (1) the mileage allowance: 100 business km with a private car
    r = s.post(B + O + "/vehicles", json={"name": "Privatwagen", "plate": "M-KC 5128", "kind": "private"})
    check(r.status_code in (200, 201), f"{who}: a private car {r.text[:200]}")
    veh = r.json()["id"]
    r = s.post(B + O + "/drives", json={"vehicle_id": veh, "day": f"{Y}-06-01", "dest": "Kunde", "purpose": "Dreh", "km": 100, "kind": "business"})
    check(r.status_code in (200, 201), f"{who}: a business drive {r.text[:200]}")

    # ---- the reports of Y
    rep = s.get(B + L + f"?year={Y}&journal=1").json()
    eu = s.get(B + O + f"/books/euer?year={Y}").json()
    balanced(rep, who, str(Y))
    # (1) the meal: as the income statement, plus the 30 % (an expense in the commercial accounts)
    ml = next((x for x in eu.get("expenses", []) if x["key"] == "m:"), {})
    check(bal(rep, a["meal"]) == D(ml.get("net") or "-1") == D("91.00") and bal(rep, a["meal_nd"]) == D("39.00"),
          f"{who}: meal 70 % = the income statement's {ml.get('net')}, 30 % on its own account {[x for x in rep['susa'] if x['account'] in (a['meal'], a['meal_nd'])]}")
    check(bal(rep, a["in19"]) == D("19.00") and bal(rep, a["in7"]) == D("1.40"), f"{who}: the meal's full input tax 19.00 + 1.40")
    mr = rows(rep, "meal")
    check(sum((D(x["amount"]) for x in mr), D(0)) == D("150.40") and all(x["credit"] == a["clearing"] for x in mr),
          f"{who}: the meal books the whole bill against the clearing account {mr}")
    # (1) its bank line moves the money only: no second expense, the clearing account takes it
    br = [x for x in rep["journal"] if x["doc"] == f"BK{tx['MEAL']}"]
    check(len(br) == 1 and br[0]["debit"] == a["clearing"] and br[0]["credit"] == a["bank"] and br[0]["amount"] == "150.40",
          f"{who}: the meal's bank line: clearing against bank (was an expense of its own) {br}")
    # (1) the mileage allowance
    kl = next((x for x in eu.get("expenses", []) if x["key"] == "km"), {})
    kr = rows(rep, "km")
    check(len(kr) == 1 and kr[0]["debit"] == a["km"] and kr[0]["credit"] == a["km_counter"] and D(kr[0]["amount"]) == D(kl.get("net") or "-1") > 0,
          f"{who}: the mileage allowance {kr} = the income statement's {kl}")
    # (2) the second bank account
    check(bal(rep, a["bank2"]) == D("550.00") and bal(rep, a["bank"]) == D("-150.40") + D("1166.20"),
          f"{who}: second account 595 - 45, the default account meal + payment A {[x for x in rep['susa'] if x['class'] == 'liquid']}")
    lb2 = next((x["label"] for x in rep["susa"] if x["account"] == a["bank2"]), "")
    check("Tagesgeld" in lb2, f"{who}: the second account carries its name {lb2!r}")
    pb = [x for x in rows(rep, "payment") if x["credit"] != a["bank2"] and D(x["amount"]) == D("595.00")]
    check(pb and pb[0]["debit"] == a["bank2"], f"{who}: invoice B paid on the second account {pb}")
    # (b) the cash discount: 23.80 = 20.00 revenue + 3.80 VAT against the debtor on the day of the payment; the debtor balances
    sk = rows(rep, "skonto")
    check(sorted(D(x["amount"]) for x in sk) == [D("3.80"), D("20.00")] and all(x["day"] == f"{Y}-02-15" for x in sk),
          f"{who}: the cash discount net + VAT on the day of the payment {sk}")
    check(any(x["debit"] == a["vat19"] and x["amount"] == "3.80" for x in sk), f"{who}: the VAT of the discount reduces the VAT {sk}")
    check(cls(rep, "bs:B.II.1") == D("238.00"), f"{who}: only invoice C open on the debtors (A balances with payment + discount)")
    pl = {x["key"]: D(x["amount"]) for x in rep["pl"]}
    check(pl.get("1") == D("1680.00"), f"{who}: revenue 1000 + 500 + 200 - 20 discount {pl}")
    check(bal(rep, a["vat19"]) == -(D("190.00") - D("3.80") + D("95.00") + D("38.00")), f"{who}: VAT less the discount's {bal(rep, a['vat19'])}")
    check(bal(rep, a["clearing"]) == D("45.00") - (D(kr[0]["amount"]) if kr and a["km_counter"] == a["clearing"] else 0),
          f"{who}: clearing: the unmatched 45.00 (the meal and its line net out) {bal(rep, a['clearing'])}")

    # ---- (3) the balance sheet and the profit and loss account as PDF (the rights of the CSV)
    for what in ("bs", "pl"):
        r = s.get(B + L + f"/{what}.pdf?year={Y}")
        check(r.ok and r.headers.get("Content-Type", "").startswith("application/pdf") and r.content[:5] == b"%PDF-" and f"-{Y}.pdf" in r.headers.get("Content-Disposition", ""),
              f"{who}: PDF {what} {r.status_code} {r.headers.get('Content-Type')}")
    check(s.get(B + L + f"/susa.pdf?year={Y}").status_code == 404, f"{who}: no PDF of an unknown list")
    # ---- (1) a paid reminder fee (this year: marked paid today)
    r = s.post(B + O + "/docs/reminder", json={"doc_ids": [ic], "level": 1, "fee": 5})
    check(r.ok, f"{who}: a reminder with a fee {r.status_code} {r.text[:200]}")
    rm = r.json()["id"]
    check(s.post(B + O + f"/docs/{rm}/finalize").ok, f"{who}: the reminder finalised")
    check(s.post(B + O + f"/docs/{rm}/fee", json={"state": "paid"}).ok, f"{who}: the fee paid")
    # ---- (a) counter account bank: a receipt paid out of the cash box books bank against cash
    ws_ = ws
    r2 = doc(s, ws_, "r2-porto.pdf", "59.50", TODAY.isoformat(), "19", "Porto")
    r = s.post(B + O + "/cashbooks", json={"name": "Handkasse", "opening": "100.00", "opening_day": f"{T}-01-01"})
    check(r.status_code == 201, f"{who}: a cash box {r.text[:200]}")
    r = s.post(B + O + f"/cashbooks/{r.json()['id']}/entries", json={"day": TODAY.isoformat(), "dir": "out", "amount": "59.50", "text": "Porto", "node_id": r2})
    check(r.status_code == 201, f"{who}: the receipt paid out of the cash box {r.text[:200]}")
    ce = r.json().get("id") or (r.json().get("entry") or {}).get("id")
    check(s.put(B + O + "/settings", json={"datev_extf": {"chart": chart, "in_counter": "bank"}}).ok, f"{who}: counter account of receipts: bank")
    rt = s.get(B + L + f"?year={T}&journal=1").json()
    eu = s.get(B + O + f"/books/euer?year={T}").json()
    balanced(rt, who, str(T))
    fl = next((x for x in eu.get("income", []) if x["key"] == "fee"), {})
    fr = rows(rt, "fee")
    check(len(fr) == 1 and fr[0]["credit"] == a["fee"] and fr[0]["debit"] == a["clearing"] and D(fr[0]["amount"]) == D(fl.get("net") or "-1") == D("5.00"),
          f"{who}: the paid fee as other income = the income statement's {fr} {fl}")
    check({x["key"]: D(x["amount"]) for x in rt["pl"]}.get("4") == D("5.00"), f"{who}: the fee in the other operating income")
    kc = [x for x in rt["journal"] if x["doc"] == f"KA{ce}"]
    check(len(kc) == 1 and kc[0]["debit"] == a["bank"] and kc[0]["credit"] == a["cash"] and kc[0]["amount"] == "59.50",
          f"{who}: the cash box paid the receipt booked against the bank: bank against cash (was not booked) {kc}")
    return rep


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2685B")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
office(A, "org", f"org:{ORG}", "SKR03", ALICE)

# a member of the organisation (no office admin) gets no PDF of the balance sheet
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": []})
check(r.ok, "setup: bob " + r.text[:120])
A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"})
org_join(B, "bob", ORG)
Bo = login(B, "bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
check(Bo.get(B + f"/api/office/books/ledger/bs.pdf?year={Y}").status_code in (403, 404), "a member gets no PDF of the balance sheet")

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
office(Fr, "freelancer", "private", "SKR04", FID)

sys.exit(kt.done("p2685_b_bilanz"))
