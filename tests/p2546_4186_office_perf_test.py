#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.546.0 (#4186) API tests: the receipt lists of the office read trash and rights in one go, the bank list finds its
suggestions through an index -- the same answers, fewer statements. Own container (kt.fresh, server key + org encryption on).
Invented companies, people and figures only.
tenant-matrix: office  freelancer-matrix: office
 - rights unchanged: for every person (organisation admin, a member in "Staff" (own receipts), a member without a group,
   a member in a group without receipts, an admin of another organisation, an agent, a person without an organisation)
   and every receipt node (own, another person's, shared with an expired / a valid share, in a folder in the trash, in
   the trash itself, of another organisation, of the person without an organisation) files.store.fs_roles_many gives
   exactly what fs_chain + fs_role gave per node -- and needs far fewer statements (PERF line: before / after)
 - GET /api/office/books, /books/receipts: the admin sees her and bob's receipts, never the one in the trashed folder,
   the deleted one or another organisation's; bob (Staff) only his own; the person without an organisation only hers;
   the month list of the books = the year's receipts of that month (one run instead of two)
 - ratchet: the statements of /api/office/books, /books/receipts and /bank/tx stay the same (at most +2) for 12 more receipts
 - bank: bank.bnk_suggest with the index (bnk_suggest_index) gives the same suggestions in the same order as the full
   pair loop (random bookings, invoices and receipts with shared words / amounts); the bank list suggests the receipt of
   the same amount
usage: p2546_4186_office_perf_test.py <datadir>"""
import base64
import json
import os
import re
import subprocess
import sys

import kt
from kt import B, CT, check, sess, until
from freelancer_fixture import freelancer, org_join
import testclock

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY,
              "KALMIDO_TEST_TIMING_ALL": "1"}, prefix="P2546A")
kt.docker_logs_on_first_fail()
O = "/api/office"
FEAT = "cal,comments,collab,office,clients,files,docs"
TODAY = testclock.today()
TD = TODAY.isoformat()
MONTH = TD[:7]
YEAR = TD[:4]
TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


def in_app(code):
    """Python inside the server container (the app loaded, c = a connection, system context) -> stdout + stderr."""
    body = "\n".join("    " + x for x in code.split("\n"))
    out = subprocess.run(["docker", "exec", CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nc = connect()\n"
                          "with system_ctx(c):\n" + body + "\nc.close()"], capture_output=True, text=True)
    return out.stdout + out.stderr


def last_json(out):
    for line in reversed(out.strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    return {"_err": out[-1500:]}


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
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def receipts(s, ws, items, marker=None):
    """Upload receipts (name, amount or None) into documents space ws in one request; amount / date set by hand, marked as
    receipt (by marker's session, default s) -> their node ids in order."""
    files = [("files", (n, tiny_pdf(n), "application/pdf")) for n, _a in items]
    r = s.post(B + "/api/docs", data={"ws": ws}, files=files)
    assert r.ok, r.text
    ids = r.json()["ids"]
    assert len(ids) == len(items), r.text
    for nid in ids:
        until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 60)
    for nid, (_n, amt) in zip(ids, items):
        if amt is not None:
            r = s.patch(B + f"/api/docs/{nid}", json={"amount": amt, "currency": "EUR", "date": TD})
            assert r.ok, r.text
        r = (marker or s).put(B + f"/api/docs/{nid}/receipt", json={"category": "Material", "vat_pct": "19", "keep": True})
        assert r.ok, r.text
    return ids


# ---------------------------------------------------------------- setup: two organisations, members, an agent, a freelancer
A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
U = {}
for u in ("bob", "carl", "dave", "eve"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com", "orgs": [] if u == "eve" else [{"id": ORG, "role": "member"}]})
    assert r.ok, r.text
    U[u] = r.json()["id"]
    if u != "eve":
        check(org_join(B, u, ORG), f"setup: {u} is a member of Alpha")
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": U["eve"]}).json()["id"]
Bo, Ca, Da, Ev = sess("bob"), sess("carl"), sess("dave"), sess("eve")
for s, ws in ((Bo, ORG), (Ca, ORG), (Da, ORG), (Ev, ORG2)):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ws}"})
check(A.put(B + O + "/settings", json={"company_fields": {"name": "Alpha Beispiel GmbH", **COMPANY}}).ok, "setup: Alpha's office")
check(Ev.put(B + O + "/settings", json={"company_fields": {"name": "Beta Beispiel GmbH", **COMPANY}}).ok, "setup: Beta's office")
R = O + "/rights"
check(A.put(B + f"{R}/people/{U['bob']}", json={"groups": ["tpl:staff"]}).ok, "setup: bob in Staff (own receipts)")
r = A.post(B + f"{R}/groups", json={"from": "tpl:none", "name": "Nothing yet"})
check(r.status_code == 201, "setup: a group without areas " + r.text[:200])
check(A.put(B + f"{R}/people/{U['dave']}", json={"groups": [f"g:{r.json().get('id')}"]}).ok, "setup: dave in the group without receipts")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "office"], "org_id": ORG})
check(r.ok, "setup: alice's agent " + r.text[:200])
AG = r.json().get("id")
FID, Fr = freelancer(B, A, "fiona", features=FEAT)  # freelancer-matrix: office (the personal office, its own admin)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
check(Fr.put(B + O + "/settings", json={"company_fields": {"name": "Fiona Grafik", **COMPANY}}).ok, "setup: Fiona's office")

# ---------------------------------------------------------------- receipts
RA = receipts(A, f"org:{ORG}", [("alice-paper.pdf", "11.90"), ("alice-ink.pdf", "23.80"), ("alice-cable.pdf", "35.70"),
                                 ("alice-trash.pdf", "47.60"), ("alice-gone.pdf", "59.50"), ("alice-noamount.pdf", None)])
RB = receipts(Bo, f"org:{ORG}", [("bob-taxi.pdf", "71.40")], marker=A)
RE = receipts(Ev, f"org:{ORG2}", [("eve-hotel.pdf", "83.30")])
RF = receipts(Fr, "private", [("fiona-brush.pdf", "95.20"), ("fiona-canvas.pdf", "107.10")])
R_TRASHED_FOLDER, R_DELETED = RA[3], RA[4]
root = kt.dbx("SELECT parent_id, owner_id, org_id FROM fs_nodes WHERE id=?", (RA[0],))[0]
kt.dbx("INSERT INTO fs_nodes(parent_id, kind, name, owner_id, org_id, created_by, created_at, updated_at) "
       "VALUES(?, 'folder', 'Old receipts', ?, ?, ?, '2026-10-01T10:00:00Z', '2026-10-01T10:00:00Z')",
       (root["parent_id"], root["owner_id"], root["org_id"], ALICE))
FOLDER = kt.dbx("SELECT id FROM fs_nodes WHERE name='Old receipts' AND org_id=?", (ORG,))[0]["id"]
kt.dbx("UPDATE fs_nodes SET parent_id=? WHERE id=?", (FOLDER, R_TRASHED_FOLDER))
kt.dbx("UPDATE fs_nodes SET deleted_at='2026-10-02T10:00:00Z' WHERE id=?", (FOLDER,))
kt.dbx("UPDATE fs_nodes SET deleted_at='2026-10-02T10:00:00Z' WHERE id=?", (R_DELETED,))
kt.dbx("INSERT INTO fs_shares(node_id, user_id, role, expires_at, created_by, created_at) VALUES(?, ?, 'view', '2020-01-01T00:00:00Z', ?, '2026-10-01T10:00:00Z')",
       (RA[1], U["carl"], ALICE))  # expired
kt.dbx("INSERT INTO fs_shares(node_id, user_id, role, created_by, created_at) VALUES(?, ?, 'edit', ?, '2026-10-01T10:00:00Z')", (RA[2], U["carl"], ALICE))
kt.dbx("INSERT INTO fs_shares(node_id, user_id, role, created_by, created_at) VALUES(?, ?, 'view', ?, '2026-10-01T10:00:00Z')", (RA[0], U["dave"], ALICE))
kt.dbx("INSERT INTO fs_shares(node_id, agent_id, role, created_by, created_at) VALUES(?, ?, 'view', ?, '2026-10-01T10:00:00Z')", (RA[1], AG, ALICE))
ALL = RA + RB + RE + RF + [FOLDER]
PEOPLE = {"alice": ALICE, "bob": U["bob"], "carl": U["carl"], "dave": U["dave"], "eve": U["eve"], "agent": AG, "fiona": FID}

# ---------------------------------------------------------------- the rights: fs_roles_many = fs_chain + fs_role per node
CODE = f"""
import json
from flask import g
from kalmido.core.config import app as fa
from kalmido.core.pg import rt_begin, rt_end
from kalmido.files.store import fs_chain, fs_deleted, fs_role, fs_roles_many
ids, people, out = {ALL!r}, {PEOPLE!r}, {{}}
for name, uid in people.items():
    with fa.test_request_context("/api/office/books"):
        rt_begin()
        old = {{}}
        for i in ids:  # the path before 2.546.0: fs_chain for the trash, then fs_role (its own fs_chain) per node
            ch = fs_chain(c, i)
            gone = fs_deleted(ch)
            old[i] = [gone, None if gone else fs_role(c, i, uid)]
        n_old = rt_end()[0]
    with fa.test_request_context("/api/office/books"):
        rt_begin()
        new = {{i: list(v) for i, v in fs_roles_many(c, ids, uid).items()}}
        n_new = rt_end()[0]
    out[name] = {{"old": {{str(k): v for k, v in old.items()}}, "new": {{str(k): v for k, v in new.items()}}, "n_old": n_old, "n_new": n_new}}
print(json.dumps(out))
"""
res = last_json(in_app(CODE))
check("_err" not in res, f"in the app: old and new rights path ran {res.get('_err')}")
for name, x in res.items():
    if name == "_err":
        continue
    diff = {k: (x["old"].get(k), x["new"].get(k)) for k in set(x["old"]) | set(x["new"]) if x["old"].get(k) != x["new"].get(k)}
    check(not diff, f"rights unchanged for {name}: trash and role of every node as before {diff}")
    check(x["n_new"] < x["n_old"], f"{name}: fewer statements for {len(ALL)} nodes ({x['n_old']} -> {x['n_new']})")
    print(f"PERF rights {name}: {len(ALL)} nodes, statements before {x['n_old']}, after {x['n_new']}", flush=True)
if "alice" in res:
    al, ev, fi, da = res["alice"]["new"], res["eve"]["new"], res["fiona"]["new"], res["dave"]["new"]
    check(all(al[str(i)][1] for i in RA[:3] + RB) and al[str(R_TRASHED_FOLDER)][0] and al[str(R_DELETED)][0],
          f"alice: her and bob's receipts, the trashed ones flagged {al}")
    check(not any(al[str(i)][1] for i in RF) and not any(ev[str(i)][1] for i in RA + RB) and not any(fi[str(i)][1] for i in RA + RB + RE),
          "another organisation / the personal office: no role across the boundary")
    check(not any(da[str(i)][1] for i in RA + RB), f"dave (no receipts area): no receipt, not even the shared one {da}")
    bo = res["bob"]["new"]
    check(bo[str(RB[0])][1] and not any(bo[str(i)][1] for i in RA[:3]), f"bob (Staff): only his own receipt {bo}")


# ---------------------------------------------------------------- the lists over the API
def books(s):
    r = s.get(B + O + f"/books?month={MONTH}&year={YEAR}")
    return r, ({x["node_id"] for x in r.json().get("receipts", [])} if r.ok else None)


def rlist(s):
    r = s.get(B + O + f"/books/receipts?from={YEAR}-01-01&to={YEAR}-12-31")
    return r, ({x["node_id"] for x in r.json().get("rows", [])} if r.ok else None)


r, seen = books(A)
check(seen == set(RA[:3] + RB), f"books: alice sees the month's receipts of Alpha, nothing in the trash, nothing of Beta {seen}")
j = r.json() if r.ok else {}
check(j.get("incomplete") == 1, f"books: the receipt without an amount counts as incomplete {j.get('incomplete')}")
check({x["node_id"] for x in j.get("missing", [])} == set(), f"books: every receipt has a VAT rate {j.get('missing')}")
r2 = A.get(B + O + f"/books?month={int(YEAR) - 1}-06&year={YEAR}")  # a month outside the year: its own run (nothing there)
check(r2.ok and r2.json().get("receipts") == [], f"books: a month of another year still answers (own run) {r2.status_code}")
r, seen = rlist(A)
check(seen == set(RA[:3] + RB), f"receipt list: alice {seen}")
amts = {x["node_id"]: x["amount"] for x in r.json().get("rows", [])} if r.ok else {}
check(amts == {RA[0]: "11.90", RA[1]: "23.80", RA[2]: "35.70", RB[0]: "71.40"}, f"receipt list: the amounts still opened (org key) {amts}")
r, seen = rlist(Bo)
check(r.status_code == 200 and seen == set(RB), f"receipt list: bob (Staff) only his own {r.status_code} {seen}")
r, seen = rlist(Da)
check(r.status_code == 403 or seen == set(), f"receipt list: dave (no receipts area) nothing {r.status_code} {seen}")
r, seen = rlist(Ev)
check(seen == set(RE), f"receipt list: eve only Beta's {seen}")
r, seen = books(Fr)
check(seen == set(RF), f"books: the person without an organisation sees her own receipts {seen}")
r, seen = rlist(Fr)
check(seen == set(RF), f"receipt list: the person without an organisation {seen}")
amts = {x["node_id"]: x["amount"] for x in r.json().get("rows", [])} if r.ok else {}
check(amts == {RF[0]: "95.20", RF[1]: "107.10"}, f"receipt list: the amounts of the personal office still opened {amts}")


# ---------------------------------------------------------------- ratchet: statements per added receipt
def counts(s):
    return {"books": nstmt(s.get(B + O + f"/books?month={MONTH}&year={YEAR}")),
            "receipts": nstmt(s.get(B + O + f"/books/receipts?from={YEAR}-01-01&to={YEAR}-12-31")),
            "bank": nstmt(s.get(B + O + "/bank/tx?state=all"))}


MORE = 12
for who, s, ws in (("alice", A, f"org:{ORG}"), ("fiona", Fr, "private")):
    counts(s)  # warm (the hints check of the list fills once)
    n1 = counts(s)
    receipts(s, ws, [(f"{who}-more-{k}.pdf", f"{k + 1}.19") for k in range(MORE)])
    counts(s)
    n2 = counts(s)
    print(f"PERF {who}: statements with +{MORE} receipts {n1} -> {n2}", flush=True)
    for k in n1:
        check(n1[k] > 0 and n2[k] - n1[k] <= 2, f"{who} {k}: the statements do not grow with the receipts ({n1[k]} -> {n2[k]} for +{MORE})")

# ---------------------------------------------------------------- bank: the index gives the same suggestions
CODE = """
import json, random
from datetime import date, timedelta
from decimal import Decimal
from kalmido.core.config import app as fa
from kalmido.office.bank import bnk_suggest, bnk_suggest_index
rnd = random.Random(4186)
W = ["Muster", "Beispiel", "Papier", "Druck", "Kabel", "Hotel", "Taxi", "AG", "Gmbh", "Nord", "Süd", "Büro", "re"]
AM = [Decimal(x) for x in ("10.00", "11.90", "23.80", "50.00", "99.99", "100.00", "250.00")]
d0 = date(2026, 6, 15)
def words(k):
    return " ".join(rnd.choice(W) for _ in range(k))
same = total = 0
with fa.test_request_context("/api/office/bank/tx"):
    for rnd_no in range(40):
        inv = [{"id": i, "number": rnd.choice(["", f"RE-2026-{i:03d}", f"R {i}", "re"]), "client": words(rnd.randint(0, 2)),
                "title": words(1), "currency": rnd.choice(["EUR", "EUR", "USD"]), "open": rnd.choice(AM)} for i in range(rnd.randint(0, 12))]
        rcs = [{"node_id": 1000 + i, "amount": rnd.choice(AM), "title": words(rnd.randint(0, 2)), "category": rnd.choice(["", "Material", "Reise"]),
                "date": (d0 + timedelta(days=rnd.randint(-20, 20))).isoformat(), "paid_at": rnd.choice([None, None, "2026-06-01"])}
               for i in range(rnd.randint(0, 15))]
        taken = {r["node_id"] for r in rcs if rnd.random() < 0.15}
        ix = bnk_suggest_index(inv, rcs)
        for _ in range(25):
            a = rnd.choice(AM) * rnd.choice([1, -1])
            if rnd.random() < 0.2:
                a = a - Decimal("1.00")
            num = rnd.choice(inv)["number"] if inv and rnd.random() < 0.4 else ""
            t = {"amount": a, "currency": rnd.choice(["EUR", "EUR", "USD"]), "counterpart": rnd.choice(["", words(2), words(1)]),
                 "purpose": f"{words(2)} {num}", "day": (d0 + timedelta(days=rnd.randint(-3, 3))).isoformat()}
            total += 1
            same += bnk_suggest(t, inv, rcs, taken) == bnk_suggest(t, inv, rcs, taken, ix)
print(json.dumps({"same": same, "total": total}))
"""
res = last_json(in_app(CODE))
check(res.get("total", 0) >= 500 and res.get("same") == res.get("total"), f"bank: the index gives the same suggestions in the same order {res}")

# the bank list: a booking of a receipt's amount suggests that receipt
camt = ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>'
        f'<Id>S1</Id><Ntry><Amt Ccy="EUR">23.80</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{TD}</Dt></BookgDt>'
        '<NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>Tinten Handel</Nm></Pty></Cdtr></RltdPties><RmtInf><Ustrd>Order 77</Ustrd></RmtInf>'
        '</TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>')
r = A.post(B + O + "/bank/import", json={"text": camt, "filename": "auszug.xml"})
check(r.status_code == 201, "bank: import one booking " + r.text[:200])
items = A.get(B + O + "/bank/tx").json().get("items", [])
sug = [s_["id"] for t in items for s_ in t.get("suggestions", []) if s_["kind"] == "receipt"]
check(sug[:1] == [RA[1]], f"bank: the booking of 23.80 suggests the receipt of the same amount {sug}")

sys.exit(kt.done("p2546_4186_office_perf"))
