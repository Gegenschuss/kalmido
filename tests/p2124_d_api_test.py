#!/usr/bin/env python3
"""2.124.0 API tests, part D (#2342, office: the account balance from the bank reconciliation), own container (start.sh, org
encryption on). Invented companies, accounts and figures only (statements made here). freelancer-matrix: office  tenant-matrix: office
 - a person without organisation (personal office, its own admin): without balances the cash flow answers exactly as before;
   CAMT.053 with opening / closing balances (CLBD before CLAV, a balance in another currency left out): the preview names
   them, the bookings stay as before; two accounts (two statements) are added up, the day = the older one; no start balance
   -> suggest_start; taken over as the start (the start route of #2341) -> computed + difference; a start by hand wins; a real
   balance by hand wins over the bank; CSV with a balance column: guessed, the chronologically last row counts (newest
   first and oldest first), the account = the typed name or the IBAN of the own account column; an import taken back hides
   its balance, restored it counts again
 - an organisation's admin: amount and account encrypted at rest; a member without the admin role 403; another
   organisation never sees the balances and gets 404 on a foreign import; the key figures still answer
usage: p2124_d_api_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
K = O + "/bank"
ST, ACT = O + "/cashflow/start", O + "/cashflow/actual"
IBAN1, IBAN2, IBAN3 = "DE02120300000000202051", "DE89370400440532013000", "DE75512108001245126199"


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


def enc(v):
    return str(v or "").startswith("kenc1:")


if not (os.environ.get("P2124D_NOSTART") or os.environ.get("KMT_NOSTART")):
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
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office, its own admin)

TODAY = testclock.today()
P0 = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)  # the 1st of the month before: every day used lies in the past
PREV, MONTH = P0.isoformat()[:7], TODAY.isoformat()[:7]


def d(n):
    return (P0 + timedelta(days=n - 1)).isoformat()


def de(day):
    return f"{day[8:10]}.{day[5:7]}.{day[:4]}"


def cf(s, basis="gross", fm=PREV, months=3):
    r = s.get(B + O + f"/cashflow?from={fm}&months={months}&basis={basis}")
    assert r.ok, r.text
    return r.json()


def row(j, mo):
    return next(x for x in j["rows"] if x["month"] == mo)


def plain(j):
    return "bank" not in j and not any("bank" in r for r in j["rows"])


def computed(j, day):
    """start + money in - out of the entries from the start day up to the end of day (what the server must answer)."""
    st = j["start"]
    s = float(st["amount"])
    for e in j["entries"]:
        if st["day"] <= e["date"] <= day:
            s += float(e["amount"]) if e["dir"] == "in" else -float(e["amount"])
    return round(s, 2)


def camt(acct, bals, ntry=""):
    b = "".join(f'<Bal><Tp><CdOrPrtry><Cd>{cd}</Cd></CdOrPrtry></Tp><Amt Ccy="{ccy}">{amt}</Amt><CdtDbtInd>{ind}</CdtDbtInd><Dt><Dt>{day}</Dt></Dt></Bal>'
                for cd, amt, ind, day, ccy in bals)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>STMT-{acct[-4:]}</Id>
<Acct><Id><IBAN>{acct}</IBAN></Id><Ccy>EUR</Ccy></Acct>{b}{ntry}</Stmt></BkToCstmrStmt></Document>"""


def ntry(amt, ind, day, ref, name):
    return (f'<Ntry><Amt Ccy="EUR">{amt}</Amt><CdtDbtInd>{ind}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{day}</Dt></BookgDt>'
            f'<AcctSvcrRef>{ref}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Dbtr><Pty><Nm>{name}</Nm></Pty></Dbtr></RltdPties>'
            f'<RmtInf><Ustrd>Rechnung {ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>')


# ---------------------------------------------------------------- the personal office
check(Fr.get(B + O + "/settings").json().get("role") == "admin", "personal office: the person is its admin")
r = Fr.post(B + O + "/fixed-costs", json={"label": "Miete Beispiel", "amount": "100", "vat_rate": 19, "repeat": "monthly", "start": d(15)})
check(r.status_code == 201, "a fixed cost " + r.text[:200])
J0 = cf(Fr)
check(plain(J0) and "start" not in J0, f"without balances: the answer as before {list(J0)}")

C1 = camt(IBAN1, [("OPBD", "1000.00", "CRDT", d(1), "EUR"), ("CLAV", "1490.00", "CRDT", d(20), "EUR"), ("CLBD", "1500.00", "CRDT", d(20), "EUR")],
          ntry("500.00", "CRDT", d(10), "R-1001", "Kunde Eins GmbH"))
r = Fr.post(B + K + "/import/preview", json={"text": C1, "filename": "konto1.xml"})
check(r.ok, "camt preview " + r.text[:200])
p = r.json()
check(len(p["rows"]) == 1 and p["rows"][0]["amount"] == "500.00" and p["rows"][0]["day"] == d(10) and p["count"] == 1, f"camt: the bookings as before {p.get('rows')}")
check(sorted((x["kind"], x["day"], x["amount"], x["account"]) for x in p.get("balances", []))
      == [("close", d(20), "1500.00", IBAN1), ("open", d(1), "1000.00", IBAN1)], f"camt: opening + closing balance, CLBD before CLAV {p.get('balances')}")
r = Fr.post(B + K + "/import", json={"text": C1, "filename": "konto1.xml"})
check(r.status_code == 201 and r.json()["count"] == 1 and r.json().get("balances") == 2, "camt import " + r.text[:200])
I1 = r.json()["import"]["id"]
j = cf(Fr)
check(j.get("bank", {}).get("amount") == "1500.00" and j["bank"]["day"] == d(20) and j["bank"].get("suggest_start") is True
      and "diff" not in j["bank"], f"one account: the closing balance, no start yet -> suggested {j.get('bank')}")
check(row(j, PREV).get("bank", {}).get("amount") == "1500.00" and "bank" not in row(j, MONTH), f"per month: the balances inside it {[x.get('bank') for x in j['rows']]}")
check([x["in"] for x in j["rows"]] == [x["in"] for x in J0["rows"]] and [x["balance"] for x in j["rows"]] == [x["balance"] for x in J0["rows"]]
      and not any("account" in x for x in j["rows"]), "the computed values stay, no account balance without a start")

C2 = camt(IBAN2, [("CLBD", "200.00", "DBIT", d(18), "EUR"), ("CLBD", "999.00", "CRDT", d(19), "USD"), ("ITBD", "50.00", "CRDT", d(19), "EUR")],
          ntry("80.00", "DBIT", d(12), "R-2001", "Lieferant Beispiel"))
r = Fr.post(B + K + "/import", json={"text": C2, "filename": "konto2.xml"})
check(r.status_code == 201 and r.json().get("balances") == 1, "second account: USD and an intermediate balance left out " + r.text[:200])
I2 = r.json()["import"]["id"]
j = cf(Fr)
b = j.get("bank", {})
check(b.get("amount") == "1300.00" and b.get("day") == d(18) and sorted(a["account"] for a in b.get("accounts", [])) == sorted([IBAN1, IBAN2]),
      f"two accounts added up, the day = the older one {b}")
check({a["account"]: a["amount"] for a in b.get("accounts", [])} == {IBAN1: "1500.00", IBAN2: "-200.00"}, "a debit balance is negative")

# taken over as the start balance (the client PUTs the start route of #2341)
r = Fr.put(B + ST, json={"amount": b["amount"], "day": b["day"]})
check(r.ok and r.json()["start"]["amount"] == "1300.00", "taken over as the start " + r.text[:200])
j = cf(Fr)
check(j["bank"].get("suggest_start") is False and j["bank"].get("computed") == f"{computed(j, d(18)):.2f}" and j["bank"].get("diff") == "0.00",
      f"with the start on the bank's day: computed = bank {j['bank']}")
# a start by hand wins; the difference against the running balance
r = Fr.put(B + ST, json={"amount": "1000", "day": d(1)})
check(r.ok, "a start by hand " + r.text[:200])
j = cf(Fr)
exp = computed(j, d(18))
check(j["start"] == {"amount": "1000.00", "day": d(1)}, f"the start by hand stays {j.get('start')}")
check(j["bank"].get("computed") == f"{exp:.2f}" and j["bank"].get("diff") == f"{1300 - exp:.2f}", f"difference bank - computed ({exp}) {j['bank']}")
rb = row(j, PREV).get("bank", {})
check(rb.get("diff") == j["bank"].get("diff") and rb.get("day") == d(18), f"the month's balance with its difference {rb}")
jn = cf(Fr, "net")
check(jn["bank"].get("computed") == j["bank"]["computed"] and row(jn, PREV)["bank"].get("computed") == rb.get("computed"),
      f"net basis: the bank compared with the gross account {jn['bank']}")
# a real balance by hand wins over the bank (#2341 real / diff), the bank row stays beside it
assert Fr.put(B + ACT, json={"month": PREV, "amount": "5000"}).ok
j = cf(Fr)
check(row(j, PREV).get("real") == "5000.00" and row(j, PREV).get("diff") == f"{5000 - float(row(j, PREV)['account']):.2f}"
      and row(j, PREV).get("bank", {}).get("amount") == "1300.00", f"the real balance by hand wins {row(j, PREV)}")
assert Fr.put(B + ACT, json={"month": PREV, "amount": None}).ok
# a view without the month: the computed value on the bank's day comes from that month all the same
jl = cf(Fr, fm=MONTH)
check(jl.get("bank", {}).get("computed") == j["bank"]["computed"] and not any("bank" in x for x in jl["rows"]), f"bank day before the view {jl.get('bank')}")

# CSV with a balance column: newest first (most banks) and oldest first
HEAD = "Buchungstag;Name;Verwendungszweck;Betrag;Saldo\n"
DESC = HEAD + f"{de(d(22))};Laden Beispiel;Einkauf;-10,00;790,00\n{de(d(22))};Kiosk Beispiel;Zeitung;-5,00;800,00\n{de(d(21))};Kunde Zwei;Zahlung;5,00;805,00\n"
ASC = HEAD + f"{de(d(21))};Kunde Zwei;Zahlung;5,00;805,00\n{de(d(22))};Kiosk Beispiel;Zeitung;-5,00;800,00\n{de(d(22))};Laden Beispiel;Einkauf;-10,00;790,00\n"
pv = Fr.post(B + K + "/import/preview", json={"text": DESC, "filename": "kasse.csv"}).json()
check(pv.get("guess", {}).get("balance") == 4 and pv["guess"].get("account") is None and pv.get("accounts") == sorted([IBAN1, IBAN2]), f"csv: the balance column guessed {pv.get('guess')} {pv.get('accounts')}")
MAP = {k: pv["guess"].get(k) for k in ("date", "amount", "amount_in", "amount_out", "title", "counterpart", "decimal", "date_format", "balance")}
for name, text in (("newest first", DESC), ("oldest first", ASC)):
    r = Fr.post(B + K + "/import/preview", json={"text": text, "mapping": MAP, "account": "Kasse Beispiel"})
    check(r.ok and r.json().get("balances") == [{"account": "Kasse Beispiel", "day": d(22), "amount": "790.00", "kind": "close"}],
          f"csv {name}: the balance of the last booking {r.text[:300]}")
r = Fr.post(B + K + "/import/preview", json={"text": DESC, "mapping": {k: v for k, v in MAP.items() if k != "balance"}})
check(r.ok and r.json().get("balances") == [] and len(r.json()["rows"]) == 3, "csv without a balance column: no balance, the bookings as before")
check(Fr.post(B + K + "/import/preview", json={"text": DESC, "mapping": dict(MAP, balance=9)}).status_code == 400, "a balance column out of range 400")
r = Fr.post(B + K + "/import/preview", json={"text": DESC, "mapping": MAP})
check(r.ok and r.json()["balances"][0]["account"] == "Main account", "csv without a name: the main account")
IBC = "Auftragskonto;Buchungstag;Name;Verwendungszweck;Betrag;Saldo\n" + f"{IBAN3};{de(d(22))};Laden Beispiel;Einkauf;-10,00;790,00\n"
pv2 = Fr.post(B + K + "/import/preview", json={"text": IBC}).json()
check(pv2["guess"].get("account") == 0 and pv2["guess"].get("balance") == 5, f"csv: the own account column guessed {pv2.get('guess')}")
r = Fr.post(B + K + "/import/preview", json={"text": IBC, "mapping": {k: pv2["guess"].get(k) for k in list(MAP) + ["account"]}, "account": "Kasse Beispiel"})
check(r.ok and r.json()["balances"][0]["account"] == IBAN3, "csv: the IBAN of the own account column wins over the name " + r.text[:200])
r = Fr.post(B + K + "/import", json={"text": DESC, "filename": "kasse.csv", "mapping": MAP, "account": "Kasse Beispiel"})
check(r.status_code == 201 and r.json().get("balances") == 1, "csv import with the balance " + r.text[:200])
I3 = r.json()["import"]["id"]
j = cf(Fr)
check(j["bank"]["amount"] == "2090.00" and j["bank"]["day"] == d(18) and len(j["bank"]["accounts"]) == 3, f"three accounts {j['bank']}")
check(Fr.post(B + K + "/import/preview", json={"text": DESC}).json().get("accounts") == sorted([IBAN1, IBAN2, "Kasse Beispiel"]), "the known account names offered")

# an import taken back: its balance no longer counts; restored: it counts again
r = Fr.post(B + K + f"/imports/{I2}/undo")
check(r.ok, "import 2 taken back " + r.text[:200])
j = cf(Fr)
check(j["bank"]["amount"] == "2290.00" and j["bank"]["day"] == d(20) and IBAN2 not in [a["account"] for a in j["bank"]["accounts"]], f"taken back: its balance is gone {j['bank']}")
check(Fr.post(B + K + f"/imports/{I2}/restore").ok and cf(Fr)["bank"]["amount"] == "2090.00", "restored: it counts again")
for i in (I1, I2, I3):
    Fr.post(B + K + f"/imports/{i}/undo")
Fr.delete(B + ST)
check(plain(cf(Fr)), "every import taken back: the answer as before")

# ---------------------------------------------------------------- an organisation: encrypted at rest, rights
r = A.post(B + K + "/import", json={"text": C1, "filename": "alpha.xml"})
check(r.status_code == 201, "organisation: camt import " + r.text[:200])
IA = r.json()["import"]["id"]
bl = sql("SELECT amount, account, kind FROM office_bank_balances WHERE import_id=?", (IA,))
check(len(bl) == 2 and all(enc(x[0]) and enc(x[1]) for x in bl), f"amount and account encrypted at rest {[(x[2]) for x in bl]}")
check(cf(A).get("bank", {}).get("amount") == "1500.00", "organisation: the balance in the cash flow")
check(Bo.get(B + O + f"/cashflow?from={PREV}&months=3").status_code == 403 and Bo.post(B + K + "/import/preview", json={"text": C1}).status_code == 403
      and Bo.post(B + K + "/import", json={"text": C1}).status_code == 403, "a member without the admin role: 403")
check(plain(cf(Ca)), "another organisation sees none of the balances")
check(Ca.post(B + K + f"/imports/{IA}/undo").status_code == 404 and cf(A)["bank"]["amount"] == "1500.00", "another organisation: 404 on a foreign import")
check(plain(cf(Fr)), "the personal office sees nothing of the organisation")
check(A.get(B + O + "/kpi").ok, "the key figures still answer")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
