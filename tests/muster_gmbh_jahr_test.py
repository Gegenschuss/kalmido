#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.784.0 (#5387): the business year of the invented "Muster GmbH" (balance sheet, SKR03, VAT on invoicing, quarterly
advance returns) as a hard check of the bookkeeping. The events and the expected figures stand in
tests/fixtures/muster_gmbh_2025.json: worked out BY HAND (HGB, UStG, SKR03), each event with its postings and a short way of
computing -- never derived from Kalmido code. The suite
 - first checks the fixture itself: the postings add up to the expected account balances, profit and loss and balance sheet
   agree with each other (so a typo in the expected figures cannot hide)
 - creates the organisation through the normal API and plays every event in (tools/muster_gmbh_play.py, the same code as the
   demo loader tools/muster_gmbh_demo.py)
 - compares Kalmido's journal (each posting: day, debit, credit, amount), the account balances, the profit and loss account,
   the balance sheet (office/ledger_dbl.py) and the advance VAT returns per quarter and year (books.bk_ustva) to the cent;
   a difference names account / field, expected and actual
 - prints the named gaps (LUECKEN): what a real GmbH year needs and Kalmido does not do (yet); nothing is silently left out
 - 2.912.0 (#5419): a deferral case with both sides (prepaid expenses 0980 / deferred income 0990, section 250 HGB): the
   expected figures again by hand, the fixture check recomputes them from the periods; the VAT returns compare strictly (every
   expected field must be in Kalmido's answer)
 - 2.784.0 (#5387 fix): a reminder fee paid in an earlier month is marked paid with that day (was: always today -- a fee paid
   in December and marked in January landed in the wrong year); a day in the future or before the reminder is refused
Freelancer parity: the changed fee route also in a personal office.
usage: muster_gmbh_jahr_test.py <datadir>"""
# freelancer-matrix: office
import base64
import json
import os
import sys
from collections import Counter
from decimal import Decimal

import testclock

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(N, "..", "tools"))
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check  # noqa: E402
from muster_gmbh_demo import allowed  # noqa: E402
from muster_gmbh_play import play  # noqa: E402

D = Decimal
OFC = "/api/office"
FX = json.load(open(os.path.join(N, "fixtures", "muster_gmbh_2025.json"), encoding="utf-8"))
Y = FX["jahr"]
FEAT = "cal,comments,collab,office,clients,docs"

# What a real year-end of a GmbH needs and Kalmido does not do (yet). Printed on every run; none of it is silently left out.
LUECKEN = [
    "E-Bilanz (XBRL, Taxonomie) und Übermittlung per ERiC an das Finanzamt: Kalmido rechnet Bilanz und GuV, übermittelt nichts",
    "Anhang und Lagebericht (§§ 284 ff., 289 HGB) sowie Offenlegung im Unternehmensregister: nicht in Kalmido",
    "Körperschaftsteuer, Solidaritätszuschlag und Gewerbesteuer (Steuerrückstellung, Steuererklärungen): nicht berechnet; das "
    "Jahresergebnis der Suite ist vor Ertragsteuern",
    "Reverse-Charge-Eingang (§ 13b UStG): Kalmido bucht den Beleg netto ohne das Paar 1577 Vorsteuer an 1787 Umsatzsteuer (je "
    "114,00 bei B04); Bilanz und GuV stimmen (Saldo 0), die USt-Voranmeldung meldet 46/47/67 richtig, nur das Journal zeigt die "
    "zwei Konten nicht (Entscheidung #4387: der Steuerschlüssel bleibt beim Steuerberater)",
    "Lohnbuchhaltung (Gehälter, Sozialversicherung, Lohnsteuer-Anmeldung): nicht in Kalmido, darum hat die Muster GmbH kein Personal",
    "Zusammenfassende Meldung und Umsatzsteuer-Jahreserklärung: nur die Zahlen der Voranmeldungen, kein Formular",
    "Rückstellungen, Abgrenzungen und das Ausbuchen der Zahlungen an das Finanzamt (1780) macht Kalmido nicht selbst: Umbuchung "
    "von Hand (U1-U7; die Rechnungsabgrenzungen 0980 / 0990 rechnet Kalmido nicht aus Leistungszeiträumen), Bankzeilen ohne Beleg laufen über das Verrechnungskonto 1590",
    "Personenkonten: Kalmido bucht alle Kunden auf das Sammelkonto 10000 und alle Lieferanten auf 70000 (ohne Kundennummer); "
    "offene Posten je Kunde/Lieferant stehen nicht in der Saldenliste",
    "Umsatzsteuer bei Dauerleistungen (Soll-Versteuerung): die Voranmeldung nimmt das Rechnungsdatum, nicht Leistungszeitraum "
    "oder Anzahlung (§ 13 Abs. 1 Nr. 1a UStG); RE7 stimmt nur, weil Rechnung und Vorauszahlung im selben Quartal liegen",
    "Reisekostenabrechnung: es gibt keinen Zahlweg für die Erstattung an die reisende Person (Umbuchung U3 von Hand)",
]

FIELDS = ("81", "86", "66", "46", "47", "67", "83")


def postings(fx):
    """Every expected posting [day, debit, credit, amount] of the fixture (opening entries on 1 January)."""
    out = [[f"{Y}-01-01", e["soll"], e["haben"], e["betrag"]] for e in fx["eroeffnung"]]
    out += [[u["tag"], u["soll"], u["haben"], u["betrag"]] for u in fx["umbuchungen"]]

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "buchungen":
                    out.extend(v)
                elif k not in ("soll", "eroeffnung", "umbuchungen"):
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(fx)
    return out


def balances(rows):
    bal = {}
    for _day, dr, cr, a in rows:
        bal[dr] = bal.get(dr, D(0)) + D(a)
        bal[cr] = bal.get(cr, D(0)) - D(a)
    return bal


# ================================================================ 1. the fixture itself (no server)
SOLL = FX["soll"]
EXP = postings(FX)
bal = balances(EXP)
want = {k: D(v) for k, v in SOLL["konten"].items()}
diff = [(a, want.get(a, D(0)), bal.get(a, D(0))) for a in sorted(set(bal) | set(want)) if bal.get(a, D(0)) != want.get(a, D(0))]
check(not diff, f"fixture: the postings add up to the expected balances (account, expected, from the postings) {diff}")
check(sum(bal.values(), D(0)) == 0, "fixture: debit = credit over all postings")
pl = {k: D(v) for k, v in SOLL["guv"].items()}
res = pl["1"] + pl["4"] + pl["11"] - pl["5"] - pl["6"] - pl["7"] - pl["8"] - pl["13"] - pl["14"] - pl["16"]
check(res == D(SOLL["ergebnis"]), f"fixture: profit and loss lines give the result {res} = {SOLL['ergebnis']}")
# the result also from the accounts: minus the sum of the income and expense accounts (classes 2-8 of SKR03)
res2 = -sum((v for a, v in bal.items() if len(a) == 4 and a[0] in "2345678"), D(0))
check(res2 == D(SOLL["ergebnis"]), f"fixture: the result from the accounts {res2} = {SOLL['ergebnis']}")
bs = {k: D(v) for k, v in SOLL["bilanz"].items()}
assets = sum((v for k, v in bs.items() if not k.startswith("P.")), D(0))
liab = sum((v for k, v in bs.items() if k.startswith("P.")), D(0))
check(assets == liab == D(SOLL["summe_aktiva"]) and bs["P.A.V"] == D(SOLL["ergebnis"]), f"fixture: assets {assets} = equity and liabilities {liab}")
uq = SOLL["ustva"]
for f in FIELDS:
    tot = sum((D(uq[q][f]) for q in ("q1", "q2", "q3", "q4")), D(0))
    check(tot == D(uq["y"][f]), f"fixture: VAT field {f}: quarters add up to the year {tot} = {uq['y'][f]}")
tax = sum((bal.get(a, D(0)) for a in ("1571", "1576", "1771", "1776", "1780")), D(0))
check(-tax == D(uq["q4"]["83"]) == bs["P.C.8"], f"fixture: VAT accounts net = the open return of Q4 {-tax}")
check(D(uq["y"]["83"]) == -(bal["1776"] + bal["1771"]) - (bal["1576"] + bal["1571"]), "fixture: the year's VAT = VAT accounts - input tax accounts")
# 2.912.0 (#5419): the deferrals from their periods (months after the balance sheet day / months of the period x net amount)
_rap = {u["key"]: u for u in FX["umbuchungen"]}
_b04 = next(b for b in FX["belege"] if b["key"] == "B04")
_re7 = next(r for r in FX["rechnungen"] if r["key"] == "RE7")
check(D(_rap["U6"]["betrag"]) == D(_b04["brutto"]) * 3 / 12 == bs["C"] == bal["0980"], "fixture: prepaid expenses = 3 of 12 months of B04 (2026-01 to 03)")
check(D(_rap["U7"]["betrag"]) == sum((D(x["preis"]) * x["menge"] for x in _re7["positionen"]), D(0)) * 11 / 12 == bs["P.D"] == -bal["0990"],
      "fixture: deferred income = 11 of 12 months of RE7 net (2026-01 to 11), the VAT stays out")

# the demo loader never writes to the live instance: only local hosts and the hosts of KALMIDO_DEMO_ALLOW, never the live domain
for url, allow, ok in (("https://app.kalmido.com", "app.kalmido.com", False), ("https://x.kalmido.com.", "", False), ("http://127.0.0.1:3048", "", True),
                       ("https://demo.example", "", False), ("https://demo.example", "demo.example", True), ("ftp://demo.example", "demo.example", False)):
    check(allowed(url, allow)[0] == ok, f"demo loader: {url} with allow list {allow!r} -> {'allowed' if ok else 'refused'}")

# ================================================================ 2. the organisation, played through the API
assert testclock.today().year > Y, "the test time must lie after the business year of the fixture"
KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="MUSTERGMBH")
A = kt.setup()
ME = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "de", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": FX["firma"]["name"], "admin_id": ME}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
IDS = play(A, B, FX, f"org:{ORG}", ME, log=lambda x: print("played:", x, flush=True))
check("MA1" in IDS and len(IDS) >= len(FX.get("mahnungen") or []), f"all events played in through the API ({len(IDS)} ids)")

# ================================================================ 3. Kalmido against the expected figures
rep = A.get(B + OFC + f"/books/ledger?year={Y}&journal=1").json()
jr = rep.get("journal") or []
got = Counter((x["day"], x["debit"], x["credit"], D(x["amount"])) for x in jr)
exp = Counter((d, dr, cr, D(a)) for d, dr, cr, a in EXP)
missing, extra = exp - got, got - exp
check(not missing, "journal: every expected posting is there (day, debit, credit, amount) - missing: "
      + "; ".join(f"{d} {dr} an {cr} {a} (x{n})" for (d, dr, cr, a), n in sorted(missing.items())))
check(not extra, "journal: no posting beyond the expected ones - extra: "
      + "; ".join(f"{d} {dr} an {cr} {a} (x{n}) {[x['doc'] + ' ' + x['text'] for x in jr if (x['day'], x['debit'], x['credit'], D(x['amount'])) == (d, dr, cr, a)][:2]}"
                  for (d, dr, cr, a), n in sorted(extra.items())))
susa = {x["account"]: D(x["balance"]) for x in rep.get("susa") or []}
for a in sorted(set(susa) | set(want)):
    check(susa.get(a, D(0)) == want.get(a, D(0)), f"account {a}: expected {want.get(a, D(0))}, Kalmido {susa.get(a, D(0))}")
plk = {x["key"]: D(x["amount"]) for x in rep.get("pl") or []}
for k, v in pl.items():
    check(plk.get(k, D(0)) == v, f"profit and loss line {k}: expected {v}, Kalmido {plk.get(k)}")
check(D(rep.get("result") or "0") == D(SOLL["ergebnis"]), f"result of the year: expected {SOLL['ergebnis']}, Kalmido {rep.get('result')}")
bsk = {x["key"]: D(x["amount"]) for x in rep.get("bs") or [] if x.get("level") == 1}
for k in sorted(set(bsk) | set(bs)):
    check(bsk.get(k, D(0)) == bs.get(k, D(0)), f"balance sheet line {k}: expected {bs.get(k, D(0))}, Kalmido {bsk.get(k, D(0))}")
ch = rep.get("checks") or {}
check(ch.get("balanced") and D(ch.get("difference") or "1") == 0 and D(ch.get("assets") or "0") == D(SOLL["summe_aktiva"]) and D(ch.get("opening") or "1") == 0,
      f"checks: debit = credit, assets {SOLL['summe_aktiva']} = equity and liabilities, opening balance account 0 {ch}")
for q in ("q1", "q2", "q3", "q4", "y"):
    r = A.get(B + OFC + f"/books/ustva?year={Y}&period={q}")
    kz = r.json().get("kz", {}) if r.ok else {}
    check(r.ok and r.json().get("basis") == "soll", f"VAT return {q}: VAT on invoicing {r.status_code} {r.text[:120] if not r.ok else r.json().get('basis')}")
    for f in FIELDS:  # 2.912.0 (#5419): strict - a field missing in Kalmido's answer is a difference, not 0
        check(f in kz and D(kz[f]) == D(uq[q][f]), f"VAT return {q} field {f}: expected {uq[q][f]}, Kalmido {kz.get(f, 'missing')}")
    check(r.ok and r.json().get("missing_vat") == 0, f"VAT return {q}: no receipt without a VAT rate {r.json().get('missing_vat') if r.ok else ''}")

# the gap of section 13b in the journal is real (the pair is not booked) -- so it stays named, not silently fine
pair = FX["belege"][3]["nicht_in_kalmido"][0]
check(not [x for x in jr if (x["debit"], x["credit"]) == (pair[1], pair[2])],
      "gap still there: the section 13b pair 1577 / 1787 is not in the journal (if Kalmido books it now: move it from LUECKEN into the postings)")
print("LUECKEN (named gaps, not checked):", flush=True)
for x in LUECKEN:
    print("  -", x, flush=True)

# ================================================================ 4. the reminder fee with its day (#5387 fix)
D_ = OFC + "/docs"
rm = IDS["MA1"]
fee_day = kt.dbx("SELECT reminder_fee_paid_at FROM office_docs WHERE id=?", (rm,))[0][0]
check(fee_day == FX["mahnungen"][0]["bezahlt_am"], f"fee paid on the day the money came, not today (was: always today) {fee_day}")
check(A.post(B + f"{D_}/{rm}/fee", json={"state": "paid", "day": "2099-01-01"}).status_code == 400, "a fee day in the future: 400")
check(A.post(B + f"{D_}/{rm}/fee", json={"state": "paid", "day": f"{Y}-07-31"}).status_code == 400, "a fee day before the reminder: 400")
check(A.post(B + f"{D_}/{rm}/fee", json={"state": "paid", "day": "1.9."}).status_code == 400, "a fee day that is no day: 400")
check(kt.dbx("SELECT reminder_fee_paid_at FROM office_docs WHERE id=?", (rm,))[0][0] == fee_day, "a refused day changes nothing")


# ================================================================ 5. the same in a personal office (freelancer parity)
def fee_personal(s, who):
    cl = s.post(B + "/api/clients", json={"name": f"{who} Kunde", "street": "Weg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"}).json()["id"]
    r = s.post(B + D_, json={"kind": "invoice", "client_id": cl, "project_title": "Schnitt", "date": f"{Y}-03-02", "service_from": f"{Y}-03-02",
                             "items": [{"title": "Schnitt", "qty": 1, "rate": 500}]})
    check(r.status_code == 201, f"{who}: invoice {r.text[:200]}")
    inv = r.json()["id"]
    if s.get(B + f"{D_}/{inv}").json().get("date") != f"{Y}-03-02":
        s.patch(B + f"{D_}/{inv}", json={"date": f"{Y}-03-02"})
    r = s.post(B + f"{D_}/{inv}/finalize")
    check(r.ok, f"{who}: invoice finalised {r.status_code} {r.text[:300]}")
    r = s.post(B + D_ + "/reminder", json={"doc_ids": [inv], "level": 2, "fee": 5})
    check(r.ok, f"{who}: reminder with a fee {r.text[:200]}")
    rid = r.json()["id"]
    if s.get(B + f"{D_}/{rid}").json().get("date") != f"{Y}-04-01":
        s.patch(B + f"{D_}/{rid}", json={"date": f"{Y}-04-01"})
    check(s.post(B + f"{D_}/{rid}/finalize").ok, f"{who}: reminder finalised")
    r = s.post(B + f"{D_}/{rid}/fee", json={"state": "paid", "day": f"{Y}-04-20"})
    check(r.ok, f"{who}: fee paid with its day {r.text[:200]}")
    check(kt.dbx("SELECT reminder_fee_paid_at FROM office_docs WHERE id=?", (rid,))[0][0] == f"{Y}-04-20", f"{who}: the day is stored")
    eu = s.get(B + OFC + f"/books/euer?year={Y}").json()
    fee = [x for x in eu.get("income") or [] if x["key"] == "fee"]
    check(fee and fee[0]["gross"] == "5.00", f"{who}: the income statement of {Y} counts the fee (was: the year of the click) {fee}")
    r = s.post(B + f"{D_}/{rid}/fee", json={"state": "paid"})
    check(r.ok and kt.dbx("SELECT reminder_fee_paid_at FROM office_docs WHERE id=?", (rid,))[0][0] == f"{Y}-04-20",
          f"{who}: paid again without a day keeps the day {r.status_code}")
    r = s.post(B + f"{D_}/{rid}/fee", json={"state": ""})
    check(r.ok and not kt.dbx("SELECT reminder_fee_paid_at FROM office_docs WHERE id=?", (rid,))[0][0], f"{who}: opened again: no day")
    r = s.post(B + f"{D_}/{rid}/fee", json={"state": "paid"})
    check(r.ok and kt.dbx("SELECT reminder_fee_paid_at FROM office_docs WHERE id=?", (rid,))[0][0] == testclock.today().isoformat(),
          f"{who}: without a day: today, as before")


FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
r = Fr.put(B + OFC + "/settings", json={"lang": "de", "currency": "EUR", "payment_days": 14, "company_fields": {
    "name": "Frida Beispiel", "street": "Weg 2", "zip": "12345", "city": "Musterstadt", "country": "DE", "tax_number": "12/345/67891",
    "iban": "DE89370400440532013000"}})
check(r.ok, f"freelancer: office settings {r.text[:200]}")
fee_personal(Fr, "freelancer")

# 2.784.0 (#5387 review): a fee paid in a month that is locked keeps its day - neither moved to an open month nor opened again
rid = kt.dbx("SELECT id FROM office_docs WHERE org_id=(SELECT id FROM orgs WHERE personal_of=?) AND kind='reminder' ORDER BY id DESC LIMIT 1", (FID,))[0][0]
check(Fr.post(B + f"{D_}/{rid}/fee", json={"state": "paid", "day": f"{Y}-04-20"}).ok, "freelancer: the fee back on its April day")
r = Fr.post(B + OFC + "/periods/lock", json={"through": f"{Y}-05", "confirm": f"05/{Y}"})
check(r.ok, f"freelancer: lock through 05/{Y} {r.status_code} {r.text[:160]}")
r1 = Fr.post(B + f"{D_}/{rid}/fee", json={"state": "paid", "day": f"{Y}-06-02"})
r2 = Fr.post(B + f"{D_}/{rid}/fee", json={"state": ""})
check(r1.status_code == 409 and r2.status_code == 409, f"the paid day in a locked month: moving and opening again 409 ({r1.status_code} {r2.status_code})")
check(kt.dbx("SELECT reminder_fee_paid_at, reminder_fee_state FROM office_docs WHERE id=?", (rid,))[0] == (f"{Y}-04-20", "paid"),
      "the locked fee day stays")
# 2.990.0 (#5484): a fee paid before 2.545 has no day and counts on the reminder's date (April, locked): opening it again or
# moving it to an open month is refused too (was: the empty day skipped the period check)
kt.dbx("UPDATE office_docs SET reminder_fee_paid_at=NULL WHERE id=?", (rid,))
r1 = Fr.post(B + f"{D_}/{rid}/fee", json={"state": "paid", "day": f"{Y}-06-02"})
r2 = Fr.post(B + f"{D_}/{rid}/fee", json={"state": ""})
check(r1.status_code == 409 and r2.status_code == 409, f"an old fee without day in a locked month: moving and opening again 409 ({r1.status_code} {r2.status_code})")
check(kt.dbx("SELECT COALESCE(reminder_fee_paid_at, ''), reminder_fee_state FROM office_docs WHERE id=?", (rid,))[0] == ("", "paid"),
      "the old fee stays paid without day")

sys.exit(kt.done("muster_gmbh_jahr"))
