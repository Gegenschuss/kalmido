#!/usr/bin/env python3
"""2.299.0 part A (#3190): MT940 / MT942 bank statements are read, own container (start.sh, org encryption on).
Invented accounts, names and figures only: every statement is made here (bytes, Latin-1 where the bank dialect is).
freelancer-matrix: office, personal
tenant-matrix: office
 - a person without organisation (personal office, its own admin; the import route is the same for an organisation):
   Sparkasse style (?20-?33 sub-fields, Latin-1 umlauts, bank reference, balances), Volksbank style (envelope {1:}{4:}, SEPA
   tags EREF+ / SVWZ+ across sub-fields), Deutsche Bank style (another separator, supplementary line, split lines), Commerzbank
   style (unstructured SEPA tags, CRLF, @@), MT942 pending, bulk booking, booking date across the year change, reversals
   (RC / RD), two statements in one file, one booking in a day and a month statement counts once, ZIP with two .sta files,
   a broken file named per file, import + undo + restore with fmt mt940, the balance taken from :60F: / :62F:
 - the household budget reads the same file (rows of the same shape)
usage: p2299_a_mt940_test.py <datadir>"""
import base64
import io
import os
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # noqa: E402
FEAT = "cal,comments,collab,office,clients,home,budget,contracts"
K = "/api/office/bank"
IBAN1, IBAN2, IBAN3 = "DE02120300000000202051", "DE89370400440532013000", "DE75512108001245126199"

if not (os.environ.get("P2299A_NOSTART") or os.environ.get("KMT_NOSTART")):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
FID, Fr = freelancer(B, A, features=FEAT)  # freelancer-matrix: office, personal
Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Beispiel Studio", "street": "Weg 1", "zip": "12345", "city": "Musterstadt",
                                                              "country": "DE"}})


def up(s, url, files, **form):
    fl = [("files", (n, d if isinstance(d, bytes) else d.encode(), "application/octet-stream")) for n, d in files]
    return s.post(B + url, files=fl, data=form)


def zipped(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files:
            z.writestr(name, data)
    return b.getvalue()


def prev(files, s=Fr):
    r = up(s, K + "/import/preview", files)
    return r, (r.json() if r.ok else {})


# ---------------------------------------------------------------- statements made here
SPK = (":20:STARTUMS\n:25:50050201/0123456789\n:28C:00014/001\n:60F:C261001EUR1000,00\n"
       ":61:2610021002C12,50NMSCNONREF\n"
       ":86:166?00Gutschrift?10931?20EREF+E2E-A1?21SVWZ+Rechnung 4711 Gr\n?22öße M?23ärz?30COBADEFFXXX?31" + IBAN2 + "?32Müller & Söhne\n?33GmbH?34166\n"
       ":61:2610031003D45,00NDDTKREF1234//BANKREF99\n"
       ":86:105?00Lastschrift?10931?20SVWZ+Strom Oktober?32Stadtwerke Beispiel?31" + IBAN3 + "\n"
       ":62F:C261003EUR967,50\n")
SPK_B = SPK.encode("latin-1")

r, p = prev([("konto.sta", SPK_B)])
check(r.ok and p.get("fmt") == "mt940" and p.get("count") == 2, "Sparkasse: read as mt940, 2 new " + r.text[:300])
rows = p.get("rows") or []
a, d = (rows + [{}, {}])[:2]
check(a.get("amount") == "12.50" and a.get("day") == "2026-10-02" and a.get("counterpart") == "Müller & Söhne GmbH" and a.get("iban") == IBAN2,
      f"Sparkasse: amount, day, umlaut name, IBAN {a}")
check(a.get("purpose") == "Rechnung 4711 Größe März" and a.get("ref") == "E2E-A1", f"Sparkasse: SVWZ is the purpose across lines, EREF the reference {a}")
check(d.get("amount") == "-45.00" and d.get("ref") == "BANKREF99" and d.get("purpose") == "Strom Oktober" and d.get("iban") == IBAN3, f"Sparkasse: debit, bank reference {d}")
bal = {x["kind"]: x for x in p.get("balances") or []}
check(bal.get("open", {}).get("amount") == "1000.00" and bal.get("close", {}).get("amount") == "967.50" and bal["close"]["day"] == "2026-10-03"
      and bal["open"]["account"] == "50050201/0123456789", f"Sparkasse: opening / closing balance of :60F: / :62F: {p.get('balances')}")

# the same file as UTF-8 (a bank that sends UTF-8) reads the same
r, p2 = prev([("konto.mt940", SPK)])
check(r.ok and p2["rows"][0]["counterpart"] == a.get("counterpart"), "UTF-8 file: the same name")

VB = ("{1:F01GENODEF1XXX0000000000}{2:I940GENODEF1XXXN}{4:\n:20:VB1\n:25:" + IBAN1 + "\n:28C:1/1\n:60F:C260930EUR500,00\n"
      ":61:2610011001D19,99N062NONREF\n"
      ":86:152?00Lastschrift?10?20EREF+MND-1?21SVWZ+Monatsbeitrag Okt?22ober?32Verein Beispiel e.V.?31" + IBAN3 + "\n"
      ":61:2610021002RC5,00N062NONREF\n:86:152?00Storno?20SVWZ+Rueckbuchung?32Kiosk Example\n"
      ":61:2610031003RD8,00N062NONREF\n:86:152?00Storno?20SVWZ+Rueckgabe?32Kiosk Example\n"
      ":62F:C261003EUR483,01\n-}")
r, p = prev([("vb.sta", VB)])
rows = p.get("rows") or []
check(r.ok and p.get("count") == 3, "Volksbank: envelope read, 3 bookings " + r.text[:200])
check(rows and rows[0]["purpose"] == "Monatsbeitrag Oktober" and rows[0]["ref"] == "MND-1" and rows[0]["amount"] == "-19.99" and rows[0]["iban"] == IBAN3,
      f"Volksbank: SVWZ+ over two sub-fields, EREF+ {rows[:1]}")
check([x["amount"] for x in rows[1:]] == ["-5.00", "8.00"], f"reversals: RC is money out, RD money in {[x['amount'] for x in rows]}")
check({x["kind"]: x["amount"] for x in p.get("balances") or []} == {"open": "500.00", "close": "483.01"}, "Volksbank: balances")

DB = (":20:DB-1\n:25:" + IBAN1 + "/EUR\n:28C:0/1\n:60F:C261004EUR2000,00\n"
      ":61:261005D1200,00NDAUNONREF//DB12345\nHausverwaltung\n"
      ":86:805~00Dauerauftrag~10123~20Miete Oktober\n~21Wohnung 5~30~31~32Hausverwaltung\n~33Beispiel GmbH\n"
      ":62F:C261005EUR800,00\n")
r, p = prev([("db.sta", DB)])
x = (p.get("rows") or [{}])[0]
check(r.ok and x.get("amount") == "-1200.00" and x.get("counterpart") == "Hausverwaltung Beispiel GmbH" and x.get("purpose") == "Miete OktoberWohnung 5"
      and x.get("ref") == "DB12345", f"Deutsche Bank: other separator, split lines, bank reference {x}")
check(any(b["account"] == IBAN1 for b in p.get("balances") or []), "Deutsche Bank: the account of :25: with /EUR is the IBAN")

CB = (":20:CB1\r\n:25:" + IBAN1 + "\r\n:28C:2/1\r\n:60F:C261006EUR10,00\r\n:61:2610061006C99,00NTRFNONREF\r\n"
      ":86:EREF+NOTPROVIDED SVWZ+Rechnung 99 ABWA+Fritz Beispiel IBAN+" + IBAN2 + "\r\n:62F:C261006EUR109,00\r\n")
r, p = prev([("cb.txt", CB)])
x = (p.get("rows") or [{}])[0]
check(r.ok and x.get("purpose") == "Rechnung 99" and x.get("counterpart") == "Fritz Beispiel" and x.get("iban") == IBAN2 and x.get("ref") is None,
      f"Commerzbank: unstructured SEPA tags, CRLF, NOTPROVIDED is no reference {x}")
r, p = prev([("cb.txt", CB.replace("\r\n", "@@"))])
check(r.ok and p.get("count") == 1, "@@ as the line separator " + r.text[:200])

M942 = (":20:INTRA\n:25:" + IBAN1 + "\n:28C:5/1\n:34F:EUR0,\n:13D:2610061200+0200\n:61:2610061006D7,00NMSCNONREF\n"
        ":86:166?00Kartenzahlung?20SVWZ+Kiosk\n:90D:1EUR7,00\n:90C:0EUR0,\n-")
r, p = prev([("intra.sta", M942)])
check(r.ok and p.get("pending_count") == 1 and p.get("count") == 0 and p["rows"][0]["pending"], "MT942: pending, shown, not counted " + r.text[:200])
check(up(Fr, K + "/import", [("intra.sta", M942)]).status_code == 400, "MT942: nothing to import")

SAM = (":20:S\n:25:" + IBAN1 + "\n:60F:C261007EUR100,00\n:61:2610071007D345,67NMSCNONREF\n"
       ":86:808?00Sammelueberweisung?20SAMMEL-UEBERW 3 Posten?21Gehalt Okt, Miete, Strom\n:62F:C261007EUR-245,67\n")
r, p = prev([("sam.sta", SAM)])
check(r.ok and p.get("count") == 1 and "Gehalt Okt" in p["rows"][0]["purpose"] and "SAMMEL" in p["rows"][0]["purpose"], "bulk booking: one booking, purpose visible " + r.text[:200])
SAM2 = SAM.replace("C261007EUR-245,67", "D261007EUR245,67")
bal = {x["kind"]: x["amount"] for x in prev([("sam.sta", SAM2)])[1].get("balances") or []}
check(bal.get("close") == "-245.67", f"a debit balance (D) is negative {bal}")

YR = (":20:Y\n:25:" + IBAN1 + "\n:60F:C261230EUR0,00\n:61:2701021230D10,00NMSCNONREF\n:86:166?00A?20SVWZ+Vor dem Jahreswechsel\n"
      ":61:2612300102C20,00NMSCNONREF\n:86:166?00B?20SVWZ+Nach dem Jahreswechsel\n:62F:C270102EUR10,00\n")
r, p = prev([("yr.sta", YR)])
check([x["day"] for x in p.get("rows") or []] == ["2026-12-30", "2027-01-02"], f"booking date MMDD across the year change {[x['day'] for x in p.get('rows') or []]}")

TWO = (SPK + "-\n" + VB)
r, p = prev([("zwei.sta", TWO)])
check(r.ok and p.get("count") == 5 and len(p.get("balances") or []) == 4, f"two statements in one file: 5 bookings, 4 balances {len(p.get('rows') or [])} {len(p.get('balances') or [])}")

# a booking in a day and a month statement counts once
DAYST = ":20:T\n:25:" + IBAN1 + "\n:60F:C261010EUR0,00\n:61:2610101010D30,00NMSCNONREF//REF-77\n:86:166?00Kartenzahlung?20SVWZ+Tankstelle?32Fuel Example\n:62F:C261010EUR-30,00\n"
MONTH = (":20:M\n:25:" + IBAN1 + "\n:60F:C261001EUR0,00\n:61:2610101010D30,00NMSCNONREF//REF-77\n:86:166?00Kartenzahlung?20SVWZ+Tankstelle?32Fuel Example\n"
         ":61:2610111011D4,00NMSCNONREF//REF-78\n:86:166?00Kartenzahlung?20SVWZ+Kiosk?32Kiosk Example\n:62F:C261031EUR-34,00\n")
r, p = prev([("tag.sta", DAYST), ("monat.sta", MONTH)])
check(r.ok and p.get("count") == 2 and p.get("dup_count") == 1, f"day + month statement: the shared booking counts once {p.get('count')} {p.get('dup_count')}")

# a ZIP with two .sta files, one broken file named per file
BROKEN = ":20:KAPUTT\n:25:" + IBAN1 + "\n:28C:1/1\n"
r, p = prev([("auszuege.zip", zipped([("a.sta", SPK_B), ("b.sta", DB), ("liesmich.pdf", "x")]))])
check(r.ok and p.get("count") == 3 and len(p.get("skipped_files") or []) == 1, f"ZIP with two .sta: 3 bookings, the pdf skipped {p.get('count')} {p.get('skipped_files')}")
r, p = prev([("gut.sta", SPK_B), ("kaputt.sta", BROKEN)])
check(r.ok and p.get("count") == 2 and [e["file"] for e in p.get("file_errors") or []] == ["kaputt.sta"], f"a broken file is named, the good one is read {p.get('file_errors')}")
r, p = prev([("kaputt.sta", BROKEN)])
check(r.status_code == 400, "a single broken file: 400 " + r.text[:200])
BADROW = ":20:X\n:25:" + IBAN1 + "\n:60F:C261001EUR0,00\n:61:XXXX\n:62F:C261001EUR0,00\n"
r, p = prev([("x.sta", BADROW)])
check(r.ok and p.get("skipped") == 1 and p.get("count") == 0, "an unreadable :61: line = a skipped row " + r.text[:200])

# import, balances, undo, restore, fmt
r = up(Fr, K + "/import", [("konto.sta", SPK_B)])
check(r.status_code == 201 and r.json().get("count") == 2 and r.json()["import"]["fmt"] == "mt940", "import: 2 bookings, fmt mt940 " + r.text[:200])
IMP = r.json()["import"]["id"] if r.status_code == 201 else 0
r, p = prev([("konto.sta", SPK_B)])
check(p.get("count") == 0 and p.get("dup_count") == 2, "the same file again: all there")
check(Fr.get(B + "/api/office/cashflow").ok, "cash flow still loads with the MT940 balances")
check(Fr.post(B + K + f"/imports/{IMP}/undo").ok, "import taken back")
r, p = prev([("konto.sta", SPK_B)])
check(p.get("count") == 2, "after the undo the file is new again")
check(Fr.post(B + K + f"/imports/{IMP}/restore").ok, "import restored")
check(Fr.post(B + K + "/import/preview", json={"text": SPK, "filename": "konto.txt"}).json().get("fmt") == "mt940", "JSON way too")

# the household budget reads the same file
L = Fr.post(B + "/api/budget/lists", json={}).json()["list_id"]
r = up(Fr, f"/api/budget/{L}/import/parse", [("konto.sta", SPK_B)])
j = r.json() if r.ok else {}
check(r.ok and j.get("fmt") == "mt940" and [x["kind"] for x in j.get("rows") or []] == ["in", "out"], "budget: the same file, rows in / out " + r.text[:200])
take = [{k: x[k] for k in ("day", "amount", "kind", "title", "counterpart", "iban", "ref", "e2e", "fi")} for x in j.get("rows") or []]
r = Fr.post(B + f"/api/budget/{L}/import/commit", json={"rows": take, "label": "konto.sta", "fmt": "mt940"})
check(r.status_code == 201 and r.json().get("created") == 2, "budget: taken over " + r.text[:200])

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
