#!/usr/bin/env python3
# kalmido-suite: now=2027-02-15T10:00:00+01:00
"""2.603.0 API tests, part B (#4921): the EUeR next to the year before (office/euercmp.py). Invented companies, accounts and
figures only: every DATEV file is written here. tenant-matrix: office  freelancer-matrix: office
 - a year before with figures in Kalmido: every line now / before / deviation / percent, the totals and the profit equal the
   two EUeR results; the VAT liability = field 83 of the two whole-year VAT returns
 - the same year also in the DATEV archive: Kalmido wins, the archive is never added
 - a year before only in the archive: income / expenses net from the profit and loss accounts (tax keys, automatic accounts),
   the VAT liability from VAT minus input tax (prepayments, opening balances and person accounts left out), marked
   "Source: DATEV archive"; the EUeR of the year itself stays as it was (display only)
 - nothing anywhere: source none, no deviation; a member 403; a person without organisation the same as an office
usage: p2603_b_euercmp_test.py <datadir>      (P2603B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

O = "/api/office"
D = O + "/docs"
CMP = "/api/office/books/euer/compare"  # the literal path: tests/tenant_coverage_test.py finds the route here
BA = O + "/books/archive"
FEAT = "cal,comments,collab,office,clients,docs"


def dbw(sql, args=()):
    c = kt._dbx.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def tiny_pdf(text):
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


def receipt(s, ws, name, amount, day, vat, cat):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": cat, "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def invoice(s, client, net, day, paid):
    r = s.post(B + D, json={"kind": "invoice", "client_id": client, "service_from": day, "service_to": day,
                            "items": [{"title": "Schnitt", "qty": 1, "rate": net}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    dbw("UPDATE office_docs SET date=? WHERE id=?", (day, did))
    gross = s.get(B + f"{D}/{did}").json()["totals"]["gross"]
    r = s.post(B + f"{D}/{did}/payments", json={"amount": str(gross), "date": paid})
    assert r.ok, r.text
    return did


# ---------------------------------------------------------------- DATEV files (as tests/p2414_api_test.py, + the tax key)
def head(cat, name, ver, fy, frm="", to=""):
    f = ['"EXTF"', "700", str(cat), f'"{name}"', str(ver), "20260101120000000", "", '"RE"', '""', '""', "1234567", "12345", fy, "4", frm, to]
    return ";".join(f + [""] * (31 - len(f)))


def q(v):
    return '"' + str(v).replace('"', '""') + '"' if v != "" else ""


COLS21 = ("Umsatz (ohne Soll/Haben-Kz)", "Soll/Haben-Kennzeichen", "WKZ Umsatz", "Konto", "Gegenkonto (ohne BU-Schlüssel)",
          "BU-Schlüssel", "Belegdatum", "Belegfeld 1", "Buchungstext")


def extf21(year, rows):
    """rows = (amount, S/H, account, counter, tax key, DDMM, text)."""
    lines = [head(21, "Buchungsstapel", 13, f"{year}0101", f"{year}0101", f"{year}1231"), ";".join(q(c) for c in COLS21)]
    for a, sh, k, g, bu, d, t in rows:
        lines.append(";".join([a, q(sh), q("EUR"), k, g, q(bu), d, q("B-" + d), q(t)]))
    return b"\xef\xbb\xbf" + ("\r\n".join(lines) + "\r\n").encode("utf-8")


def extf20(year, labels):
    lines = [head(20, "Kontenbeschriftungen", 3, f"{year}0101"), '"Konto";"Kontenbeschriftung";"Sprach-ID"']
    lines += [f'{a};{q(t)};"de-DE"' for a, t in labels]
    return ("\r\n".join(lines) + "\r\n").encode("cp1252")


LABELS = [("1200", "Bank"), ("8400", "Erlöse 19 % USt"), ("4930", "Bürobedarf"), ("1576", "Abziehbare Vorsteuer 19 %"),
          ("1780", "Umsatzsteuer-Vorauszahlungen"), ("1776", "Umsatzsteuer 19 %")]
# the year before only in the archive: income 11,900 + 238 gross on the automatic account 8400 (19 %) = 10,200 net, 1,938 VAT;
# office supplies 1,190 with tax key 9 (19 % input tax) = 1,000 net, 190 input tax; 50 input tax booked by hand on 1576;
# left out: 500 prepaid on 1780 (its label), the opening balance on 9000, the debtor 10001 itself (a person account)
ROWS_OLD = [("11900,00", "S", "1200", "8400", "", "1503", "Honorar Archiv"),
            ("1190,00", "S", "4930", "1200", "9", "0204", "Buerobedarf Archiv"),
            ("500,00", "S", "1780", "1200", "", "1005", "USt-Vorauszahlung"),
            ("50,00", "S", "1576", "1200", "", "1106", "Vorsteuer nachgebucht"),
            ("3000,00", "S", "1200", "9000", "", "0101", "EB-Wert Bank"),
            ("238,00", "S", "10001", "8400", "", "2007", "Honorar Debitor")]


def archive(s, year, rows, labels=LABELS):
    files = [(f"EXTF_Buchungsstapel_{year}.csv", extf21(year, rows)), (f"EXTF_Kontenbeschriftungen_{year}.csv", extf20(year, labels))]
    r = s.post(B + BA + "/import", files=[("file", (n, d, "application/octet-stream")) for n, d in files])
    assert r.status_code == 201, r.text
    return r.json()


def row(d, key):
    return next((x for x in d["rows"] if x["key"] == key), None)


def money_eq(a, b):
    return a is not None and b is not None and abs(float(a) - float(b)) < 0.005


kt.fresh(prefix="P2603B")
kt.docker_logs_on_first_fail()
A = kt.setup()
assert A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"}).ok
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
COMPANY = {"name": "Studio Beispiel", "street": "Teststrasse 1", "zip": "20000", "city": "Hamburg", "country": "DE",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank", "tax_number": "12/345/67890"}
DX = {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}


def office(s, ws):
    """Kalmido figures of 2025 and 2026, the archive of 2024 and (never counted) of 2025."""
    r = s.put(B + O + "/settings", json={"small_business": 0, "vat_basis": "ist", "currency": "EUR", "company_fields": COMPANY, "datev_extf": DX})
    assert r.ok, r.text
    c1 = s.post(B + "/api/clients", json={"name": "Beispielkunde", "street": "Marktstrasse 5", "zip": "50000", "city": "Koeln", "country": "DE"}).json()["id"]
    invoice(s, c1, 1000, "2025-03-10", "2025-03-20")
    invoice(s, c1, 2000, "2026-03-10", "2026-03-20")
    receipt(s, ws, "fremd2025.pdf", "1190.00", "2025-05-05", "19", "Fremdleistungen")
    receipt(s, ws, "fremd2026.pdf", "1190.00", "2026-05-05", "19", "Fremdleistungen")
    receipt(s, ws, "porto2025.pdf", "119.00", "2025-06-05", "19", "Porto")  # only the year before has postage
    archive(s, 2024, ROWS_OLD)
    archive(s, 2025, [("99999,00", "S", "1200", "8400", "", "0107", "Nie addiert")])


def scenario(s, who):
    # ---------------------------------------------------------------- the year before from Kalmido
    r = s.get(B + CMP + "?year=2026")
    check(r.ok, f"{who}: the comparison answers " + r.text[:300])
    d = r.json()
    e26, e25 = s.get(B + O + "/books/euer?year=2026").json(), s.get(B + O + "/books/euer?year=2025").json()
    check(d["year"] == 2026 and d["prev_year"] == 2025 and d["source"] == "kalmido" and d["archive"] is None, f"{who}: 2025 from Kalmido {d['source']}")
    i = row(d, "i:vat19")
    check(i and i["now"] == "2000.00" and i["prev"] == "1000.00" and i["diff"] == "1000.00" and i["pct"] == 100, f"{who}: an income line now / before / deviation {i}")
    f = next((x for x in d["rows"] if x["group"] == "expense" and x["label"] == "Fremdleistungen"), None)
    check(f and f["now"] == "1000.00" and f["prev"] == "1000.00" and f["diff"] == "0.00" and f["pct"] == 0, f"{who}: an expense line unchanged {f}")
    p = next((x for x in d["rows"] if x["group"] == "expense" and x["label"] == "Porto"), None)
    check(p and p["now"] == "0.00" and p["prev"] == "100.00" and p["pct"] == -100, f"{who}: a line only the year before had {p}")
    tot = {k: row(d, k) for k in ("income_total", "expense_total", "profit")}
    check(money_eq(tot["income_total"]["now"], e26["income_total"]["net"]) and money_eq(tot["income_total"]["prev"], e25["income_total"]["net"])
          and money_eq(tot["expense_total"]["prev"], e25["expense_total"]["net"]) and money_eq(tot["profit"]["now"], e26["profit"])
          and money_eq(tot["profit"]["prev"], e25["profit"]), f"{who}: the totals = the two EUeR results {tot}")
    check(float(tot["income_total"]["prev"]) < 99999, f"{who}: the archive of 2025 is never added to Kalmido's 2025 {tot['income_total']}")
    u26 = s.get(B + O + "/books/ustva?year=2026&period=y").json()["kz"]["83"]
    u25 = s.get(B + O + "/books/ustva?year=2025&period=y").json()["kz"]["83"]
    v = d["vat"]
    check(v and money_eq(v["now"], u26) and money_eq(v["prev"], u25) and v["label"] == "VAT liability", f"{who}: the VAT liability = field 83 of the years {v} {u26} {u25}")
    check(v and v["now"] == "190.00" and v["prev"] == "-19.00" and v["diff"] == "209.00", f"{who}: VAT liability 380 - 190 / 190 - 190 - 19 {v}")
    check(any("display only" in n for n in d["notes"]) and "No tax advice; figures without guarantee." in d["notes"], f"{who}: the notes {d['notes']}")

    # ---------------------------------------------------------------- the year before from the DATEV archive
    before = s.get(B + O + "/books/euer?year=2024").json()
    r = s.get(B + CMP + "?year=2025")
    check(r.ok, f"{who}: comparison 2025 " + r.text[:300])
    d = r.json()
    check(d["source"] == "archive" and d["archive"] and d["archive"]["label"] == "Source: DATEV archive" and d["archive"]["chart"] == "SKR03",
          f"{who}: 2024 from the archive, marked {d['source']} {d.get('archive', {}) and d['archive'].get('label')}")
    check([x["key"] for x in d["rows"]] == ["income_total", "expense_total", "profit"], f"{who}: the archive compares the totals only {[x['key'] for x in d['rows']]}")
    it, ex, pr = row(d, "income_total"), row(d, "expense_total"), row(d, "profit")
    check(it["prev"] == "10200.00", f"{who}: archive income net (automatic account 19 %, the debtor's side left out) {it}")
    check(ex["prev"] == "1000.00", f"{who}: archive expenses net (tax key 9) {ex}")
    check(pr["prev"] == "9200.00" and money_eq(pr["now"], s.get(B + O + "/books/euer?year=2025").json()["profit"]), f"{who}: archive profit {pr}")
    check(d["vat"] and d["vat"]["prev"] == "1698.00", f"{who}: archive VAT liability 1,938 - 190 - 50 (prepayment and opening balance left out) {d['vat']}")
    acc = {a["account"]: a for a in d["archive"]["accounts"]}
    check(set(acc) == {"8400", "4930", "1576"} and acc["8400"]["label"] == "Erlöse 19 % USt" and acc["8400"]["kind"] == "income",
          f"{who}: the archive accounts behind the sums (no bank, prepayment, debtor) {sorted(acc)}")
    check(any("DATEV booking archive" in n for n in d["notes"]), f"{who}: the archive note {d['notes']}")
    after = s.get(B + O + "/books/euer?year=2024").json()
    check({k: v for k, v in after.items() if "at" not in k} == {k: v for k, v in before.items() if "at" not in k}
          and not after["income"] and not after["expenses"], f"{who}: the EUeR of 2024 itself stays empty (display only)")

    # ---------------------------------------------------------------- nothing at all
    d = s.get(B + CMP + "?year=2024").json()
    check(d["source"] == "none" and d["archive"] is None and all(x["prev"] is None and x["diff"] is None and x["pct"] is None for x in d["rows"]),
          f"{who}: no figures for 2023: no deviation {d['rows']}")


office(A, f"org:{ORG}")
check(Bo.get(B + CMP + "?year=2026").status_code == 403, "a member cannot read the comparison (403)")
check(A.get(B + CMP + "?year=abc").status_code == 400, "a broken year: 400")
scenario(A, "office")

# ---------------------------------------------------------------- a person without organisation (freelancer parity)
FID, Fr = freelancer(B, A, "erin")  # freelancer-matrix: office
office(Fr, Fr.get(B + O + "/books").json()["upload_ws"])
scenario(Fr, "freelancer")

sys.exit(kt.done("p2603_b_euercmp"))
