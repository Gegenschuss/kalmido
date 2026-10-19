#!/usr/bin/env python3
"""2.123.0 API tests, part D (#2341, office: the account balance of the cash flow; #2351 the installment list), own container
(start.sh, org encryption on). Invented companies, people and figures only. freelancer-matrix: office  tenant-matrix: office
 - a person without organisation (personal office, its own admin): without a start balance the cash flow answers exactly as
   before (no start / account / adjust / manual / real); start balance 1,000.00 on the 1st of this month + a fixed cost
   100 net (19 %) monthly: the account at the end of this month 881.00, the next 762.00, the one after 643.00 (the preview);
   a correction by hand (in 250, next month) and one (out 50, this month) count only in the account, the computed values
   (in / out / balance) stay; edit / delete (the answer carries it for the undo) / post again; the net basis shows net
   amounts but the account stays gross; a start in the month before the view carries over (with that month's correction);
   months before the start day have no account; the real balance at a month's end shows the difference (removed again:
   gone); bad values 400; the start balance removed = the answer as before
 - an organisation's admin: amounts and notes encrypted at rest; a member without the admin role 403 on every route;
   another organisation 404 on a foreign correction and never sees it; an agent token 403; the key figures still answer
 - #2351: the progress rows of the installment list carry open_text in the document's number format ("2.332,00 €")
usage: p2123_d_api_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time

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
ST, ADJ, ACT = O + "/cashflow/start", O + "/cashflow/adjust", O + "/cashflow/actual"


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


def add_months(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


if not (os.environ.get("P2123D_NOSTART") or os.environ.get("KMT_NOSTART")):
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
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office, its own admin)

MONTH = testclock.today().isoformat()[:7]
PREV, NEXT, NEXT2 = add_months(MONTH, -1), add_months(MONTH, 1), add_months(MONTH, 2)


def cf(s, basis="gross", fm=MONTH, months=3):
    r = s.get(B + O + f"/cashflow?from={fm}&months={months}&basis={basis}")
    assert r.ok, r.text
    return r.json()


def row(j, mo):
    return next(x for x in j["rows"] if x["month"] == mo)


def acc(j, mo):
    v = row(j, mo).get("account")
    return None if v is None else round(float(v), 2)


NEW_KEYS = ("start", "adjust")
NEW_ROW_KEYS = ("account", "manual", "real", "diff")


def plain(j):
    """True when the answer carries none of the 2.123 additions."""
    return not any(k in j for k in NEW_KEYS) and not any(k in r for r in j["rows"] for k in NEW_ROW_KEYS)


# ---------------------------------------------------------------- the personal office
check(Fr.get(B + O + "/settings").json().get("role") == "admin", "personal office: the person is its admin")
r = Fr.post(B + O + "/fixed-costs", json={"label": "Miete Büro", "amount": "100", "vat_rate": 19, "repeat": "monthly", "start": MONTH + "-01"})
check(r.status_code == 201, "a fixed cost " + r.text[:200])
J0 = cf(Fr)
check(plain(J0), f"without a start balance: the answer as before {list(J0)}")
check(Fr.get(B + ST).json().get("start") is None, "no start balance yet")
r = Fr.put(B + ST, json={"amount": "1.000,00", "day": MONTH + "-01"})
check(r.ok and r.json()["start"]["amount"] == "1000.00" and r.json()["start"]["day"] == MONTH + "-01" and r.json()["prev"] is None, "start balance set " + r.text[:200])
j = cf(Fr)
check(j.get("start") == {"amount": "1000.00", "day": MONTH + "-01"}, f"the cash flow carries the start {j.get('start')}")
check((acc(j, MONTH), acc(j, NEXT), acc(j, NEXT2)) == (881.0, 762.0, 643.0), f"the running account balance incl. the preview {[acc(j, m) for m in (MONTH, NEXT, NEXT2)]}")
check([x["in"] for x in j["rows"]] == [x["in"] for x in J0["rows"]] and [x["out"] for x in j["rows"]] == [x["out"] for x in J0["rows"]]
      and [x["balance"] for x in j["rows"]] == [x["balance"] for x in J0["rows"]] and j["entries"] == J0["entries"], "the computed values stay as they are")

# corrections by hand
r = Fr.post(B + ADJ, json={"month": NEXT, "dir": "in", "amount": "250", "note": "Barzahlung Flohmarkt"})
check(r.status_code == 201 and r.json()["amount"] == "250.00" and r.json()["manual"] is True, "a correction in " + r.text[:200])
A1 = r.json()["id"]
r = Fr.post(B + ADJ, json={"month": MONTH, "dir": "out", "amount": 50, "note": "Bar bezahlt"})
check(r.status_code == 201, "a correction out " + r.text[:200])
A2 = r.json()["id"]
j = cf(Fr)
check((acc(j, MONTH), acc(j, NEXT), acc(j, NEXT2)) == (831.0, 962.0, 843.0), f"corrections count in the account {[acc(j, m) for m in (MONTH, NEXT, NEXT2)]}")
check(row(j, NEXT).get("manual") == {"in": "250.00", "out": "0.00"} and row(j, MONTH).get("manual") == {"in": "0.00", "out": "50.00"}
      and "manual" not in row(j, NEXT2), f"per month the corrections apart {[x.get('manual') for x in j['rows']]}")
check([x["in"] for x in j["rows"]] == [x["in"] for x in J0["rows"]] and [x["balance"] for x in j["rows"]] == [x["balance"] for x in J0["rows"]]
      and j["entries"] == J0["entries"], "corrections never change the computed values")
check(sorted(a["id"] for a in j.get("adjust", [])) == sorted([A1, A2]) and all(a["manual"] for a in j["adjust"]), f"the list of corrections {j.get('adjust')}")
r = Fr.patch(B + f"{ADJ}/{A1}", json={"amount": "300,00"})
check(r.ok and r.json()["amount"] == "300.00" and r.json()["note"] == "Barzahlung Flohmarkt", "a correction edited " + r.text[:200])
check(acc(cf(Fr), NEXT) == 1012.0, "the edit counts")
r = Fr.delete(B + f"{ADJ}/{A1}")
check(r.ok and r.json()["item"]["amount"] == "300.00" and r.json()["item"]["month"] == NEXT, "a correction deleted, its row in the answer " + r.text[:200])
check(acc(cf(Fr), NEXT) == 712.0, "deleted: no longer counted")
it = r.json()["item"]
r = Fr.post(B + ADJ, json={k: it[k] for k in ("month", "dir", "amount", "note")})
check(r.status_code == 201 and acc(cf(Fr), NEXT) == 1012.0, "the undo posts it again")
A1 = r.json()["id"]
for bad in ({"month": "2026-13", "dir": "in", "amount": 1}, {"month": MONTH, "dir": "sideways", "amount": 1}, {"month": MONTH, "dir": "in", "amount": 0},
            {"month": MONTH, "dir": "in", "amount": "-5"}, {"month": MONTH, "dir": "in", "amount": "abc"}, {"month": MONTH, "dir": "in"}):
    check(Fr.post(B + ADJ, json=bad).status_code == 400, f"a bad correction 400 {bad}")
check(Fr.patch(B + f"{ADJ}/999999", json={"amount": 1}).status_code == 404, "an unknown correction 404")

# the net basis: net amounts, the account stays gross
jn = cf(Fr, "net")
check(round(float(row(jn, MONTH)["out"]["actual"]) + float(row(jn, MONTH)["out"]["plan"]), 2) == 100.0 and acc(jn, MONTH) == 831.0,
      f"net basis: out 100 net, the account gross {row(jn, MONTH)}")

# the real balance at the end of a month
r = Fr.put(B + ACT, json={"month": MONTH, "amount": "851,00"})
check(r.ok and r.json()["amount"] == "851.00" and r.json()["prev"] is None, "a real balance " + r.text[:200])
j = cf(Fr)
check(row(j, MONTH).get("real") == "851.00" and row(j, MONTH).get("diff") == "20.00", f"the difference real - computed {row(j, MONTH)}")
check("real" not in row(j, NEXT) and "diff" not in row(j, NEXT), "other months without a real balance")
r = Fr.put(B + ACT, json={"month": MONTH, "amount": "800"})
check(r.ok and r.json()["prev"] == "851.00" and row(cf(Fr), MONTH).get("diff") == "-31.00", "changed: the old one in the answer, a negative difference")
check(Fr.put(B + ACT, json={"month": MONTH, "amount": None}).ok and "real" not in row(cf(Fr), MONTH), "removed again")
check(Fr.put(B + ACT, json={"month": "x", "amount": 1}).status_code == 400 and Fr.put(B + ACT, json={"month": MONTH, "amount": "abc"}).status_code == 400,
      "bad real balance 400")

# a start in the month before the view carries over (with that month's correction)
check(Fr.post(B + ADJ, json={"month": PREV, "dir": "in", "amount": 10}).status_code == 201, "a correction in the month before")
r = Fr.put(B + ST, json={"amount": 1000, "day": PREV + "-01"})
check(r.ok and r.json()["prev"]["day"] == MONTH + "-01", "start moved back, the old one in the answer " + r.text[:200])
check(acc(cf(Fr), MONTH) == 841.0, f"carried over from the month before {acc(cf(Fr), MONTH)}")
# months before the start day have no account
check(Fr.put(B + ST, json={"amount": 1000, "day": MONTH + "-01"}).ok, "start back to this month")
jp = cf(Fr, fm=PREV)
check("account" not in row(jp, PREV) and acc(jp, MONTH) == 831.0, f"before the start day no account {row(jp, PREV)}")
for bad in ({"amount": "abc", "day": MONTH + "-01"}, {"amount": 1, "day": "1999-12-31"}, {"amount": 1, "day": "2026-02-30"}, {"amount": 1},
            {"amount": "", "day": MONTH + "-01"}, {"amount": True, "day": MONTH + "-01"}):
    check(Fr.put(B + ST, json=bad).status_code == 400, f"a bad start balance 400 {bad}")
check(Fr.put(B + ST, json={"amount": "-250,50", "day": MONTH + "-01"}).ok and Fr.get(B + ST).json()["start"]["amount"] == "-250.50", "a negative start (overdraft)")
# removed: the answer as before (corrections stay listed, they are data of their own)
r = Fr.delete(B + ST)
check(r.ok and r.json()["prev"]["amount"] == "-250.50", "start balance removed, the old one in the answer")
j = cf(Fr)
check("start" not in j and not any("account" in x for x in j["rows"]), "without a start: no account balance")
for a in [A1, A2] + [a["id"] for a in cf(Fr, fm=PREV)["adjust"] if a["month"] == PREV]:
    Fr.delete(B + f"{ADJ}/{a}")
check(plain(cf(Fr)), "nothing set any more: the answer exactly as before")

# ---------------------------------------------------------------- an organisation: encrypted at rest, rights
check(A.put(B + ST, json={"amount": "5000", "day": MONTH + "-01"}).ok, "organisation: start balance")
r = A.post(B + ADJ, json={"month": MONTH, "dir": "in", "amount": "120", "note": "Privateinlage Beispiel"})
check(r.status_code == 201, "organisation: a correction " + r.text[:200])
OA = r.json()["id"]
check(A.put(B + ACT, json={"month": MONTH, "amount": "5100"}).ok, "organisation: a real balance")
j = cf(A)
check(acc(j, MONTH) == 5120.0 and row(j, MONTH).get("diff") == "-20.00", f"organisation: account and difference {row(j, MONTH)}")
st = sql("SELECT amount FROM office_cf_start WHERE org_id=?", (ORG,))
ad = sql("SELECT amount, note FROM office_cf_adjust WHERE id=?", (OA,))
ac = sql("SELECT amount FROM office_cf_actual WHERE org_id=?", (ORG,))
check(st and enc(st[0][0]) and ad and enc(ad[0][0]) and enc(ad[0][1]) and ac and enc(ac[0][0]), "amounts and the note encrypted at rest")
for m, path, b in (("get", ST, None), ("put", ST, {"amount": 1, "day": MONTH + "-01"}), ("delete", ST, None), ("post", ADJ, {"month": MONTH, "dir": "in", "amount": 1}),
                   ("patch", f"{ADJ}/{OA}", {"amount": 1}), ("delete", f"{ADJ}/{OA}", None), ("put", ACT, {"month": MONTH, "amount": 1})):
    check(getattr(Bo, m)(B + path, json=b).status_code == 403, f"a member without the admin role: 403 on {m.upper()} {path}")
    check(getattr(requests, m)(B + path, headers=AGH, json=b).status_code == 403, f"an agent token: 403 on {m.upper()} {path}")
check(Ca.patch(B + f"{ADJ}/{OA}", json={"amount": 1}).status_code == 404 and Ca.delete(B + f"{ADJ}/{OA}").status_code == 404, "another organisation: 404 on a foreign correction")
jc = cf(Ca)
check(plain(jc) and Ca.get(B + ST).json()["start"] is None, "another organisation sees nothing of it")
check(plain(cf(Fr)), "the personal office sees nothing of the organisation")
check(A.get(B + O + "/kpi").ok, "the key figures still answer")
check(A.get(B + f"{ADJ}/{OA}").status_code in (404, 405), "no read route per correction")

# ---------------------------------------------------------------- #2351: the installment list in the document's number format
r = Fr.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {
    "name": "Frida Film", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "tax_number": "12/345/67890",
    "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
check(r.ok, "#2351: document language German " + r.text[:200])
cl = Fr.post(B + "/api/clients", json={"name": "Kunde Beispiel GmbH", "street": "Weg 2", "zip": "20000", "city": "Beispielstadt", "country": "DE"}).json()["id"]
r = Fr.post(B + O + "/docs", json={"project_title": "Imagefilm", "client_id": cl, "service_from": MONTH + "-01", "service_to": MONTH + "-02"})
assert r.status_code == 201, r.text
OFF = r.json()["id"]
assert Fr.put(B + f"{O}/docs/{OFF}/items", json={"items": [{"title": "Dreh", "qty": 2, "unit": "day", "rate": 4000, "tax": "standard"},
                                                          {"title": "Buch", "qty": 1, "unit": "flat", "rate": 2000, "tax": "reduced"}]}).ok
r = Fr.post(B + f"{O}/docs/{OFF}/invoice", json={"inv_type": "progress", "amount": 2000})
check(r.status_code == 201, "#2351: a progress invoice " + r.text[:200])
check(Fr.post(B + f"{O}/docs/{r.json()['id']}/finalize").ok, "#2351: finalised")
pr = Fr.get(B + f"{O}/docs/{OFF}/progress").json()["progress"]
txt = [(x.get("open_text") or "").replace(" ", " ").replace(" ", " ") for x in pr]
check(len(pr) == 1 and txt == ["2.332,00 €"] and pr[0]["open"] == "2332.00", f"#2351: open_text in German format {txt} {[x.get('open') for x in pr]}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
