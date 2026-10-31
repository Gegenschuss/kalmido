#!/usr/bin/env python3
# kalmido-suite:
"""2.368.2 (#2984, #2986) API tests: office CSV files and document dates follow the language, own container (start.sh).
Invented companies and people only. freelancer-matrix: office
 - #2984 the office CSV exports (income statement, cash book, equipment, meals, travel, per diem) write "," and the point in
   English, ";" and the decimal comma in German; the logged times of the cash book are local ("2026-10-09 14:05:33"), no raw
   UTC stamp; the same for a person without organisation
 - #2986 one rule for document dates: the language of the document, the country pack only as the fallback; recurring invoice
   periods, terms, invoice lines and reminders do not write a German or ISO date into another language
usage: p23682_a_api_test.py <datadir>"""
import csv
import io
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, done, sess, B, H, DATA  # noqa: E402,F401

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")


def in_app(code):
    """Runs python code inside the server container (the app loaded); -> stdout + stderr."""
    return subprocess.run(["docker", "exec", CT, "python", "-c", "import app\n" + code], capture_output=True, text=True)


if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs,files", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, F = freelancer(B, A)
O = "/api/office"
Y = time.strftime("%Y")
TODAY = time.strftime("%Y-%m-%d")
FILES = (O + f"/books/euer.csv?year={Y}", O + "/equipment/value.csv", O + f"/meals/report?from={Y}-01-01&to={TODAY}&format=csv",
         O + "/trips/report?by=month&format=csv", O + f"/trips/vma.csv?year={Y}")


def table(r, sep):
    return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=sep))


def cash_file(s, tag, sep, amount):
    bk = s.get(B + O + "/cashbooks").json()
    bk = (bk.get("books") if isinstance(bk, dict) else bk) or []
    bid = bk[0]["id"] if bk else s.post(B + O + "/cashbooks", json={"name": "Till", "opening_balance": "100"}).json()["id"]
    if tag.endswith(" en"):
        r = s.post(B + O + f"/cashbooks/{bid}/entries", json={"day": TODAY, "dir": "in", "amount": "12.50", "text": "Counter sale", "vat_pct": "19"})
        check(r.ok, f"{tag}: a cash entry " + r.text[:200])
    r = s.get(B + O + f"/cashbook.csv?book_id={bid}&year={Y}")
    rows = table(r, sep)
    row = next((x for x in rows if len(x) > 4 and x[2] == "Counter sale"), [])
    check(row[4:5] == [amount], f"{tag}: cash book amount {row}")
    i = next((n for n, x in enumerate(rows) if x[:1] and x[0] in ("Change log", "Änderungsprotokoll")), None)
    log = [x for x in rows[i + 2:] if len(x) >= 4] if i is not None else []
    check(log and all(re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", x[0]) for x in log), f"{tag}: the logged times are local, not raw UTC {log[:2]}")


for s, tag in ((A, "org"), (F, "freelancer")):
    s.patch(B + "/api/settings", json={"lang": "en"})
    for url in FILES:
        r = s.get(B + url)
        check(r.ok and "," in r.content.decode("utf-8-sig").splitlines()[0] and ";" not in r.content.decode("utf-8-sig").splitlines()[0],
              f"{tag}: English separator in {url}: {r.status_code} {r.text[:120]!r}")
    rows = table(s.get(B + O + f"/books/euer.csv?year={Y}"), ",")
    check(rows[0] == ["Group", "Net", "VAT", "Gross"] and any(x[0] == "Profit" and re.fullmatch(r"-?\d+\.\d\d", x[1]) for x in rows if len(x) > 1), f"{tag}: EUeR with the point {rows}")
    cash_file(s, tag + " en", ",", "12.50")
    s.patch(B + "/api/settings", json={"lang": "de"})
    for url in FILES:
        r = s.get(B + url)
        check(r.ok and ";" in r.content.decode("utf-8-sig").splitlines()[0], f"{tag}: German separator in {url}: {r.status_code} {r.text[:120]!r}")
    rows = table(s.get(B + O + f"/books/euer.csv?year={Y}"), ";")
    check(any(re.fullmatch(r"-?\d+,\d\d", x[1]) for x in rows if len(x) > 1 and x[1]), f"{tag}: EUeR with the comma {rows}")
    cash_file(s, tag + " de", ";", "12,50")
    s.patch(B + "/api/settings", json={"lang": "en"})

r = in_app(r"""
from datetime import date, datetime, timezone
from kalmido.core.db import TZ, local_stamp
from kalmido.core.i18n import csv_dialect, short_day
from kalmido.office.docs import _fmt_date
from kalmido.office.recurring import _period_txt, rin_fill
from kalmido.office.subs import _fmt_day as sub_day
from kalmido.office.terms import agb_fmt_date
from kalmido.office.travel import _fmt_day as trip_day
US = {"formats": {"date": "mm/dd/yyyy"}}
print(csv_dialect("en")[0], csv_dialect("en")[1]("1234.50"), csv_dialect("de")[0], csv_dialect("de")[1]("1234.50"), repr(csv_dialect("fr")[1](None)), repr(csv_dialect("de")[1](0)), sep="|")
want = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc).astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")
print(local_stamp("2026-07-01T10:00:00.000+00:00") == want, local_stamp("2026-07-01T10:00:00") == want, repr(local_stamp(None)), local_stamp("kaputt"), sep="|")
print(_period_txt("2027-01-31", "2027-02-28", "en"), _period_txt("2027-01-31", "2027-02-28", "de"), _period_txt("2027-01-31", "2027-02-28", "fr"), sep="|")
print(rin_fill("{period}", "2027-01-31", "2027-02-28", "en", US), rin_fill("{period}", "2027-01-31", "2027-02-28", "de", US), sep="|")
print(_fmt_date("2026-10-09", US, "en"), _fmt_date("2026-10-09", US, "de"), _fmt_date("2026-10-09", US), sep="|")
print(agb_fmt_date("2026-10-09", "en"), agb_fmt_date("2026-10-09", "de"), agb_fmt_date("2026-10-09", "fr"), agb_fmt_date("", "de") == "", sep="|")
print(trip_day("2026-10-09", "en"), trip_day("2026-10-09", "de"), trip_day("", "en") == "", sep="|")
print(sub_day("2026-10-09", "en"), sub_day("2026-10-09", "de"), sep="|")
""")
L = r.stdout.splitlines()
check(r.returncode == 0 and len(L) == 8, "the helpers run " + r.stderr[-400:])
if len(L) == 8:
    check(L[0] == ",|1234.50|;|1234,50|''|'0'", "#2984: csv_dialect " + L[0])
    check(L[1] == "True|True|''|kaputt", "#2984: local_stamp " + L[1])
    check(L[2].split("|")[:2] == ["31 Jan 2027 - 27 Feb 2027", "31.01.2027 - 27.02.2027"] and ".2027" not in L[2].split("|")[2], "#2986: the period text of the reader's language " + L[2])
    check(L[3] == "31 January 2027 - 27 February 2027|01/31/2027 - 02/27/2027", "#2986: {period}: the document's language, the pack as the fallback " + L[3])
    check(L[4] == "9 October 2026|10/09/2026|10/09/2026", "#2986: one rule for document dates " + L[4])
    check(L[5].split("|")[:2] == ["9 October 2026", "09.10.2026"] and "2026-10" not in L[5] and "." not in L[5].split("|")[2] and L[5].endswith("True"), "#2986: terms: no ISO date " + L[5])
    check(L[6] == "9 October 2026|09.10.2026|True", "#2986: an invoice line of the travel expenses " + L[6])
    check(L[7] == "9 Oct 2026|09.10.2026", "#2986: subscription reminder " + L[7])
sys.exit(done("p23682_a_api"))
