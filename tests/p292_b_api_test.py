#!/usr/bin/env python3
"""2.92.0 API tests, part B (#1931): the value of equipment, own container (org encryption on). Invented companies,
devices and figures only.
 - new fields of a device (purchase day, net price, serial number, vendor, receipt, useful life, new / current value,
   policy); prices, values and the serial number encrypted at rest
 - depreciation: the suggested useful life by category, linear by the month (the years add up to the price), low-value
   assets (<= 800 net) in full in the purchase year, an own useful life; book value; the current value = book value unless
   an own value is set; new value = purchase price unless set
 - the insurance list: sums, CSV (semicolon, decimal comma, no formula injection), PDF, filtered by policy (#1925)
 - "take from receipt": a document of the office's document space proposes date, gross / net and vendor; a document of
   another organisation or a private one is 404 (and refused as the receipt of a device)
 - rights: a member never gets prices / values (list, row, export) and gets 403 on the value routes; another organisation
   sees nothing (404 / 403); the personal office of a person without organisation works the same
 - export / import of the master data: values travel for admins, receipt / policy ids of another office never do
tenant-matrix: office
usage: p292_b_api_test.py <datadir>"""
import base64
import csv
import io
import os
import subprocess
import sys
import time
from decimal import ROUND_HALF_UP, Decimal

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
O = "/api/office"
E = O + "/equipment"
FEAT = "cal,comments,collab,office,clients,docs"


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


def upload(s, name, text, ws, amount, day):
    """A document in workspace ws, recognised, then amount / date set by hand (the recognition may guess otherwise)."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf(text), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    for _ in range(60):
        if s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"):
            break
        time.sleep(0.5)
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day})
    assert r.ok, r.text
    return nid


def row(s, rid):
    return next((x for x in s.get(B + E + "?archived=1").json()["items"] if x["id"] == rid), None)


def m2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def plan(net, y, m, life):
    """The expected linear plan (like the server): cumulated by months, rounded per year."""
    net, out, done, yr = Decimal(net), [], Decimal(0), y
    first = 12 - m + 1
    while done < net:
        k = min(first + (yr - y) * 12, life)
        cum = m2(net * k / life) if k < life else net
        out.append({"year": yr, "afa": f"{cum - done:.2f}", "book": f"{net - cum:.2f}"})
        done, yr = cum, yr + 1
    return out


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
if not os.environ.get("P292B_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Solo"), ("erin", "Erin Solo")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Do, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
TODAY = testclock.today()
Y = TODAY.year

# ---------------------------------------------------------------- fields, encryption, depreciation
r = A.post(B + E, json={"name": "Kamera Alpha", "category": "Kamera", "daily_rate": 120, "purchase_date": "2024-03-15", "purchase_net": "2400",
                        "serial_no": "SN-0815", "vendor": "Fotohaus Beispiel"})
check(r.status_code == 201, "a device with purchase data " + r.text[:200])
CAM = r.json()["id"]
c1 = row(A, CAM)
check(c1["purchase_net"] == "2400.00" and c1["serial_no"] == "SN-0815" and c1["vendor"] == "Fotohaus Beispiel" and c1["purchase_date"] == "2024-03-15",
      f"the fields come back {c1}")
check(c1["life_suggest"] == 84 and c1["life_eff"] == 84 and c1["method"] == "linear", f"a camera: 84 months suggested, linear {c1.get('life_suggest')} {c1.get('method')}")
P = plan("2400", 2024, 3, 84)
check(c1["afa_plan"] == P and P[0] == {"year": 2024, "afa": "285.71", "book": "2114.29"} and P[-1]["book"] == "0.00"
      and sum(Decimal(p["afa"]) for p in P) == Decimal("2400"), f"linear by the month from March, the years add up {c1['afa_plan'][:3]}")
exp_afa = next((p["afa"] for p in P if p["year"] == Y), "0.00")
check(c1["afa_year"] == exp_afa and c1["year"] == Y, f"the depreciation of this year {c1['afa_year']} / {exp_afa}")
k = min((Y - 2024) * 12 + TODAY.month - 3 + 1, 84)
exp_book = Decimal("2400") - (m2(Decimal(2400) * k / 84) if k < 84 else Decimal(2400))
check(c1["book_value"] == f"{exp_book:.2f}" and c1["current_value_eff"] == c1["book_value"] and c1["new_value_eff"] == "2400.00",
      f"book value today, current value = book value, new value = price {c1['book_value']} {exp_book}")
enc = sql("SELECT purchase_net, serial_no, new_value, vendor FROM office_equipment WHERE id=?", (CAM,))[0]
check(str(enc[0]).startswith("kenc1:") and str(enc[1]).startswith("kenc1:") and enc[2] == "" and enc[3] == "Fotohaus Beispiel",
      f"price and serial number encrypted at rest {str(enc[0])[:10]} {str(enc[1])[:10]}")
# 2.92.0 review: the office log of the equipment row carries the price too -> encrypted like the column
logs = [str(x[0]) for x in sql("SELECT detail FROM office_doc_log WHERE detail LIKE ? OR detail LIKE ?", ("%purchase_net%", "%serial_no%"))]
check(not logs, f"no office log entry holds the equipment price in plain text {logs[:1]}")

r = A.post(B + E, json={"name": "Funkmikrofon", "category": "Ton", "purchase_date": "2025-06-01", "purchase_net": "650"})
MIC = r.json()["id"]
m_ = row(A, MIC)
check(m_["method"] == "gwg" and m_["afa_plan"] == [{"year": 2025, "afa": "650.00", "book": "0.00"}] and m_["book_value"] == "0.00",
      f"low-value asset: in full in the purchase year {m_.get('afa_plan')}")
r = A.post(B + E, json={"name": "Schnitt-Laptop", "category": "Computer", "purchase_date": "2025-10-01", "purchase_net": "1500,00"})
check(r.status_code == 201, "a price with a decimal comma " + r.text[:120])
LAP = r.json()["id"]
lp = row(A, LAP)
check(lp["life_suggest"] == 12 and lp["afa_plan"] == [{"year": 2025, "afa": "375.00", "book": "1125.00"}, {"year": 2026, "afa": "1125.00", "book": "0.00"}],
      f"a computer: one year (digital asset), by the month {lp.get('afa_plan')}")
r = A.patch(B + f"{E}/{LAP}", json={"life_months": 36})
lp = row(A, LAP)
check(r.ok and lp["life_months"] == 36 and lp["life_eff"] == 36 and lp["afa_plan"] == plan("1500", 2025, 10, 36), f"an own useful life {lp.get('life_eff')}")
check(A.patch(B + f"{E}/{LAP}", json={"life_months": 0}).ok and row(A, LAP)["life_eff"] == 12, "life 0 = the suggestion again")
check(A.patch(B + f"{E}/{LAP}", json={"life_months": 9999}).status_code == 400, "an absurd useful life is refused")
check(A.patch(B + f"{E}/{LAP}", json={"purchase_net": "-5"}).status_code == 400, "a negative price is refused")
check(A.patch(B + f"{E}/{LAP}", json={"purchase_date": "2025-13-01"}).status_code == 400, "an invalid date is refused")
r = A.patch(B + f"{E}/{CAM}", json={"current_value": "999", "new_value": "2600"})
c1 = row(A, CAM)
check(r.ok and c1["current_value_eff"] == "999.00" and c1["new_value_eff"] == "2600.00" and c1["book_value"] == f"{exp_book:.2f}",
      f"own current value and new value win, the book value stays {c1.get('current_value_eff')} {c1.get('new_value_eff')}")
check(str(sql("SELECT current_value FROM office_equipment WHERE id=?", (CAM,))[0][0]).startswith("kenc1:"), "current value encrypted at rest")
r = A.post(B + E, json={"name": "=SUM(1;2)", "category": "Sonstiges", "purchase_date": f"{Y}-01-10", "purchase_net": "100"})
INJ = r.json()["id"]
OLD = A.post(B + E, json={"name": "Altes Stativ", "category": "Kamera"}).json()["id"]
check(row(A, OLD)["method"] == "" and row(A, OLD)["afa_plan"] == [] and row(A, OLD)["current_value_eff"] is None, "a device without purchase data: no values")

# ---------------------------------------------------------------- members never see prices / values
bl = Bo.get(B + E).json()["items"]
b1 = next(x for x in bl if x["id"] == CAM)
hidden = ("purchase_net", "purchase_date", "serial_no", "vendor", "new_value", "current_value", "receipt_node_id", "life_months", "agreement_id",
          "afa_plan", "afa_year", "book_value", "current_value_eff", "new_value_eff")
check(b1["name"] == "Kamera Alpha" and not any(k in b1 for k in hidden), f"member: the device without any value {sorted(b1)}")
b2 = Bo.get(B + f"{E}/{CAM}").json()
check(not any(k in b2 for k in hidden), "member: the single row without any value")
for path in ("/value", "/value.csv", "/value.pdf", "/policies", "/receipts", "/receipts/1"):
    check(Bo.get(B + E + path).status_code == 403, f"member: {path} is 403")
check(Bo.patch(B + f"{E}/{CAM}", json={"purchase_net": "1"}).status_code == 403, "member: cannot change the price")
bx = Bo.get(B + O + "/export").json()
check(not any(k in x for x in bx["equipment"] for k in hidden), "member: the master data export has no values")
ax = A.get(B + O + "/export").json()
check(next(x for x in ax["equipment"] if x["id"] == CAM)["purchase_net"] == "2400.00", "admin: the export carries the purchase price")
# another organisation
check(all(x["id"] not in (CAM, MIC) for x in Ca.get(B + E).json()["items"]), "other organisation: sees none of the devices")
check(Ca.get(B + f"{E}/{CAM}").status_code == 404 and Ca.patch(B + f"{E}/{CAM}", json={"current_value": "1"}).status_code == 404, "other organisation: 404")
check(Ca.get(B + E + "/value").json()["rows"] == [], "other organisation: an empty insurance list")

# ---------------------------------------------------------------- policies (#1925)
r = A.post(B + O + "/agreements", json={"kind": "insurance", "name": "Elektronikversicherung", "provider": "Beispiel Versicherung AG", "cost": "240", "per": "year"})
if r.status_code == 404:
    print("SKIP: policies -- part A (POST /api/office/agreements) is not in this build", flush=True)
    POL = None
else:
    check(r.status_code in (200, 201), "a policy (part A) " + r.text[:160])
    POL = r.json()["id"]
    check(any(p["id"] == POL for p in A.get(B + E + "/policies").json()["items"]), "the policy is offered under insured by")
    r = A.patch(B + f"{E}/{CAM}", json={"agreement_id": POL})
    check(r.ok and row(A, CAM)["agreement_id"] == POL and row(A, CAM)["agreement_name"] == "Elektronikversicherung", "a device insured by the policy " + r.text[:120])
    v = A.get(B + E + f"/value?agreement_id={POL}").json()
    check([x["id"] for x in v["rows"]] == [CAM] and v["sums"]["new_value"] == "2600.00", f"the list filtered by policy {v['sums']}")
    v0 = A.get(B + E + "/value?agreement_id=0").json()
    check(CAM not in [x["id"] for x in v0["rows"]] and MIC in [x["id"] for x in v0["rows"]], "filter 0 = devices without a policy")
    P2 = Ca.post(B + O + "/agreements", json={"kind": "insurance", "name": "Fremdpolice"}).json()["id"]
    check(A.patch(B + f"{E}/{MIC}", json={"agreement_id": P2}).status_code == 400, "a policy of another organisation is refused")
    check(A.patch(B + f"{E}/{MIC}", json={"agreement_id": 99999999}).status_code == 400, "an unknown policy is refused")
    check(Bo.get(B + E + f"/value?agreement_id={POL}").status_code == 403, "member: no filtered list")

# ---------------------------------------------------------------- the insurance list: sums, CSV, PDF
v = A.get(B + E + "/value").json()
ids = [x["id"] for x in v["rows"]]
check(set(ids) == {CAM, MIC, LAP, INJ, OLD} and v["sums"]["count"] == 5, f"the live devices {ids}")
exp_new = Decimal("2600") + Decimal("650") + Decimal("1500") + Decimal("100")
exp_cur = sum(Decimal(x["current_value"] or 0) for x in v["rows"])
check(v["sums"]["new_value"] == f"{exp_new:.2f}" and v["sums"]["current_value"] == f"{exp_cur:.2f}" and Decimal(v["sums"]["current_value"]) >= Decimal("999"),
      f"the sums {v['sums']}")
check(v["disclaimer"] == "No tax advice; figures without guarantee.", "the note: no tax advice")
A.patch(B + f"{E}/{OLD}", json={"archived": 1})
check(OLD not in [x["id"] for x in A.get(B + E + "/value").json()["rows"]], "an archived device leaves the insurance list")
r = A.get(B + E + "/value.csv")
check(r.ok and r.headers["Content-Type"].startswith("text/csv") and "attachment" in r.headers.get("Content-Disposition", ""), "CSV download")
rows_ = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
check(rows_[0][:3] == ["Device", "Category", "Serial number"], f"CSV header {rows_[0]}")
cam_row = next((x for x in rows_ if x and x[0] == "Kamera Alpha"), None)
check(cam_row is not None and cam_row[2] == "SN-0815" and cam_row[5] == "2600,00" and cam_row[6] == "999,00", f"CSV row with decimal comma {cam_row}")
check(any(x and x[0] == "'=SUM(1;2)" for x in rows_), "CSV: a formula is defused")
check(rows_[-2][0] == "Total" and rows_[-2][5] == f"{exp_new:.2f}".replace(".", ","), f"CSV total {rows_[-2]}")
r = A.get(B + E + "/value.pdf")
check(r.ok and r.content[:5] == b"%PDF-" and r.headers["Content-Type"] == "application/pdf", "PDF download")
check(A.get(B + E + "/value?agreement_id=x").status_code == 400, "an invalid filter is 400")

# ---------------------------------------------------------------- take from receipt
RC = upload(A, "rechnung-objektiv.pdf", "Rechnung Objektiv 50mm Gesamt 1190,00 EUR inkl. 19 % MwSt", f"org:{ORG}", "1190.00", "2025-02-03")
lst = A.get(B + E + "/receipts").json()["items"]
check(any(x["id"] == RC and x["amount"] == "1190.00" for x in lst), f"the document of the office is offered {[x['id'] for x in lst]}")
sg = A.get(B + f"{E}/receipts/{RC}").json()
check(sg.get("gross") == "1190.00" and sg.get("date") == "2025-02-03" and sg.get("currency") == "EUR", f"the proposal: gross and date {sg}")
check((sg.get("vat_pct") == 19 and sg.get("net") == "1000.00") or (sg.get("vat_pct") is None and sg.get("net") is None and sg.get("hint")),
      f"net from 19 % VAT, or empty with a hint {sg}")
r = A.post(B + E, json={"name": "Objektiv 50mm", "category": "Objektiv", "receipt_node_id": RC, "purchase_date": sg["date"], "purchase_net": "1000"})
check(r.status_code == 201 and row(A, r.json()["id"])["receipt_node_id"] == RC, "a device with its receipt " + r.text[:120])
OBJ = r.json()["id"]
OWN = upload(A, "privat.pdf", "Privatbeleg 10,00", "private", "10.00", "2025-01-01")
check(A.get(B + f"{E}/receipts/{OWN}").status_code == 404, "a private document is no receipt of the organisation (404)")
check(OWN not in [x["id"] for x in A.get(B + E + "/receipts").json()["items"]], "and is not offered")
check(A.patch(B + f"{E}/{OBJ}", json={"receipt_node_id": OWN}).status_code == 400, "a private document cannot be linked")
CRC = upload(Ca, "fremd.pdf", "Fremdbeleg 99,00", f"org:{ORG2}", "99.00", "2025-01-01")
check(A.get(B + f"{E}/receipts/{CRC}").status_code == 404 and Ca.get(B + f"{E}/receipts/{RC}").status_code == 404, "a receipt of another organisation is 404")
check(A.patch(B + f"{E}/{OBJ}", json={"receipt_node_id": CRC}).status_code == 400, "a receipt of another organisation cannot be linked")
check(A.get(B + f"{E}/receipts/99999999").status_code == 404, "an unknown document is 404")

# ---------------------------------------------------------------- import keeps values, drops foreign ids
ax = A.get(B + O + "/export").json()
r = Ca.post(B + O + "/import", json={"equipment": [x for x in ax["equipment"] if x["id"] in (CAM, OBJ)]})
check(r.ok, "the export of one organisation imports into another " + r.text[:200])
ci = {x["name"]: x for x in Ca.get(B + E).json()["items"]}
check(ci.get("Kamera Alpha", {}).get("purchase_net") == "2400.00" and ci["Kamera Alpha"].get("agreement_id") is None
      and ci.get("Objektiv 50mm", {}).get("receipt_node_id") is None, f"values travel, receipt / policy ids of the other office do not {ci.get('Objektiv 50mm')}")

# ---------------------------------------------------------------- undo: a device's values back
r = A.patch(B + f"{E}/{CAM}", json={"current_value": None, "new_value": None})
c1 = row(A, CAM)
check(r.ok and c1["current_value_eff"] == c1["book_value"] and c1["new_value_eff"] == "2400.00", "empty values = the computed ones again (the undo of an own value)")
if POL:
    A.post(B + O + f"/agreements/{POL}/archive")  # part A may archive by PATCH instead
    A.patch(B + O + f"/agreements/{POL}", json={"archived": 1})
    r = A.patch(B + f"{E}/{CAM}", json={"agreement_id": POL, "serial_no": "SN-0816"})
    check(r.ok and row(A, CAM)["serial_no"] == "SN-0816", "an archived policy that is set already does not block saving " + r.text[:120])

# ---------------------------------------------------------------- the personal office (person without organisation)
r = Do.post(B + E, json={"name": "Drohne Solo", "category": "Drohne", "purchase_date": "2025-01-20", "purchase_net": "1680", "serial_no": "DR-1"})
check(r.status_code == 201, "personal office: a device with values " + r.text[:160])
DR = r.json()["id"]
d1 = row(Do, DR)
check(d1["life_suggest"] == 84 and d1["afa_plan"] == plan("1680", 2025, 1, 84) and d1["afa_plan"][0]["afa"] == "240.00", f"personal office: a drone, 84 months {d1.get('afa_plan', [])[:2]}")
check(str(sql("SELECT purchase_net FROM office_equipment WHERE id=?", (DR,))[0][0]).startswith("kenc1:"), "personal office: the price encrypted at rest")
dv = Do.get(B + E + "/value").json()
check([x["id"] for x in dv["rows"]] == [DR] and dv["sums"]["new_value"] == "1680.00", f"personal office: its insurance list {dv['sums']}")
check(Do.get(B + E + "/value.csv").ok and Do.get(B + E + "/value.pdf").content[:5] == b"%PDF-", "personal office: CSV and PDF")
DRC = upload(Do, "drohne.pdf", "Drohne 1999,20 EUR inkl. 19% USt", "private", "1999.20", "2025-01-20")
check(DRC in [x["id"] for x in Do.get(B + E + "/receipts").json()["items"]], "personal office: its own documents are its receipts")
check(Do.patch(B + f"{E}/{DR}", json={"receipt_node_id": DRC}).ok, "personal office: link the receipt")
check(Do.get(B + f"{E}/receipts/{RC}").status_code == 404 and Do.patch(B + f"{E}/{DR}", json={"receipt_node_id": RC}).status_code == 400,
      "personal office: a document of an organisation is 404 / refused")
check(A.get(B + f"{E}/receipts/{DRC}").status_code == 404, "an organisation never reaches a private receipt")
check(Er.get(B + f"{E}/{DR}").status_code == 404 and Er.get(B + E + "/value").json()["rows"] == [] and Er.get(B + f"{E}/receipts/{DRC}").status_code == 404,
      "a second person sees nothing of it")
check(Er.patch(B + f"{E}/{DR}", json={"current_value": "1"}).status_code == 404, "a second person cannot change it")
check(DR not in [x["id"] for x in A.get(B + E).json()["items"]], "the organisation does not see the personal device")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
