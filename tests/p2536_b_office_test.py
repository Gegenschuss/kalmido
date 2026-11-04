#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.536.0 B (#4334, #4335) API tests: card fees in the books and depreciation without a purchase, own container (start.sh, org
encryption on). Invented companies, cards and figures only; every statement and receipt is made here.
tenant-matrix: office  freelancer-matrix: office
 - #4334: positions of a confirmed card statement marked "no receipt needed" (the fees and interest by themselves, money
   back by hand) count in the income/expense statement (EUeR, own line, no input tax) and in the cash flow (kind card, a
   refund comes in), as the DATEV export books them; a draft, open, private and matched positions do not (a matched one
   counts through its receipt, once); the bank booking of the statement's total is no expense of its own
 - #4335: depreciation "none": no plan, no depreciation line, a linked receipt counts in full (before: 400, and a price
   was always written off); a device depreciated without a linked receipt is named in the EUeR (afa_no_receipt) and carries
   receipt_missing; a device with a linked receipt or only a new value for the insurance list is not
 - both in an organisation and for a person without an organisation (personal office)
usage: p2536_b_office_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time
from decimal import Decimal

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
from kt import FAILS, OKS, check, sess, until, B, H, DATA  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"
K = O + "/cards"
E = O + "/equipment"
FEAT = "cal,comments,collab,office,clients,docs"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


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
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A, "frida")
Y = testclock.today().year - 1  # a closed year: everything of the test lies in the past (cash flow: actual)
LINES = [f"Kreditkartenabrechnung vom 15.01.{Y}", "Beispielbank Mastercard Business", "Karte 5232 12XX XXXX 4711", "Saldo Vormonat 100,00-",
         "28.12. 29.12. Cafe Beispiel Berlin 12,50-", "02.01. 02.01. Ihre Zahlung 100,00+", "03.01. 04.01. Cloud Beispiel Inc USD 20,00 18,40-",
         "Auslandseinsatzentgelt 1,75% 0,32-", "05.01. 05.01. Gutschrift Beispielhaendler 5,00+", "10.01. 10.01. Jahresentgelt 30,00-", "Neuer Saldo 56,22-"]


def doc(s, ws, name, amount, day, receipt=None):
    """A document in workspace ws with amount and date by hand; receipt = {category, vat_pct} makes it a receipt."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, pdf(["Rechnung " + name]), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    until(lambda: (sql("SELECT state FROM doc_meta WHERE node_id=?", (nid,)) or [["wait"]])[0][0] in ("done", "failed"), 30)
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    if receipt is not None:
        r = s.put(B + f"/api/docs/{nid}/receipt", json={**receipt, "keep": True})
        assert r.ok, r.text
    return nid


def euer(s):
    return s.get(B + O + f"/books/euer?year={Y}").json()


def line(eu, key):
    return next((x for x in eu["expenses"] if x["key"] == key), None)


def card_entries(s):
    d = s.get(B + O + f"/cashflow?from={Y}-01&months=12").json()
    return [e for e in d["entries"] if e["kind"] == "card"]


def card_sums(s):
    es = card_entries(s)
    return (sum((Decimal(e["amount"]) for e in es if e["dir"] == "out"), Decimal(0)), sum((Decimal(e["amount"]) for e in es if e["dir"] == "in"), Decimal(0)), es)


def camt(entries):
    return ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>S</Id>'
            '<Acct><Id><IBAN>DE02120300000000202051</IBAN></Id><Ccy>EUR</Ccy></Acct>' + "".join(entries) + '</Stmt></BkToCstmrStmt></Document>')


def ntry(amt, day, ref):
    return (f'<Ntry><Amt Ccy="EUR">{amt}</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{day}</Dt></BookgDt><AcctSvcrRef>{ref}</AcctSvcrRef>'
            f'<NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>Beispielbank Kartenservice</Nm></Pty></Cdtr></RltdPties><RmtInf><Ustrd>Buchung {ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>')


def cards(s, uid, ws, who):
    """#4334 for one office."""
    r = s.post(B + K, json={"holder_id": uid, "last4": "4711"})
    assert r.status_code == 201, r.text
    r = s.post(B + f"{K}/{r.json()['id']}/statements", files={"file": ("stmt.pdf", pdf(LINES), "application/pdf")})
    check(r.status_code == 201 and r.json()["read"] is True, f"{who}: statement read {r.text[:200]}")
    sid = r.json()["statement"]["id"]
    L = {x["merchant"]: x for x in s.get(B + f"{K}/statements/{sid}").json()["lines"]}
    fee, year_fee = L["Auslandseinsatzentgelt 1,75%"], L["Jahresentgelt"]
    check(fee["state"] == "noreceipt" and year_fee["state"] == "noreceipt", f"{who}: the fees need no receipt")
    check(line(euer(s), "k:") is None and card_sums(s)[2] == [], f"{who}: a draft counts for nothing")
    assert s.post(B + f"{K}/statements/{sid}/confirm", json={}).ok
    k = line(euer(s), "k:")
    check(k and k["net"] == "30.32" and k["gross"] == "30.32" and k["vat"] == "0.00" and k["count"] == 2,
          f"{who}: EUeR: the two fees without a receipt, no input tax {k}")
    check(k and k["label"] == "Card fees without receipt", f"{who}: their own line {k}")
    out, in_, es = card_sums(s)
    check(out == Decimal("30.32") and in_ == 0 and len(es) == 2 and all(e["state"] == "actual" and e["statement_id"] == sid for e in es),
          f"{who}: cash flow: the fees go out on their day {es}")
    # open (cafe, cloud, money back) count nowhere; private does not either
    assert s.patch(B + f"{K}/lines/{L['Gutschrift Beispielhaendler']['id']}", json={"state": "private"}).ok
    check(line(euer(s), "k:")["net"] == "30.32" and card_sums(s)[:2] == (Decimal("30.32"), 0), f"{who}: a private position is no business expense")
    # money back marked "no receipt needed": less expense, money in
    assert s.patch(B + f"{K}/lines/{L['Gutschrift Beispielhaendler']['id']}", json={"state": "noreceipt"}).ok
    k = line(euer(s), "k:")
    out, in_, es = card_sums(s)
    check(k["net"] == "25.32" and k["count"] == 3 and out == Decimal("30.32") and in_ == Decimal("5.00"), f"{who}: money back lowers the line, comes in {k} {es}")
    # a matched position counts through its receipt, once
    base = euer(s)["expense_total"]["gross"]
    cloud = doc(s, ws, "cloud-rechnung.pdf", "18.40", f"{Y}-01-03")
    r = s.post(B + f"{K}/lines/{L['Cloud Beispiel Inc']['id']}/match", json={"node_id": cloud})
    check(r.ok, f"{who}: the cloud position matched {r.text[:200]}")
    eu = euer(s)
    check(line(eu, "k:")["net"] == "25.32" and Decimal(eu["expense_total"]["gross"]) == Decimal(base) + Decimal("18.40"),
          f"{who}: the matched receipt counts once {base} -> {eu['expense_total']}")
    check(len(card_sums(s)[2]) == 3, f"{who}: no card entry for the matched position in the cash flow")
    # the bank booking of the total only moves money to the card account
    assert s.post(B + O + "/bank/import", json={"text": camt([ntry("56.22", f"{Y}-01-20", "C-1")]), "filename": "k.xml"}).status_code == 201
    tx = next(t["id"] for t in s.get(B + O + "/bank/tx?state=all").json()["items"] if t["purpose"] == "Buchung C-1")
    r = s.post(B + O + f"/bank/tx/{tx}/match", json={"kind": "card", "id": sid})
    check(r.ok, f"{who}: the bank booking of the total matched {r.text[:200]}")
    eu = euer(s)
    check(line(eu, "k:")["net"] == "25.32" and Decimal(eu["expense_total"]["gross"]) == Decimal(base) + Decimal("18.40"),
          f"{who}: the total is no expense of its own {eu['expense_total']}")
    check(card_sums(s)[:2] == (Decimal("30.32"), Decimal("5.00")), f"{who}: nor an outflow")


def assets(s, ws, who):
    """#4335 for one office."""
    rc = doc(s, ws, "kamera-kauf.pdf", "1190.00", f"{Y}-03-01", {"category": "Material", "vat_pct": "19"})
    r = s.post(B + E, json={"name": "Kamera Beleg", "category": "Kamera", "purchase_date": f"{Y}-03-01", "purchase_net": "1000", "receipt_node_id": rc})
    check(r.status_code == 201, f"{who}: a device with its receipt {r.text[:200]}")
    cam = r.json()["id"]
    r = s.post(B + E, json={"name": "Laptop Ohne Beleg", "category": "Laptop", "purchase_date": f"{Y}-02-01", "purchase_net": "1500"})
    lap = r.json()["id"]
    r = s.post(B + E, json={"name": "Licht Nur Liste", "category": "Licht", "purchase_date": f"{Y}-04-01", "purchase_net": "2000", "afa_method": "none"})
    check(r.status_code == 201, f"{who}: depreciation none is a choice (was 400) {r.text[:200]}")
    lst = r.json()["id"]
    r = s.post(B + E, json={"name": "Stativ Neuwert", "category": "Stativ", "new_value": "900"})
    tri = r.json()["id"]
    rows = {x["id"]: x for x in s.get(B + E + "?archived=1").json()["items"]}
    check(rows[lst]["afa_method"] == "none" and rows[lst]["method"] == "" and rows[lst]["afa_plan"] == [] and rows[lst]["afa_year"] is None,
          f"{who}: none: no plan {rows[lst].get('method')} {rows[lst].get('afa_plan')}")
    check(rows[lst]["receipt_missing"] is False and rows[tri]["receipt_missing"] is False and rows[cam]["receipt_missing"] is False,
          f"{who}: no warning without depreciation or with a receipt")
    check(rows[lap]["receipt_missing"] is True and rows[lap]["method"] == "linear", f"{who}: depreciated without a receipt: warned")
    eu = euer(s)
    dep = line(eu, "a:")
    mat = line(eu, "c:material")
    exp_dep = sum((Decimal(p["afa"]) for i in (cam, lap) for p in rows[i]["afa_plan"] if p["year"] == Y), Decimal(0))
    check(dep and Decimal(dep["net"]) == exp_dep and dep["count"] == 2, f"{who}: depreciation only of the camera and the laptop {dep} / {exp_dep}")
    check(mat and mat["net"] == "0.00" and mat["vat"] == "190.00", f"{who}: the camera's receipt only with its input tax {mat}")
    check([x["name"] for x in eu["afa_no_receipt"]] == ["Laptop Ohne Beleg"], f"{who}: the EUeR names the device without a receipt {eu['afa_no_receipt']}")
    # the camera on none: its receipt counts in full, no depreciation of it any more
    r = s.patch(B + f"{E}/{cam}", json={"afa_method": "none"})
    check(r.ok, f"{who}: switched to none {r.text[:200]}")
    eu = euer(s)
    mat, dep = line(eu, "c:material"), line(eu, "a:")
    check(mat["net"] == "1000.00" and mat["gross"] == "1190.00", f"{who}: none: the receipt counts as a normal expense {mat}")
    check(dep and dep["count"] == 1, f"{who}: only the laptop is depreciated {dep}")
    # the laptop gets a receipt: the warning goes
    lrc = doc(s, ws, "laptop-kauf.pdf", "1785.00", f"{Y}-02-01", {"category": "Material", "vat_pct": "19"})
    assert s.patch(B + f"{E}/{lap}", json={"receipt_node_id": lrc}).ok
    check(euer(s)["afa_no_receipt"] == [], f"{who}: with its receipt the warning is gone")


for s in (A, Fr):
    assert s.put(B + O + "/settings", json={"company_fields": {"name": "Beispiel Film", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"}}).ok
cards(A, ALICE, f"org:{ORG}", "Alpha")
assets(A, f"org:{ORG}", "Alpha")
cards(Fr, FID, "private", "Frida")
assets(Fr, "private", "Frida")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
