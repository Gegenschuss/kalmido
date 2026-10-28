#!/usr/bin/env python3
"""2.58.0 API tests, part B, own container in mode workspaces (start.sh). Invented names and amounts only.
 - #1656: a bulk move into an imported (mirrored) address book -> 409 (also the single move and the token API); a contact
   deleted over CardDAV trashes its birthday task like the app; a birthday task in a list the person may not change stays
   with its link when the contact moves (and stays when it is deleted)
 - #1759: a part on the title page x 1.5 with two tax rates: the title line is exactly rate x qty and the sum of its tax
   amounts; invoices from the quotation (full / title / summary) give the quotation's net, gross and tax bases per rate
usage: p258_b_api_test.py <datadir>"""
import os
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def vcf(prefix, n, bday=None):
    out = []
    for i in range(n):
        out += ["BEGIN:VCARD", "VERSION:3.0", f"UID:{prefix}-{i}", f"FN:{prefix.title()} Person {i}", f"N:Person {i};{prefix.title()};;;",
                f"EMAIL;TYPE=HOME:{prefix}{i}@example.com", *([f"BDAY:{bday}"] if bday else []), "END:VCARD"]
    return "\r\n".join(out) + "\r\n"


def book(s, name):
    r = s.post(B + "/api/books", json={"name": name})
    assert r.ok, r.text
    return r.json()["id"]


def ids_of(s, bid):
    r = s.get(B + f"/api/contacts?book_id={bid}&limit=2000")
    assert r.ok, r.text
    return sorted(x["id"] for x in r.json()["items"])


def live_task(tid):
    return bool(dbx("SELECT id FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)))


def occ_of(cid):
    return [r[0] for r in dbx("SELECT task_id FROM contact_occ WHERE contact_id=?", (cid,))]


# ---------------------------------------------------------------- setup
if not os.environ.get("KMT_NOSTART"):  # KMT_NOSTART=1: against an app in mode workspaces that already runs (a quick local check)
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["contacts", "family"]})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
for s_ in (A, Bo):
    s_.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ================================================================== #1656: no move into an imported address book
A1, A2 = book(A, "Own"), book(A, "Mirror")
A.post(B + f"/api/books/{A1}/import", files={"file": ("a.vcf", vcf("mv", 2).encode(), "text/vcard")})
mv = ids_of(A, A1)
ALICE = A.get(B + "/api/state").json()["me"]["id"]
dbx("INSERT INTO contact_srcs(user_id, url, created_at) VALUES(?, 'https://dav.example.com/', '2026-01-01T00:00:00+00:00')", (ALICE,))
SRC = dbx("SELECT MAX(id) FROM contact_srcs WHERE user_id=?", (ALICE,))[0][0]
dbx("UPDATE books SET src_id=? WHERE id=?", (SRC, A2))
r = A.post(B + "/api/contacts/bulk", json={"action": "move", "ids": mv, "book_id": A2})
check(r.status_code == 409 and "imported" in r.json().get("error", ""), f"#1656: bulk move into an imported address book -> 409 {r.status_code} {r.text[:160]}")
check(ids_of(A, A1) == mv, "#1656: ... nothing moved")
r = A.patch(B + f"/api/contacts/{mv[0]}", json={"book_id": A2})
check(r.status_code == 409 and ids_of(A, A1) == mv, f"#1656: the single move too -> 409 {r.status_code}")
tok = A.post(B + "/api/me/tokens", json={"name": "t258b", "scopes": ["read", "contacts"]}).json()["token"]
r = requests.post(B + "/api/v1/contacts/bulk", headers={"Authorization": "Bearer " + tok}, json={"action": "move", "ids": mv, "book_id": A2})
check(r.status_code == 409, f"#1656: the token API (agents) -> 409 {r.status_code} {r.text[:160]}")

# ================================================================== #1656: CardDAV delete = the app's delete for birthday tasks
BL = A.post(B + "/api/lists", json={"name": "Birthdays"}).json()["id"]
F = book(A, "Bday")
check(A.patch(B + f"/api/books/{F}", json={"birthdays_list_id": BL}).ok, "#1656: a book with a birthday list")
A.post(B + f"/api/books/{F}/import", files={"file": ("b.vcf", vcf("dv", 1, "1980-05-12").encode(), "text/vcard")})
cid = ids_of(A, F)[0]
tid = (occ_of(cid) or [None])[0]
check(tid and live_task(tid), f"#1656: the contact has its birthday task {tid}")
PW = A.post(B + "/api/me/app-passwords", json={"name": "Phone"}).json()["password"]
r = requests.delete(B + f"/dav/addressbooks/alice/b{F}/dv-0.vcf", auth=("alice", PW))
check(r.status_code == 204 and not ids_of(A, F), f"#1656: deleted over CardDAV {r.status_code}")
check(tid and not live_task(tid) and dbx("SELECT deleted_at FROM tasks WHERE id=?", (tid,))[0][0], "#1656: its birthday task is in the trash (as in the app)")

# ================================================================== #1656: a birthday list the person may not change
BLB = Bo.post(B + "/api/lists", json={"name": "Bob's birthdays"}).json()["id"]
BB = book(Bo, "Bob's book")
check(Bo.patch(B + f"/api/books/{BB}", json={"birthdays_list_id": BLB}).ok, "#1656: Bob's book with Bob's birthday list")
Bo.post(B + f"/api/books/{BB}/import", files={"file": ("c.vcf", vcf("bb", 2, "1975-02-03").encode(), "text/vcard")})
check(Bo.put(B + f"/api/books/{BB}/members", json={"user_id": ALICE, "role": "edit"}).ok, "#1656: shared with Alice (edit)")
bb = ids_of(Bo, BB)
t0, t1 = (occ_of(bb[0]) or [None])[0], (occ_of(bb[1]) or [None])[0]
check(t0 and t1 and live_task(t0) and live_task(t1), "#1656: Bob's birthday tasks")
r = A.post(B + "/api/contacts/bulk", json={"action": "move", "ids": [bb[0]], "book_id": A1})
check(r.ok and r.json().get("moved") == 1, f"#1656: Alice moves one into her book {r.text[:160]}")
check(live_task(t0) and occ_of(bb[0]) == [t0], f"#1656: the task in Bob's list stays, with its link {occ_of(bb[0])}")
r = A.post(B + "/api/contacts/bulk", json={"action": "delete", "ids": [bb[1]]})
check(r.ok and live_task(t1), f"#1656: deleting the other leaves Bob's task alone {r.text[:160]}")

# ================================================================== #1759: a part x 1.5 with two tax rates
A.patch(B + "/api/settings", json={"features": "office,clients,contacts", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
D = "/api/office/docs"


def svc(t, q, rate, tax="standard"):
    return {"kind": "service", "title": t, "qty": q, "unit": "day", "rate": rate, "tax": tax, "raw_fee": 0, "producing": 0,
            "intext": "intern", "cost": 0, "discountable": 1}


def money(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


r = A.post(B + D, json={"kind": "offer", "lang": "en", "project_title": "Cents", "items": []})
check(r.status_code == 201, "#1759: quotation " + r.text[:200])
DOC = r.json()["id"]
P = A.post(B + f"{D}/{DOC}/parts", json={"title": "Shoot days"}).json()["part"]["id"]
# standard 110.01 x 1.5 = 165.015 and reduced 50.01 x 1.5 = 75.015 each round up: one cent more than 160.02 x 1.5 = 240.03
r = A.put(B + f"{D}/{DOC}/parts/{P}/items", json={"items": [svc("Camera", 1, 10.01), svc("Light", 1, 100), svc("Booklet", 1, 50.01, "reduced")]})
items = r.json()["items"]
items[-1]["qty"] = 1.5
r = A.put(B + f"{D}/{DOC}/items", json={"items": items})
off = r.json()["totals"]
ln = next((x for x in off["lines"] if x.get("part_id")), {})
check(money(ln.get("total", 0)) == money(Decimal(str(ln.get("rate", 0))) * Decimal("1.5")) == Decimal("240.03"),
      f"#1759: the title line = rate x qty ({ln.get('rate')} x 1.5 = {ln.get('total')})")
check(sum(money(v) for v in (ln.get("taxes") or {}).values()) == money(ln.get("total", 0)), f"#1759: its tax amounts add up to it {ln.get('taxes')}")
qb = {t["rate_key"]: money(t["base"]) for t in off["tax_lines"]}
check(sum(qb.values()) == money(off["net"]) == Decimal("240.03"), f"#1759: the quotation's bases add up to its net {qb} {off['net']}")
for mode in ("full", "title", "summary"):
    r = A.post(B + f"{D}/{DOC}/invoice", json={"parts_mode": mode, "force": True})  # 2.356.0 (#3003): a further full invoice from the same quotation only with force (else 409 invoice_exists)
    check(r.status_code == 201, f"#1759: invoice {mode} " + r.text[:200])
    t = r.json().get("totals", {})
    ib = {x["rate_key"]: money(x["base"]) for x in t.get("tax_lines", [])}
    check(money(t.get("net", 0)) == money(off["net"]) and money(t.get("gross", 0)) == money(off["gross"]) and ib == qb,
          f"#1759: invoice {mode} = the quotation to the cent ({t.get('net')} / {t.get('gross')} {ib} vs {off['net']} / {off['gross']} {qb})")
    if mode == "full":
        flat = [x for x in r.json()["items"] if x.get("unit") == "flat" and "1.5 ×" in (x.get("detail") or "")]
        check(len(flat) == 1, f"#1759: full: the rest cent sits on one position (qty x rate in its detail) {[(x['title'], x['qty'], x['unit'], x.get('detail')) for x in r.json()['items']]}")

print(f"p258_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
