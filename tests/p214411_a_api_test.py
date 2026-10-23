#!/usr/bin/env python3
"""2.144.11 API tests, part A (#2354): the open review points of the cash book (2.121.0 B). Invented names and figures only.
tenant-matrix: office
freelancer-matrix: office
 - N3: office_cash_log.entry_id is ON DELETE SET NULL on a new database; an older database (CASCADE) is turned at the
   next start (restart with KEEP=1); a log line outlives its entry
 - N4: the lists decrypt only what they show: the box list (balance, count) and the entries of another year carry no
   cipher text, the balance still counts every entry; a new entry comes back with its text
 - N6: the receipt hint goes through the office gate: office switched off 403, an agent refused; the admin and a person
   without an organisation (personal office) still see their entries
usage: p214411_a_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
CBS, CE = O + "/cashbooks", O + "/cash-entries"
FK = ("SELECT con.confdeltype FROM pg_constraint con JOIN pg_class t ON t.oid=con.conrelid "
      "JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(con.conkey) "
      "WHERE t.relname='office_cash_log' AND con.contype='f' AND a.attname='entry_id'")


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def start(keep=False):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}",
               **({"KEEP": "1"} if keep else {}))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    for _ in range(60):
        try:
            if requests.get(B + "/api/health", timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)


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


def receipt(s, ws, name, amount, day):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    assert s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Material", "vat_pct": "19", "keep": True}).ok
    return nid


start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}

# ---- N3: SET NULL on a new database
check([r[0] for r in sql(FK)] == ["n"], f"new database: entry_id ON DELETE SET NULL {sql(FK)}")
j = A.get(B + CBS).json()
BK = j["books"][0]["id"]
check(A.patch(B + f"{CBS}/{BK}", json={"opening": "100", "opening_day": "2025-01-02"}).ok, "opening balance 100")


def post(s, body, path=None):
    return s.post(B + (path or f"{CBS}/{BK}/entries"), json=body)


r = post(A, {"day": "2025-06-03", "dir": "in", "amount": "10", "text": "Vorjahr Einnahme Nordwind"})
check(r.status_code == 201 and r.json()["text"] == "Vorjahr Einnahme Nordwind", "entry of the year before " + r.text[:200])
OLD = r.json()["id"]
r = post(A, {"day": "2026-01-05", "dir": "out", "amount": "4.50", "text": "Briefmarken Kontor"})
check(r.status_code == 201 and r.json()["text"] == "Briefmarken Kontor" and r.json()["balance"] == "105.50", "N4: a new entry with its text + balance " + r.text[:200])
E2 = r.json()["id"]
check(A.patch(B + f"{CE}/{E2}", json={"text": "Briefmarken Kontor Ost"}).json().get("text") == "Briefmarken Kontor Ost", "N4: a changed entry with its text")

# an older database: the constraint back to CASCADE, a restart turns it
name = sql("SELECT con.conname FROM pg_constraint con JOIN pg_class t ON t.oid=con.conrelid JOIN pg_attribute a ON a.attrelid=t.oid "
           "AND a.attnum=ANY(con.conkey) WHERE t.relname='office_cash_log' AND con.contype='f' AND a.attname='entry_id'")[0][0]
sql(f'ALTER TABLE office_cash_log DROP CONSTRAINT "{name}"', write=True)
sql("ALTER TABLE office_cash_log ADD CONSTRAINT office_cash_log_entry_old FOREIGN KEY (entry_id) REFERENCES office_cash_entries(id) "
    "ON DELETE CASCADE", write=True)
check([r[0] for r in sql(FK)] == ["c"], "test set-up: CASCADE like 2.121-2.144.10")
start(keep=True)
A = sess("alice")
check([r[0] for r in sql(FK)] == ["n"], f"older database: the start turns entry_id into SET NULL {sql(FK)}")
start(keep=True)
check([r[0] for r in sql(FK)] == ["n"], "a second start changes nothing (one constraint)")
before = sql("SELECT count(*) FROM office_cash_log WHERE entry_id=?", (E2,))[0][0]
check(before >= 2, f"the entry has log lines (create + change): {before}")
sql("DELETE FROM office_cash_entries WHERE id=?", (E2,), write=True)  # no route deletes: a maintenance tool would
left = sql("SELECT count(*) FROM office_cash_log WHERE entry_id IS NULL AND action IN ('create', 'change') AND book_id=?", (BK,))[0][0]
check(left >= before, f"N3: the log lines outlive the removed entry ({left})")

# ---- N4: lists without cipher text, balance over all entries
j = A.get(B + CBS).json()
b = next(x for x in j["books"] if x["id"] == BK)
check(b["balance"] == "110.00" and b["entries"] == 1, f"box list: balance + count {b}")
check("kenc1:" not in json.dumps(j), "box list: no cipher text")
r = post(A, {"day": "2026-01-06", "dir": "out", "amount": "20", "text": "Kaffee Kontor"})
check(r.status_code == 201 and r.json()["text"] == "Kaffee Kontor" and r.json()["balance"] == "90.00", "entry after the restart " + r.text[:200])
E3 = r.json()["id"]
j = A.get(B + f"{CBS}/{BK}/entries?year=2026").json()
check([e["text"] for e in j["entries"]] == ["Kaffee Kontor"] and j["balance"] == "90.00" and "kenc1:" not in json.dumps(j),
      f"entries of 2026: text decrypted, balance over all years {j.get('balance')}")
j = A.get(B + f"{CBS}/{BK}/entries?year=2025").json()
check([e["text"] for e in j["entries"]] == ["Vorjahr Einnahme Nordwind"] and "kenc1:" not in json.dumps(j), "entries of 2025")
r = A.post(B + f"{CE}/{E3}/cancel", json={"day": "2026-01-06"})
check(r.status_code == 201 and r.json()["entry"]["text"] == "Kaffee Kontor" and r.json()["original"]["cancelled_by"] == r.json()["entry"]["id"],
      "N4: cancellation keeps the text " + r.text[:200])
check(post(A, {"day": "2026-01-07", "dir": "out", "amount": "500", "text": "zu viel"}).status_code == 400, "N4: the balance check still counts every entry")
check(A.get(B + f"{CBS}/{BK}/closing?day=2026-01-06").json()["closing"] == "110.00", "N4: closing preview 100 + 10 - 20 + 20")
csv = A.get(B + O + f"/cashbook.csv?book_id={BK}&year=2026").content.decode("utf-8-sig")
check("Kaffee Kontor" in csv and "kenc1:" not in csv, "CSV with the texts")

# ---- N6: the receipt hint behind the office gate
R1 = receipt(A, f"org:{ORG}", "beleg.pdf", "3.00", "2026-01-08")
r = post(A, {"day": "2026-01-08", "dir": "out", "amount": "3", "text": "Beleg Material", "node_id": R1})
check(r.status_code == 201, "entry with a receipt " + r.text[:200])
h = A.get(B + f"/api/docs/{R1}/cashbook")
check(h.ok and [e["no"] for e in h.json()["entries"]] == [r.json()["no"]], f"admin: the receipt hint {h.text[:200]}")
check(requests.get(B + f"/api/docs/{R1}/cashbook", headers=AGH).status_code in (401, 403, 404), "agent: no receipt hint")  # the token layer may refuse first
A.patch(B + "/api/settings", json={"features": "cal,comments,collab,clients,docs"})
check(A.get(B + f"/api/docs/{R1}/cashbook").status_code == 403, "N6: office switched off: receipt hint 403")
A.patch(B + "/api/settings", json={"features": FEAT})
check(A.get(B + f"/api/docs/{R1}/cashbook").ok, "office on again: the hint")
_, Fr = freelancer(B, A, "frieda", FEAT)
FB = Fr.get(B + CBS).json()["books"][0]["id"]
today = Fr.get(B + CBS).json()["today"]
FR = receipt(Fr, "private", "quittung.pdf", "2.00", today)
check(post(Fr, {"dir": "in", "amount": "5", "text": "Barverkauf"}, f"{CBS}/{FB}/entries").status_code == 201, "personal office: income")
r = post(Fr, {"dir": "out", "amount": "2", "text": "Quittung", "node_id": FR}, f"{CBS}/{FB}/entries")
check(r.status_code == 201 and Fr.get(B + f"/api/docs/{FR}/cashbook").json()["entries"][0]["no"] == 2, "personal office: the receipt hint")
check("kenc1:" not in json.dumps(Fr.get(B + CBS).json()) and Fr.get(B + CBS).json()["books"][0]["balance"] == "3.00", "personal office: box list")
check(A.get(B + f"/api/docs/{FR}/cashbook").status_code == 404, "the organisation: no hint on a private receipt")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
