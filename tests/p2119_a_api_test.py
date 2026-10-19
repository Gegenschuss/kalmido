#!/usr/bin/env python3
"""2.119.0 API tests, part A (#2288): entertainment receipts (Bewirtungsbelege) in the office, own container (start.sh, org
encryption on). Invented companies, people and figures only.
 - a draft (host = me by default), the sums (VAT per line, tip without VAT, 70 / 30 of the net), the required fields of an
   approval (a vague occasion is refused), approving locks it (PATCH / DELETE / a new bill 409), new places and people join
   the choice lists (no duplicates, case ignored), undoing the approval with a reason is logged and the log stays when it is
   approved again; a draft that was approved once is kept (retention, 409), a draft that never was goes to the trash (restore)
 - the restaurant bill: PDF / JPEG / PNG only, served as uploaded, one live file (replace + restore), the PDF receipt (%PDF)
 - the evaluation of the approved meals with the filters of the travel expenses (year / period, person = host or guest,
   occasion), drafts counted apart, CSV (formula-safe) and PDF
 - the choice lists: add / same name = the one there / rename / remove + the undo (same id)
 - a move between the personal office and an organisation: a draft goes with its bill (readable there), an approved one
   stays (retention); the undo brings the bill back
 - rights: a member gets 403, another organisation 404, agents never; a person without an organisation has the module in the
   personal office -- freelancer-matrix: office -- tenant-matrix: office
usage: p2119_a_api_test.py <datadir>      (P2119A_NOSTART=1: use a running server)"""
import base64
import csv
import io
import os
import subprocess
import sys
import time

import requests

from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]


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


if os.environ.get("P2119A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
M = "/api/office/meals"
C = M + "/choices"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


def meal(s, code=201, **kw):
    r = s.post(B + M, json=kw)
    check(r.status_code == code, f"POST meal {code}: {r.status_code} {r.text[:300]}")
    return r.json()


def full(**kw):
    b = {"date": "2025-05-14", "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
         "occasion": "Negotiation of the follow-up order for the spring campaign", "host": {"id": ALICE},
         "guests": [{"name": "Gina Gast", "extra": "Example GmbH, buyer"}, {"id": BOB}],
         "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}, {"kind": "drinks", "rate": 7, "gross": 21.4}], "tip": "10"}
    b.update(kw)
    return b


# ---------------------------------------------------------------- a draft and its sums
m0 = meal(A)
check(m0["status"] == "draft" and not m0["locked"] and m0["host"] == {"id": ALICE, "name": "Alice Admin"}, f"a draft, host = me {m0.get('host')}")
r = A.patch(B + f"{M}/{m0['id']}", json=full(occasion="Geschäftsessen"))
check(r.ok, "the mask saved " + r.text[:200])
k = r.json()["calc"]
check((k["gross"], k["vat"], k["net"], k["tip"], k["deductible"], k["not_deductible"]) == ("150.40", "20.40", "130.00", "10.00", "91.00", "39.00"),
      f"the sums: VAT per line, tip without VAT, 70 / 30 of the net incl. tip {k}")
check([(x["kind"], x["rate"], x["vat"]) for x in k["lines"]] == [("food", "19", "19.00"), ("drinks", "7", "1.40")], f"VAT per line {k['lines']}")
r = A.post(B + f"{M}/{m0['id']}/approve")
check(r.status_code == 400 and "concrete" in r.text, "a vague occasion is refused " + r.text[:200])
for bad in ({"amounts": [{"kind": "wine", "gross": 1}]}, {"host": {"id": 999999}}, {"guests": "x"}, {"date": "2025-13-01"}, {"tip": -1}):
    check(A.patch(B + f"{M}/{m0['id']}", json=bad).status_code == 400, f"refused: {bad}")
d2 = meal(A, place_name="Imbiss", occasion="Kick-off of the website project")
r = A.post(B + f"{M}/{d2['id']}/approve")
check(r.status_code == 400 and "address" in r.text and "guest" in r.text and "Amounts" in r.text, "the missing fields are named " + r.text[:300])

# ---------------------------------------------------------------- approve = lock + choices
r = A.patch(B + f"{M}/{m0['id']}", json={"occasion": full()["occasion"]})
r = A.post(B + f"{M}/{m0['id']}/approve")
check(r.ok and r.json()["status"] == "approved" and r.json()["locked"] and r.json()["approved_name"] == "Alice Admin", "approved = locked, confirmed by " + r.text[:200])
MID = m0["id"]
check(A.post(B + f"{M}/{MID}/approve").status_code == 409, "approving twice: 409")
check(A.patch(B + f"{M}/{MID}", json={"tip": 0}).status_code == 409, "a locked receipt cannot be changed (409)")
check(A.delete(B + f"{M}/{MID}").status_code == 409, "a locked receipt cannot be deleted (409)")
check(A.post(B + f"{M}/{MID}/file", files={"file": ("bill.pdf", PDF, "application/pdf")}).status_code == 409, "no new bill on a locked receipt (409)")
ch = A.get(B + C).json()
check([(p["name"], p["extra"]) for p in ch["places"]] == [("Trattoria Esempio", "Beispielweg 1\n12345 Musterstadt")], f"the place joined the choices {ch['places']}")
check([(p["name"], p["extra"]) for p in ch["persons"]] == [("Gina Gast", "Example GmbH, buyer")], f"the free guest joined (no office people) {ch['persons']}")
m3 = meal(A, **full(place_name="TRATTORIA esempio", guests=[{"name": "gina gast", "extra": ""}, {"name": "Hans Neu", "extra": "Studio Beispiel"}]))
check(A.post(B + f"{M}/{m3['id']}/approve").ok, "a second approval")
ch = A.get(B + C).json()
check(len(ch["places"]) == 1 and sorted(p["name"] for p in ch["persons"]) == ["Gina Gast", "Hans Neu"], f"no duplicates (case ignored) {ch}")

# ---------------------------------------------------------------- undo the approval (logged)
r = A.post(B + f"{M}/{MID}/unlock", json={"reason": "Typo in the occasion"})
check(r.ok and r.json()["status"] == "draft" and not r.json()["locked"], "the approval undone " + r.text[:200])
check(A.post(B + f"{M}/{MID}/unlock").status_code == 409, "a draft cannot be unlocked (409)")
check(A.patch(B + f"{M}/{MID}", json={"occasion": "Negotiation of the follow-up order (spring campaign 2025)"}).ok, "the draft changes again")
check(A.post(B + f"{M}/{MID}/approve").ok, "approved again")
lg = A.get(B + f"{M}/{MID}").json()["log"]
check([(e["action"], e["user"], e["reason"]) for e in lg] == [("approve", "Alice Admin", ""), ("unlock", "Alice Admin", "Typo in the occasion"), ("approve", "Alice Admin", "")],
      f"the log keeps who, when, why {lg}")
A.post(B + f"{M}/{MID}/unlock", json={"reason": "check"})
r = A.delete(B + f"{M}/{MID}")
check(r.status_code == 409 and "2034" in r.text, "a receipt approved once is kept 8 years after its year (409) " + r.text[:200])
A.post(B + f"{M}/{MID}/approve")

# ---------------------------------------------------------------- a draft: trash + restore, duplicate
r = A.delete(B + f"{M}/{d2['id']}")
check(r.ok, "a draft that was never approved goes to the trash")
check(d2["id"] not in [x["id"] for x in A.get(B + M).json()["meals"]], "not listed any more")
check(A.post(B + f"{M}/{d2['id']}/restore").ok and d2["id"] in [x["id"] for x in A.get(B + M).json()["meals"]], "the undo restores it")
src = A.get(B + f"{M}/{MID}").json()
dup = meal(A, **{k: src[k] for k in ("date", "place_name", "place_address", "occasion", "host", "guests", "amounts", "tip", "note")})
check(dup["status"] == "draft" and dup["calc"]["gross"] == src["calc"]["gross"] and dup["files"] == [] and dup["log"] == [], "the copy: same data, a draft, no bill, no log")

# ---------------------------------------------------------------- the restaurant bill
r = A.post(B + f"{M}/{dup['id']}/file", files={"file": ("rechnung.pdf", PDF, "application/pdf")})
check(r.status_code == 201 and len(r.json()["files"]) == 1, "a PDF bill attached " + r.text[:200])
F1 = r.json()["file_id"]
g = A.get(B + f"{M}/{dup['id']}/file/{F1}")
check(g.ok and g.content == PDF and g.headers.get("Content-Type", "").startswith("application/pdf"), "served as uploaded (decrypted)")
r = A.post(B + f"{M}/{dup['id']}/file", files={"file": ("photo.png", PNG, "image/png")})
check(r.status_code == 201 and [f["mime"] for f in r.json()["files"]] == ["image/png"] and r.json()["replaced"] == [F1], "a photo replaces it (one live file)")
F2 = r.json()["file_id"]
check(A.post(B + f"{M}/{dup['id']}/file", files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 400, "a text file is refused")
r = A.post(B + f"{M}/{dup['id']}/file/{F1}/restore")
check(r.ok and [f["id"] for f in r.json()["files"]] == [F1], "the undo of the replacement brings the PDF back")
check(A.delete(B + f"{M}/{dup['id']}/file/{F1}").ok and A.get(B + f"{M}/{dup['id']}").json()["files"] == [], "the bill removed")
check(A.post(B + f"{M}/{dup['id']}/file/{F1}/restore").ok, "and restored")
check(A.get(B + f"{M}/{dup['id']}/file/{F2}").status_code == 404, "a trashed file is not served")
p = A.get(B + f"{M}/{MID}/pdf")
check(p.ok and p.content[:5] == b"%PDF-" and p.headers.get("Content-Type") == "application/pdf", "the PDF receipt")
check(A.get(B + f"{M}/{dup['id']}/pdf").content[:5] == b"%PDF-", "the PDF of a draft too")

# ---------------------------------------------------------------- the evaluation with filters
meal(A, **full(date="2024-11-02", occasion="Year-end talk with the agency"))
o24 = A.get(B + M + "?year=2024").json()["meals"][0]
A.post(B + f"{M}/{o24['id']}/approve")
rep = A.get(B + M + "/report?year=2025").json()
check(rep["count"] == 2 and rep["total"]["gross"] == "300.80" and rep["total"]["deductible"] == "182.00" and rep["total"]["vat"] == "40.80",
      f"the year: only approved ones, 70 % and input VAT {rep['count']} {rep['total']}")
check(rep["drafts"] == 1, f"the drafts are counted apart {rep['drafts']}")
check([(g["kind"], g["rate"], g["vat"]) for g in rep["rates"]] == [("drinks", "7", "2.80"), ("food", "19", "38.00")], f"input VAT per rate {rep['rates']}")
check(A.get(B + M + "/report").json()["count"] == 3, "all years")
check(A.get(B + M + "/report?from=2025-05-01&to=2025-05-31").json()["count"] == 2, "a period")
check(A.get(B + M + "/report?year=2025&person=n:hans%20neu").json()["count"] == 1, "a person: only meals with that guest")
check(A.get(B + M + f"/report?year=2025&person=u{BOB}").json()["count"] == 1 and A.get(B + M + f"/report?person=u{CAROL}").json()["count"] == 0,
      "a person of the office (guest)")
check(A.get(B + M + "/report?occasion=YEAR-END").json()["count"] == 1, "the occasion (part of the text, case ignored)")
for bad in ("person=x", "year=25", "from=2025-02-30"):
    check(A.get(B + M + "/report?" + bad).status_code == 400, f"refused: {bad}")
m4 = meal(A, **full(date="2023-03-03", occasion="=HYPERLINK(1) planning of the trade fair stand"))
check(A.post(B + f"{M}/{m4['id']}/approve").ok, "a meal of 2023 approved")
r = A.get(B + M + "/report?year=2023&format=csv")
check("'=HYPERLINK" in r.content.decode("utf-8-sig"), "the CSV is safe against formulas")
r = A.get(B + M + "/report?year=2025&format=csv")
rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
check(r.ok and rows[0][0] == "Date" and len(rows) == 4 and rows[-1][0] == "Total" and rows[-1][9] == "300,80", f"the CSV: one row per approved meal + total {rows[-1] if rows else r.text[:200]}")
check("entertainment-2025-01-01-2025-12-31" in r.headers.get("Content-Disposition", ""), "the CSV is named after the period")
r = A.get(B + M + "/report?year=2025&person=n:hans%20neu&format=pdf")
check(r.ok and r.content[:5] == b"%PDF-", "the evaluation as PDF with a filter")

# ---------------------------------------------------------------- the choice lists
r = A.post(B + C, json={"kind": "place", "name": "Café Muster", "extra": "Musterplatz 2"})
check(r.status_code == 201, "a place added " + r.text[:200])
CP = r.json()["id"]
check(A.post(B + C, json={"kind": "place", "name": "café muster"}).status_code == 200, "the same name: the one there (200)")
check(A.post(B + C, json={"kind": "x", "name": "y"}).status_code == 400 and A.post(B + C, json={"kind": "person", "name": " "}).status_code == 400, "a wrong kind / empty name: 400")
check(A.patch(B + f"{C}/{CP}", json={"name": "Café Beispiel", "extra": "Musterplatz 3"}).ok, "renamed")
check(A.patch(B + f"{C}/{CP}", json={"name": "Trattoria Esempio"}).status_code == 400, "a name that is there already: 400")
r = A.delete(B + f"{C}/{CP}")
check(r.ok and CP not in [p["id"] for p in A.get(B + C).json()["places"]], "removed")
r = A.post(B + C, json=r.json()["choice"])
check(r.status_code == 201 and r.json()["id"] == CP, "the undo brings it back with its id")
check(A.get(B + f"{M}/{MID}").json()["place_name"] == "Trattoria Esempio", "the meals keep their text")

# ---------------------------------------------------------------- rights
for m_, u, kw in (("get", M, {}), ("post", M, {"json": {}}), ("get", f"{M}/{MID}", {}), ("get", f"{M}/{MID}/pdf", {}), ("get", M + "/report", {}),
                  ("get", C, {}), ("post", f"{M}/{dup['id']}/approve", {})):
    check(getattr(Bo, m_)(B + u, **kw).status_code == 403, f"a member without the office admin gets 403: {m_} {u}")
check(Ca.get(B + M).json()["meals"] == [] and Ca.get(B + C).json() == {"places": [], "persons": []}, "another organisation sees none")
for m_, u, kw in (("get", f"{M}/{MID}", {}), ("patch", f"{M}/{dup['id']}", {"json": {"tip": 1}}), ("delete", f"{M}/{dup['id']}", {}),
                  ("post", f"{M}/{MID}/unlock", {"json": {}}), ("get", f"{M}/{MID}/pdf", {}), ("get", f"{M}/{dup['id']}/file/{F1}", {}),
                  ("patch", f"{C}/{CP}", {"json": {"name": "Fremd"}}), ("delete", f"{C}/{CP}", {})):
    check(getattr(Ca, m_)(B + u, **kw).status_code == 404, f"another organisation gets 404: {m_} {u}")
check(Ca.get(B + M + f"/report?person=u{ALICE}").json()["count"] == 0, "another organisation's evaluation never contains these")
check(Ca.post(B + "/api/office/move-space", json={"what": "meals", "ids": [dup["id"]], "to": f"org:{ORG2}", "dry": 1}).status_code == 404, "nor moves them")

# freelancer-matrix: office -- a person without an organisation: the personal office, its own module
FID, Fr = freelancer(B, A)
f1 = meal(Fr, **full(host={}, guests=[{"name": "Kunde Beispiel", "extra": "Example AG"}]))
check(f1["host"] is None, "freelancer: an empty host stays empty")
check(Fr.post(B + f"{M}/{f1['id']}/approve").status_code == 400, "freelancer: the host is required")
check(Fr.patch(B + f"{M}/{f1['id']}", json={"host": {"id": FID}}).ok and Fr.post(B + f"{M}/{f1['id']}/approve").ok, "freelancer: approved as her own host")
check(Fr.get(B + M + f"/report?year=2025&person=u{FID}").json()["count"] == 1, "freelancer: her evaluation")
check(Fr.get(B + C).json()["persons"][0]["name"] == "Kunde Beispiel", "freelancer: her own choice list")
check(Fr.get(B + f"{M}/{f1['id']}/pdf").content[:5] == b"%PDF-", "freelancer: the PDF")
check(A.get(B + f"{M}/{f1['id']}").status_code == 404 and "Kunde Beispiel" not in str(A.get(B + C).json()), "an organisation never sees the personal office's receipts")

# ---------------------------------------------------------------- a move between the personal office and the organisation
A.patch(B + "/api/settings", json={"workspace": "private"})
pm = meal(A, **full(date="2025-06-01", occasion="Pitch for the summer spot", guests=[{"name": "Paula Privat", "extra": "Beispiel KG"}, {"id": ALICE}]))
r = A.post(B + f"{M}/{pm['id']}/file", files={"file": ("privat.pdf", PDF, "application/pdf")})
PF = r.json()["file_id"]
pa = meal(A, **full(date="2025-06-02", guests=[{"name": "Paula Privat", "extra": "Beispiel KG"}]))
A.post(B + f"{M}/{pa['id']}/approve")
r = A.post(B + "/api/office/move-space", json={"what": "meals", "ids": [pm["id"], pa["id"]], "to": f"org:{ORG}", "dry": 1})
check(r.ok and "stays" in str(r.json()) and r.json()["count"]["meals"] == 1, "the dry run: the approved one stays (retention) " + r.text[:300])
r = A.post(B + "/api/office/move-space", json={"what": "meals", "ids": [pm["id"], pa["id"]], "to": f"org:{ORG}"})
check(r.ok, "the draft moves into the organisation " + r.text[:300])
MOVE = r.json().get("move_id")
check(pa["id"] in [x["id"] for x in A.get(B + M).json()["meals"]], "the approved one stays in the personal office")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
mv = A.get(B + f"{M}/{pm['id']}").json()
check(mv.get("occasion") == "Pitch for the summer spot" and [f["name"] for f in mv.get("files", [])] == ["privat.pdf"], f"there with its bill {mv.get('files')}")
check(A.get(B + f"{M}/{pm['id']}/file/{PF}").content == PDF, "the bill is readable in the organisation (sealed anew)")
check(any(g.get("id") == ALICE for g in mv["guests"]), "a person of both offices keeps her id")
r = A.post(B + "/api/office/move-space", json={"undo": MOVE})
check(r.ok, "the undo of the move " + r.text[:200])
A.patch(B + "/api/settings", json={"workspace": "private"})
check(A.get(B + f"{M}/{pm['id']}/file/{PF}").content == PDF, "the bill is back and readable in the personal office")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.get(B + f"{M}/{pm['id']}").status_code == 404, "and gone from the organisation")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
