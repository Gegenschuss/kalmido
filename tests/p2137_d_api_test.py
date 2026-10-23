#!/usr/bin/env python3
"""2.137.0 API tests, part D (#1981): a person takes their personal office into an existing organisation they are an admin
of (GET /api/office/move/check, POST /api/office/move/org). Invented companies, people and figures only.
freelancer-matrix: office
tenant-matrix: office
 - a person without an organisation fills the personal office (company data, logo, client, quotation, a finalised invoice
   with a purchase price and a payment, the cash book with a closed day), then becomes admin of organisations
 - rights: not a member 404, a member without the admin role 403, an agent 403, an office that is not personal 409, an
   empty personal office 409, no confirmation 400
 - a number the target uses already: the preview names it, the transfer is refused (409), nothing moved
 - preview -> transfer: every row in the organisation with its id, the invoice still finalised (409 on a change, the same
   number), payment and cash book readable, the closed day still closed, the file below the organisation's folder sealed
   with its key, the protected values sealed anew; no office row left in the personal office except settings, company
   data and counters; a member of the organisation sees the documents; one entry in the organisation's office log
usage: p2137_d_api_test.py <datadir>      (P2137D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import struct
import subprocess
import sys
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402; 2.148.1 (#2480): an invited member accepts

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
D = O + "/docs"
CBS = O + "/cashbooks"
CHK, MV = O + "/move/check", O + "/move/org"
MAIN = ("office_docs", "office_doc_items", "office_payments", "office_cash_entries", "office_cash_closings")  # the log grows by reading
KEEP = ("office_settings", "office_company", "office_cf_start", "office_cf_actual", "office_numbers")


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def enc(v):
    return str(v or "").startswith("kenc1:")


def ws(s, v):
    r = s.patch(B + "/api/settings", json={"workspace": v})
    assert r.ok, r.text


def png():
    """A 1x1 PNG, hand-made (no library)."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x6d\x28\xd9")) + chunk(b"IEND", b""))


def company(s, name):
    r = s.put(B + O + "/settings", json={"company_fields": {"name": name, "street": "Teststraße 1", "zip": "20000", "city": "Hamburg",
                                                            "country": "DE", "tax_number": "12/345/67890", "iban": "DE02120300000000202051",
                                                            "bic": "BYLADEM1001"}})
    assert r.ok, r.text


def invoice(s, client, cost=None):
    item = {"title": "Schnitt", "qty": 1, "rate": 100}
    if cost is not None:
        item["cost"] = cost
    r = s.post(B + D, json={"kind": "invoice", "client_id": client, "service_from": "2026-03-01", "service_to": "2026-03-02", "items": [item]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    return did


def docs(s):
    out = {}
    for kind in ("offer", "invoice"):
        r = s.get(B + D + f"?kind={kind}")
        out.update({x["id"]: x for x in (r.json().get("docs") or [])} if r.ok else {})
    return out


def head_org(path):
    with open(path, "rb") as fh:
        raw = fh.read(14)
    return struct.unpack(">q", raw[6:14])[0] if raw[:6] == b"KENC1\n" else None


def office_rows(oid):
    """{table: n} of the office tables with rows of office area oid (without the ones that stay on purpose)."""
    out = {}
    for (t,) in sql("SELECT DISTINCT table_name FROM information_schema.columns WHERE table_schema=current_schema() AND column_name='org_id' "
                    "AND left(table_name, 7)='office_'"):
        if t in KEEP:
            continue
        n = sql(f"SELECT COUNT(*) FROM {t} WHERE org_id=?", (oid,))[0][0]
        if n:
            out[t] = n
    return out


if os.environ.get("P2137D_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALPHA = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ws(A, f"org:{ALPHA}")
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], **H}

# ================================================================ the personal office of a person without an organisation
FID, Fr = freelancer(B, A)
ws(Fr, "private")
company(Fr, "Frida Film")
r = Fr.post(B + O + "/logo", files={"file": ("logo.png", png(), "image/png")})
check(r.ok, "personal office: the logo " + r.text[:200])
CL = Fr.post(B + "/api/clients", json={"name": "Kunde Nord GmbH", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]
r = Fr.post(B + D, json={"kind": "offer", "client_id": CL, "project_title": "Imagefilm", "items": [{"title": "Dreh", "qty": 2, "rate": 900}]})
assert r.status_code == 201, r.text
OFF = r.json()["id"]
INV = invoice(Fr, CL, cost=40)
NUM = Fr.get(B + f"{D}/{INV}").json()["number"]
r = Fr.post(B + f"{D}/{INV}/payments", json={"date": "2026-03-10", "amount": "119.00"})
check(r.status_code == 201, "personal office: the payment " + r.text[:200])
BK = Fr.get(B + CBS).json()["books"][0]["id"]
assert Fr.patch(B + f"{CBS}/{BK}", json={"opening": "100", "opening_day": "2026-01-01"}).ok
r = Fr.post(B + f"{CBS}/{BK}/entries", json={"day": "2026-03-01", "dir": "in", "amount": "50", "text": "Barverkauf Messe", "vat_pct": "19"})
check(r.status_code == 201, "personal office: a cash entry " + r.text[:200])
CE = r.json()["id"]
check(Fr.post(B + f"{CBS}/{BK}/closing", json={"day": "2026-03-01"}).ok, "personal office: the day closing")
PB = Fr.get(B + O + "/settings").json()["org_id"]
check(sql("SELECT personal_of FROM orgs WHERE id=?", (PB,))[0][0] == FID, "setup: the personal office")
TXT0 = sql("SELECT text FROM office_cash_entries WHERE id=?", (CE,))[0][0]
COST0 = sql("SELECT cost_enc FROM office_doc_items WHERE doc_id=?", (INV,))[0][0]
check(enc(TXT0) and enc(COST0), f"setup: cash text and purchase price encrypted at rest {TXT0!r:.20} {COST0!r:.20}")
PBDIR = os.path.join(DATA, "office", str(PB))
PDFS = [f for f in os.listdir(PBDIR) if f.startswith(f"doc{INV}-") and f.endswith(".pdf")]
check(len(PDFS) == 1 and head_org(os.path.join(PBDIR, PDFS[0])) == PB, f"setup: the stored PDF sealed with the personal office's key {PDFS}")
check(any(f.startswith("logo-") for f in os.listdir(PBDIR)), "setup: the frozen logo of the invoice")
BEFORE = office_rows(PB)

# ================================================================ rights
check(Fr.get(B + CHK + f"?org={ALPHA}").status_code == 404, "not a member of the target: 404")
check(Fr.get(B + CHK + "?org=999999").status_code == 404 and Fr.get(B + CHK + "?org=x").status_code == 404, "unknown target: 404")
assert A.put(B + f"/api/orgs/{ALPHA}/members", json={"email": "frida@example.com", "role": "member"}).ok
ws(Fr, "private")
check(Fr.get(B + CHK + f"?org={ALPHA}").status_code == 403, "a member without the admin role: 403 (preview)")
check(Fr.post(B + MV, json={"org": ALPHA, "confirm": True}).status_code == 403, "a member without the admin role: 403 (transfer)")
check(requests.get(B + CHK + f"?org={ALPHA}", headers=AGH).status_code == 403, "an agent: 403 (preview)")
check(requests.post(B + MV, headers=AGH, json={"org": ALPHA, "confirm": True}).status_code == 403, "an agent: 403 (transfer)")
check(A.get(B + CHK + f"?org={ALPHA}").status_code == 409, "the office shown is an organisation's, not a personal one: 409")

GAM = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": FID}).json()["id"]
KAP = A.post(B + "/api/admin/orgs", json={"name": "Kappa", "admin_id": FID}).json()["id"]
ws(Fr, "private")
mo = {o["id"] for o in Fr.get(B + O + "/settings").json().get("move_orgs") or []}
check(mo == {GAM, KAP}, f"settings: the organisations the person is an admin of {mo}")

FID2, Fi = freelancer(B, A, "fiona")
DEL = A.post(B + "/api/admin/orgs", json={"name": "Delta", "admin_id": FID2}).json()["id"]
ws(Fi, "private")
j = Fi.get(B + CHK + f"?org={DEL}").json()
check(j.get("ok") is False and j.get("conflicts"), f"an empty personal office: nothing to move {j}")
check(Fi.post(B + MV, json={"org": DEL, "confirm": True}).status_code == 409, "an empty personal office: 409")

# ================================================================ a number the target uses already
ws(Fr, f"org:{GAM}")
company(Fr, "Gamma Studio")
CLG = Fr.post(B + "/api/clients", json={"org_id": GAM, "name": "Kunde Sued AG", "street": "Weg 2", "zip": "10000", "city": "Berlin", "country": "DE"}).json()["id"]
INVG = invoice(Fr, CLG)
NUMG = Fr.get(B + f"{D}/{INVG}").json()["number"]
check(NUMG == NUM, f"setup: the same number in the organisation {NUMG} {NUM}")
ws(Fr, "private")
j = Fr.get(B + CHK + f"?org={GAM}").json()
check(j.get("ok") is False and NUM in (j.get("numbers") or []), f"preview: the number used in the target {j.get('numbers')}")
r = Fr.post(B + MV, json={"org": GAM, "confirm": True})
check(r.status_code == 409 and NUM in (r.json().get("numbers") or []), "a number conflict: 409 with the list " + r.text[:200])
now = office_rows(PB)
check(all(now.get(t) == BEFORE.get(t) for t in MAIN) and INV in docs(Fr), f"after the refusal nothing moved {now}")

# ================================================================ preview and transfer
assert (Fr.put(B + f"/api/orgs/{KAP}/members", json={"email": "bob@example.com", "role": "member"}).ok and org_join(B, "bob", KAP))
ws(Fr, "private")
r = Fr.get(B + CHK + f"?org={KAP}")
j = r.json()
check(r.ok and j["ok"] is True and j["org"]["id"] == KAP and not j["conflicts"], "preview: no conflict " + r.text[:300])
check(len(j["moves"]) >= 3 and len(j["keeps"]) >= 2 and "Kappa" in j["who"], f"preview: what goes, what stays, who sees it {j}")
check(Fr.post(B + MV, json={"org": KAP}).status_code == 400, "no confirmation: 400")
n_src = {(x[0], x[1]): x[2] for x in sql("SELECT kind, period, last FROM office_numbers WHERE org_id=?", (PB,))}
sql("INSERT INTO office_numbers(org_id, kind, period, last) SELECT ?, kind, period, 0 FROM office_numbers WHERE org_id=? "
    "ON CONFLICT(org_id, kind, period) DO NOTHING", (KAP, PB))  # 2.137.0 review M2: the target has its own, lower counters
r = Fr.post(B + MV, json={"org": KAP, "confirm": True})
check(r.ok and r.json().get("org_id") == KAP, "the transfer " + r.text[:300])
n_dst = {(x[0], x[1]): x[2] for x in sql("SELECT kind, period, last FROM office_numbers WHERE org_id=?", (KAP,))}
check(n_src and all(n_dst.get(k, 0) >= v for k, v in n_src.items()), f"the target's counters continue after the moved numbers {n_src} {n_dst}")

# the organisation's office (the app switched the workspace)
check(Fr.get(B + O + "/settings").json().get("org_id") == KAP, "afterwards the organisation's office is shown")
dk = docs(Fr)
check(INV in dk and OFF in dk, f"the documents are in the organisation with their ids {sorted(dk)}")
d = Fr.get(B + f"{D}/{INV}").json()
check(d.get("number") == NUM, "the invoice keeps its number")
check(Fr.patch(B + f"{D}/{INV}", json={"project_title": "anders"}).status_code == 409, "the invoice stays finalised (409 on a change)")
it = (d.get("items") or [{}])[0]
check(str(it.get("cost")) in ("40", "40.0", "40.00"), f"the purchase price readable with the organisation's key {it.get('cost')}")
p = Fr.get(B + f"{D}/{INV}/payments")
check(p.ok and len(p.json().get("payments") or p.json().get("items") or []) == 1, "the payment " + p.text[:200])
r = Fr.get(B + f"{D}/{INV}/pdf")
check(r.ok and r.content[:5] == b"%PDF-", "the stored PDF readable in the organisation")
e = Fr.get(B + f"{CBS}/{BK}/entries?year=2026")
check(e.ok and any(x["id"] == CE and x["text"] == "Barverkauf Messe" for x in e.json()["entries"]), "the cash entry readable " + e.text[:200])
check(e.json().get("last_closed") == "2026-03-01", "the closed day stays closed")
r = Fr.post(B + f"{CBS}/{BK}/entries", json={"day": "2026-03-01", "dir": "in", "amount": "5", "text": "x", "vat_pct": "19"})
check(r.status_code in (400, 409), "no entry on the closed day " + r.text[:200])
cl = sql("SELECT org_id FROM clients WHERE id=?", (CL,))[0][0]
check(cl == KAP, "the private client moved along")
# at rest: sealed anew (other ciphertext, the organisation's file folder and key)
TXT1 = sql("SELECT text FROM office_cash_entries WHERE id=?", (CE,))[0][0]
COST1 = sql("SELECT cost_enc FROM office_doc_items WHERE doc_id=?", (INV,))[0][0]
check(enc(TXT1) and TXT1 != TXT0 and enc(COST1) and COST1 != COST0, "the protected values sealed anew")
KDIR = os.path.join(DATA, "office", str(KAP))
kp = [f for f in os.listdir(KDIR) if f.startswith(f"doc{INV}-") and f.endswith(".pdf")] if os.path.isdir(KDIR) else []
check(len(kp) == 1 and head_org(os.path.join(KDIR, kp[0])) == KAP, f"the PDF below the organisation's folder, sealed with its key {kp}")
check(any(f.startswith("logo-") for f in os.listdir(KDIR)), "the frozen logo went along")
left = os.listdir(PBDIR)
check(not any(f.startswith("doc") or f.startswith("logo-") for f in left) and "logo.png" in left, f"the personal office keeps only its own logo {left}")
check(office_rows(PB) == {}, f"no office row left in the personal office {office_rows(PB)}")
check(sql("SELECT COUNT(*) FROM office_company WHERE org_id=?", (PB,))[0][0] == 1, "the company data stay in the personal office")
# who sees it: a member of the organisation
ws(Bo, f"org:{KAP}")
check(INV in docs(Bo), "a member of the organisation sees the documents")
lg = Fr.get(B + O + "/log?limit=20").json().get("log") or []
check(any(x.get("action") == "move" for x in lg), "an entry in the organisation's office log")
# the personal office is empty now, a second transfer has nothing to move
ws(Fr, "private")
check(docs(Fr) == {}, "the personal office is empty")
check(Fr.post(B + MV, json={"org": KAP, "confirm": True}).status_code == 409, "a second transfer: 409")

print(f"\np2137_d: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
