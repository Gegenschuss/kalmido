#!/usr/bin/env python3
"""2.152.0 API tests, part C (#2168 #2169 #2174): legal retention instead of deleting, own container (start.sh). Invented
people, firms and addresses only (example.com).
tenant-matrix: office
freelancer-matrix: office
 - #2168 travel expenses: a receipt ticked "in DATEV" or billed on a finalised invoice is kept (409 for the receipt and its
   trip); without the tick it goes as before
 - #2168 booked receipts (VAT rate or paid): into the trash yes, deleted for good 409 "Kept by law until 31.12.<year + 8>";
   a receipt without booking and one whose period ran out are purged
 - #2168 the undo of an old-invoice import: within 24 hours and untouched only (409 after an edit, 409 after 24 hours)
 - #2168 a payment on a finalised invoice is reversed (a second line with the negative amount, reverses_id), never deleted;
   the balance follows, a second reversal / the reversal of a reversal 409
 - #2168 a client used by an invoice is archived instead of deleted (the answer says so); an unused one goes
 - #2169 logbook: a drive a week old is closed (PATCH / DELETE 409), the fix is a new entry with a reason (400 without),
   the old one stays visible ("corrected by"), leaves the sums, the change log has both, the CSV has the fixed columns;
   "Close month" (future and, 2.186.0 #2601, the running month 400, member 403, twice fine) closes a month: new drives there 409, changes there 409
 - #2169 the same in the personal office of a person without an organisation (freelancer_fixture)
 - #2174 foreign keys: an orphan (a key dropped, a reference to a row that is gone) is cleaned by fk_ensure (task_id ->
   NULL, a habit of a gone person deleted), the key comes back under fk2103_*, the count lands in fk2103_orphans; deleting
   the task empties the reference; the schema rule: every new *_id column has REFERENCES or "no FK"
usage: p2103_c_api_test.py <datadir>      (P2103C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs,files,habits"
O = "/api/office"
D, T, V, DR, LB = O + "/docs", O + "/trips", O + "/vehicles", O + "/drives", O + "/logbook"
TODAY = testclock.today()
DAY = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


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


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def in_app(code):
    """Runs python code inside the server container (the app loaded, c = a connection); -> stdout + stderr."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.close()"],
                         capture_output=True, text=True)
    return out.stdout + out.stderr


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


def invoice(s, client, rate):
    r = s.post(B + D, json={"kind": "invoice", "client_id": client, "service_from": DAY(30), "items": [{"title": "Schnitt", "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    return did


if os.environ.get("P2103C_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
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
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
A.put(B + O + "/settings", json={"company_fields": {"name": "Beispiel Film GmbH", **COMPANY}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Kundenweg 2", "zip": "20095", "city": "Hamburg", "country": "DE"}).json()["id"]

# ---------------------------------------------------------------- #2168 travel receipts
r = A.post(B + T, json={"date_from": DAY(20), "dest": "Hamburg - Berlin", "purpose": "job", "client_id": CL,
                        "items": [{"date": DAY(20), "category": "train", "amount": "80.00", "datev": 1},
                                  {"date": DAY(20), "category": "hotel", "amount": "120.00"},
                                  {"date": DAY(20), "category": "taxi", "amount": "20.00"}]})
check(r.status_code == 201, "#2168: a trip with three receipts " + r.text[:200])
TR = r.json()
I_DATEV, I_BILL, I_FREE = [x["id"] for x in TR["items"]]
r = A.delete(B + f"{T}/{TR['id']}/items/{I_DATEV}")
check(r.status_code == 409 and "DATEV" in r.json().get("error", r.text), "#2168: a receipt in DATEV is kept (409) " + r.text[:160])
check(A.delete(B + f"{T}/{TR['id']}").status_code == 409, "#2168: its trip is kept too (409)")
INV = invoice(A, CL, 500)
sql("UPDATE office_trip_items SET billed_doc_id=?, billed_at=? WHERE id=?", (INV, DAY(1), I_BILL), write=True)  # billed on the finalised invoice
r = A.delete(B + f"{T}/{TR['id']}/items/{I_BILL}")
check(r.status_code == 409 and "finalised" in r.text, "#2168: a receipt billed on a finalised invoice is kept (409) " + r.text[:160])
check(A.delete(B + f"{T}/{TR['id']}/items/{I_FREE}").ok, "#2168: an unbooked receipt is deleted as before")
# 2.152.0 (#2168, review B-M1): the tick of a locked receipt cannot be taken back (was: PATCH datev 0 unlocked it)
r = A.patch(B + f"{T}/{TR['id']}/items/{I_DATEV}", json={"datev": 0})
check(r.status_code == 409 and "DATEV" in r.text, "#2168 B-M1: the DATEV tick of a locked receipt stays (409) " + r.text[:160])
check(A.patch(B + f"{T}/{TR['id']}/items/{I_DATEV}", json={"amount": "81.00"}).status_code == 409, "#2168 B-M1: its amount stays (409)")
check(A.patch(B + f"{T}/{TR['id']}/items/{I_BILL}", json={"date": DAY(19)}).status_code == 409, "#2168 B-M1: the date of a billed receipt stays (409)")
r = A.patch(B + f"{T}/{TR['id']}/items/{I_DATEV}", json={"text": "Bahn Hamburg", "datev": 1, "amount": "80.00"})
check(r.ok, "#2168 B-M1: the text of a locked receipt can change, unchanged locked values pass " + r.text[:160])
check(A.delete(B + f"{T}/{TR['id']}").status_code == 409, "#2168: the billed receipt still keeps the trip")
# 2.152.0 (#2168, review B-H1): the undo of a VMA import (several trips at once) keeps a trip with a receipt in DATEV
TR2 = A.post(B + T, json={"date_from": DAY(15), "dest": "Berlin", "purpose": "job",
                          "items": [{"date": DAY(15), "category": "train", "amount": "40.00", "datev": 1}]}).json()["id"]
TR3 = A.post(B + T, json={"date_from": DAY(14), "dest": "Bremen", "purpose": "job",
                          "items": [{"date": DAY(14), "category": "train", "amount": "30.00"}]}).json()["id"]
r = A.post(B + T + "/delete", json={"ids": [TR2, TR3]})
check(r.ok and r.json()["deleted"] == 1 and r.json()["skipped"] == [TR2] and sql("SELECT 1 FROM office_trips WHERE id=?", (TR2,))
      and not sql("SELECT 1 FROM office_trips WHERE id=?", (TR3,)), "#2168 B-H1: the multi delete skips the trip in DATEV " + r.text[:200])

# ---------------------------------------------------------------- #2168 booked receipts in the document store
WSO = f"org:{ORG}"


def receipt(name, vat=None, day=None):
    r = A.post(B + "/api/docs", data={"ws": WSO}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    r = A.patch(B + f"/api/docs/{nid}", json={"amount": "119.00", "date": day or DAY(5)})
    assert r.ok, r.text
    r = A.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def purge(nid):
    assert A.delete(B + f"/api/files/nodes/{nid}").ok
    return A.delete(B + f"/api/files/nodes/{nid}?purge=1")


R_BOOKED = receipt("software.pdf", "19")
R_OPEN = receipt("kasse.pdf", None)
R_OLD = receipt("alt.pdf", "7", "2015-03-01")
paths = [p for (p,) in sql("SELECT path FROM fs_versions WHERE node_id=?", (R_OPEN,))]
r = purge(R_BOOKED)
until = f"31 Dec {int(DAY(5)[:4]) + 8}"  # English (the person's language): "31 Dec <year>"
check(r.status_code == 409 and "Kept by law until" in r.text and until in r.text, f"#2168: a booked receipt goes into the trash, deleted for good 409 until {until} " + r.text[:200])
check(sql("SELECT 1 FROM fs_nodes WHERE id=?", (R_BOOKED,)) and sql("SELECT 1 FROM rc_receipts WHERE node_id=?", (R_BOOKED,)), "#2168: the booked receipt and its booking stay")
check(A.post(B + f"/api/files/nodes/{R_BOOKED}/restore").ok, "#2168: the booked receipt comes back from the trash")
check(purge(R_OPEN).ok and not sql("SELECT 1 FROM fs_nodes WHERE id=?", (R_OPEN,)), "#2168: a receipt without VAT rate / payment is deleted for good")
check(paths and not any(os.path.exists(os.path.join(DATA, "attachments", p)) for p in paths), "#2168: ... with its file")
check(purge(R_OLD).ok, "#2168: a booked receipt of 2015 (period over at the end of 2023) is deleted for good")
out = in_app(f"from kalmido.core.pg import system_ctx\nfrom kalmido.receipts.suggest import olk_fs_locked\n"
             f"with system_ctx(c):\n    print('until', olk_fs_locked(c, {R_BOOKED}))")  # like the trash run: across the organisations
check(f"until {int(DAY(5)[:4]) + 8}-12-31" in out, "#2168: olk_fs_locked answers the last day for the trash run " + out[-300:])

# ---------------------------------------------------------------- #2168 the undo of an old-invoice import


def arch_run(n):
    rid = A.post(B + O + "/legacy/archive/run").json()["run_id"]
    r = A.post(B + O + "/legacy/archive", data={"run_id": rid, "kind": "invoice", "number": f"ALT-{n}", "client_name": "Altkunde",
                                                "date": "2024-05-02", "amount": "100.00"},
               files={"file": (f"alt-{n}.pdf", tiny_pdf(f"Rechnung ALT-{n}"), "application/pdf")})
    assert r.status_code == 201, r.text
    return rid, r.json()["id"]


rid, _ = arch_run(1)
check(A.post(B + O + f"/legacy/runs/{rid}/undo").ok, "#2168: an old-invoice import is undone right after it")
rid, aid = arch_run(2)
check(A.patch(B + O + f"/legacy/archive/{aid}", json={"paid": 1}).ok, "an old invoice marked paid")
r = A.post(B + O + f"/legacy/runs/{rid}/undo")
check(r.status_code == 409 and "edited or marked as paid" in r.text and sql("SELECT 1 FROM office_archive WHERE id=?", (aid,)),
      "#2168: after an edit the undo is refused (409), the entry stays " + r.text[:160])
rid, aid = arch_run(3)
sql("UPDATE office_import_runs SET created_at=? WHERE id=?", ((testclock.now() - timedelta(hours=25)).isoformat(timespec="seconds"), rid), write=True)
r = A.post(B + O + f"/legacy/runs/{rid}/undo")
check(r.status_code == 409 and "24 hours" in r.text, "#2168: after 24 hours the undo is refused (409) " + r.text[:160])

# ---------------------------------------------------------------- #2168 payments: a reversal, never a delete
INV2 = invoice(A, CL, 300)
r = A.post(B + f"{D}/{INV2}/payments", json={"date": DAY(2), "amount": "100.00", "method": "transfer"})
check(r.status_code == 201 and r.json()["state"] == "partial", "a part payment " + r.text[:160])
P1 = r.json()["payments"][0]["id"]
check(Bo.delete(B + f"{D}/{INV2}/payments/{P1}", json={"note": "x"}).status_code in (403, 404), "a member cannot reverse a payment")
r = A.delete(B + f"{D}/{INV2}/payments/{P1}", json={"note": "Falsche Rechnung"})
ps = r.json().get("payments") or []
check(r.ok and len(ps) == 2 and ps[0]["id"] == P1 and ps[0]["reversed"] and ps[1]["reverses_id"] == P1 and ps[1]["amount"] == "-100.00"
      and ps[1]["note"] == "Falsche Rechnung" and r.json()["paid"] == "0.00" and r.json()["state"] != "partial",
      f"#2168: the payment stays, a reversal line with -100.00 and the reason, the balance 0 {ps} " + r.text[:200])
check(sql("SELECT COUNT(*) FROM office_payments WHERE doc_id=?", (INV2,))[0][0] == 2, "#2168: both rows in the database")
check(A.delete(B + f"{D}/{INV2}/payments/{P1}").status_code == 409, "#2168: a second reversal 409")
check(A.delete(B + f"{D}/{INV2}/payments/{ps[1]['id']}").status_code == 409, "#2168: the reversal of a reversal 409")
r = A.post(B + f"{D}/{INV2}/payments", json={"date": DAY(1), "amount": A.get(B + f"{D}/{INV2}").json()["open"]})
check(r.status_code == 201 and r.json()["state"] == "paid", "after the reversal the full amount can be paid " + r.text[:160])

# ---------------------------------------------------------------- #2168 clients: in use = archived
r = A.delete(B + f"/api/clients/{CL}")
check(r.ok and r.json().get("archived") is True and "archived instead" in r.json().get("message", "") and sql("SELECT archived FROM clients WHERE id=?", (CL,)) == [(1,)],
      "#2168: a client with invoices is archived instead of deleted " + r.text[:200])
CL2 = A.post(B + "/api/clients", json={"name": "Kunde Zwei GmbH"}).json()["id"]
r = A.delete(B + f"/api/clients/{CL2}")
check(r.ok and not r.json().get("archived") and not sql("SELECT 1 FROM clients WHERE id=?", (CL2,)), "#2168: an unused client is deleted")

# ---------------------------------------------------------------- #2169 logbook


def logbook(s, who):
    """The closing rules of the logbook for session s (an office admin); who = the label in the messages."""
    vid = s.post(B + V, json={"name": "Kombi", "kind": "private", "odo_start": "1000"}).json()["id"]
    d_new = s.post(B + DR, json={"vehicle_id": vid, "day": DAY(1), "dest": "Kunde", "purpose": "Dreh", "km": 30, "kind": "business"}).json()
    check(s.patch(B + f"{DR}/{d_new['id']}", json={"purpose": "Dreh Tag 1"}).ok and d_new["locked"] is None, f"{who}: a fresh drive can be changed")
    r = s.post(B + DR, json={"vehicle_id": vid, "day": DAY(10), "dest": "Lager", "purpose": "Material", "km": 40, "kind": "business"})
    old = r.json()["id"]
    sql("UPDATE office_drives SET created_at=? WHERE id=?", ((testclock.now() - timedelta(days=10)).isoformat(timespec="seconds"), old), write=True)
    j = {d["id"]: d for d in s.get(B + DR + f"?vehicle_id={vid}&year={DAY(10)[:4]}").json()["drives"]}
    check(j[old]["locked"] == "auto", f"{who}: a drive older than a week is closed {j[old].get('locked')}")
    r = s.patch(B + f"{DR}/{old}", json={"km": 45})
    check(r.status_code == 409 and "new entry" in r.text, f"{who}: PATCH of a closed drive 409 " + r.text[:160])
    check(s.delete(B + f"{DR}/{old}").status_code == 409, f"{who}: DELETE of a closed drive 409")
    base = {"vehicle_id": vid, "day": DAY(10), "dest": "Lager Nord", "purpose": "Material", "km": 45, "kind": "business"}
    check(s.post(B + DR, json=dict(base, corrects_id=old)).status_code == 400, f"{who}: a correction without reason 400")
    r = s.post(B + DR, json=dict(base, corrects_id=old, correct_note="Falsches Ziel"))
    check(r.status_code == 201 and r.json()["corrects_id"] == old and r.json()["correct_note"] == "Falsches Ziel", f"{who}: the correction with its reason " + r.text[:200])
    fix = r.json()["id"]
    check(s.post(B + DR, json=dict(base, corrects_id=old, correct_note="noch mal")).status_code == 409, f"{who}: a second correction of the same drive 409")
    j = {d["id"]: d for d in s.get(B + DR + f"?vehicle_id={vid}&year={DAY(10)[:4]}").json()["drives"]}
    check(old in j and j[old]["corrected_by"] == fix and j[old]["km"] == "40.0", f"{who}: the old drive stays visible, marked corrected by the new one")
    log = s.get(B + f"{DR}/{old}/log").json()["log"]
    check([x["action"] for x in log] == ["create", "corrected"] and log[1]["prev"].get("by") == fix and log[1]["prev"].get("note") == "Falsches Ziel",
          f"{who}: the change log of the old drive has the correction {log}")
    rep = s.get(B + LB + f"/report?year={DAY(10)[:4]}&vehicle_id={vid}").json()["vehicles"]
    if DAY(1)[:4] == DAY(10)[:4]:
        check(rep and rep[0]["km_business"] == "75.0", f"{who}: the sums count the correction, not the corrected drive {rep}")
    r = s.get(B + LB + f".csv?year={DAY(10)[:4]}&vehicle_id={vid}")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    head = rows[0]
    by = {x[13]: x for x in rows[1:] if len(x) > 17 and x[13].isdigit()}
    check(head[13:18] == ["ID", "Corrects", "Corrected by", "Reason", "Closed"] and by.get(str(old), [""] * 18)[15] == str(fix)
          and by.get(str(fix), [""] * 18)[14] == str(old) and by[str(fix)][16] == "Falsches Ziel" and by[str(old)][17] == "1",
          f"{who}: the CSV has the fixed columns with the correction link {head} {by.get(str(old))} {by.get(str(fix))}")
    check(any(len(x) > 5 and x[2] == "Corrected" and x[5] == str(old) for x in rows), f"{who}: the CSV change log names the correction")
    check(s.get(B + LB + f".pdf?year={DAY(10)[:4]}").content[:5] == b"%PDF-", f"{who}: the PDF with the corrections")
    # close the previous month (2.186.0 B (#2601): the running month can no longer be closed, see below)
    pday = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=10).isoformat()
    m = pday[:7]
    nxt = (TODAY.replace(day=1) + timedelta(days=32)).isoformat()[:7]
    check(s.post(B + LB + "/close", json={"month": nxt}).status_code == 400 and s.post(B + LB + "/close", json={"month": "2026-13"}).status_code == 400,
          f"{who}: a future / wrong month 400")
    r = s.post(B + LB + "/close", json={"month": TODAY.isoformat()[:7], "vehicle_id": vid})
    check(r.status_code == 400 and "Only past months" in r.text, f"{who} 2.186.0 (#2601): the running month 400 " + r.text[:160])
    fresh = s.post(B + DR, json={"vehicle_id": vid, "day": pday, "dest": "Studio", "km": 5}).json()["id"]
    gone = s.post(B + DR, json={"vehicle_id": vid, "day": pday, "dest": "Probe", "km": 3}).json()["id"]
    check(s.delete(B + f"{DR}/{gone}").ok, f"{who}: an open drive is deleted before its month is closed")
    r = s.post(B + LB + "/close", json={"month": m, "vehicle_id": vid})
    check(r.ok and {"vehicle_id": vid, "month": m} in r.json()["closed"], f"{who}: the month is closed " + r.text[:160])
    check(s.post(B + LB + "/close", json={"month": m, "vehicle_id": vid}).ok, f"{who}: closing twice is fine")
    r = s.patch(B + f"{DR}/{fresh}", json={"km": 6})
    check(r.status_code == 409 and "month is closed" in r.text, f"{who}: a drive of a closed month cannot be changed " + r.text[:160])
    check(s.post(B + DR, json={"vehicle_id": vid, "day": pday, "dest": "x", "km": 1}).status_code == 409, f"{who}: no new drive in a closed month")
    r = s.post(B + DR, json={"vehicle_id": vid, "day": pday, "dest": "Studio", "km": 6, "corrects_id": fresh, "correct_note": "Tippfehler"})
    check(r.status_code == 201, f"{who}: a correction in a closed month is possible " + r.text[:160])
    check(s.get(B + DR + f"?vehicle_id={vid}").json()["closed"], f"{who}: the drives answer lists the closed months")
    # 2.152.0 (#2169, review B-M8): a deleted drive does not come back into a closed month
    r = s.post(B + f"{DR}/{gone}/restore")
    check(r.status_code == 409 and "month is closed" in r.text, f"{who} B-M8: no restore into a closed month (409) " + r.text[:160])
    # a deleted drive stays until the legal period ends
    tmp = s.post(B + DR, json={"vehicle_id": vid, "day": DAY(70), "dest": "Weg", "km": 2}).json()["id"]  # before the closed month (2.186.0 (#2601): was DAY(40))
    check(s.delete(B + f"{DR}/{tmp}").ok and s.post(B + f"{DR}/{tmp}/restore").ok and s.delete(B + f"{DR}/{tmp}").ok,
          f"{who}: delete + restore while the drive is open")
    sql("UPDATE office_drives SET created_at=? WHERE id=?", ((testclock.now() - timedelta(days=10)).isoformat(timespec="seconds"), tmp), write=True)
    r = s.post(B + f"{DR}/{tmp}/restore")
    check(r.status_code == 409 and "a week after" in r.text, f"{who} B-M8: no restore after the week (409) " + r.text[:160])
    out = in_app(f"from kalmido.core.pg import system_ctx\nfrom kalmido.office.logbook import lbc_purge_ok\nwith system_ctx(c):\n"
                 f"    r = dict(c.execute('SELECT * FROM office_drives WHERE id=?', ({tmp},)).fetchone())\n"
                 f"    print('purge', lbc_purge_ok(c, r), lbc_purge_ok(c, dict(r, day='2010-05-01')))")
    check("purge False True" in out, f"{who}: lbc_purge_ok keeps a drive for 8 years after its year " + out[-300:])
    return vid


VID = logbook(A, "office")
# 2.152.0 (#2169, review B-L1): a corrected odometer typo no longer seeds the next drive
V2 = A.post(B + V, json={"name": "Transporter", "kind": "company", "odo_start": "1000"}).json()["id"]
TYPO = A.post(B + DR, json={"vehicle_id": V2, "day": DAY(10), "dest": "Lager", "odo_start": "1000", "odo_end": "10050"}).json()["id"]
sql("UPDATE office_drives SET created_at=? WHERE id=?", ((testclock.now() - timedelta(days=10)).isoformat(timespec="seconds"), TYPO), write=True)
r = A.post(B + DR, json={"vehicle_id": V2, "day": DAY(10), "dest": "Lager", "odo_start": "1000", "odo_end": "1050",
                         "corrects_id": TYPO, "correct_note": "Tippfehler Tacho"})
lo = {v["id"]: v["last_odo"] for v in A.get(B + V).json()["vehicles"]}.get(V2)
check(r.status_code == 201 and lo == "1050.0", f"#2169 B-L1: the next drive starts at the corrected odometer {lo} " + r.text[:160])
check(Bo.post(B + LB + "/close", json={"month": DAY(40)[:7]}).status_code == 403, "a member cannot close a month (403)")  # 2.186.0 (#2601): a past month
FID, Fr = freelancer(B, A)
logbook(Fr, "freelancer")
check(Fr.patch(B + f"{DR}/{sql('SELECT id FROM office_drives WHERE vehicle_id=? ORDER BY id LIMIT 1', (VID,))[0][0]}", json={"km": 1}).status_code == 404,
      "the freelancer never reaches a drive of the organisation (404)")
check(sql("SELECT correct_note FROM office_drives WHERE correct_note<>'' LIMIT 1")[0][0].startswith("kenc1:"), "#2169: the reason is encrypted at rest")

# ---------------------------------------------------------------- #2174 foreign keys


def fk_name(table, col):
    rows = sql("""SELECT con.conname FROM pg_constraint con JOIN pg_class cl ON cl.oid=con.conrelid
                  JOIN pg_attribute a ON a.attrelid=con.conrelid AND a.attnum=con.conkey[1]
                  WHERE con.contype='f' AND cl.relname=? AND a.attname=?""", (table, col))
    return rows[0][0] if rows else None


check(all(fk_name(t, c_) for t, c_ in (("doc_meta", "task_id"), ("rc_receipts", "list_id"), ("notes", "created_by"), ("agents", "owner_id"),
                                       ("habits", "user_id"), ("budget_recurring", "contract_task_id"))),
      "#2174: a new database has the keys")
# 2.152.0 (#2174, review B-M7): playbooks.author_id keeps the id of a gone author (no key; NULL would mean the owner's text)
check(fk_name("playbooks", "author_id") is None, "#2174 B-M7: playbooks.author_id has no foreign key")
INBOX = sql("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (ALICE,))[0][0]
TK = A.post(B + "/api/tasks", json={"title": "Beleg prüfen", "list_id": INBOX}).json()["id"]
sql(f"ALTER TABLE doc_meta DROP CONSTRAINT {fk_name('doc_meta', 'task_id')}", write=True)
sql(f"ALTER TABLE habits DROP CONSTRAINT {fk_name('habits', 'user_id')}", write=True)
sql("UPDATE doc_meta SET task_id=999999 WHERE node_id=?", (R_BOOKED,), write=True)  # an orphan: the task is gone
HB = A.post(B + "/api/habits", json={"name": "Lesen"})
if HB.ok:
    sql("UPDATE habits SET user_id=999999 WHERE id=?", (HB.json()["id"],), write=True)
# 2.152.0 (#2174, review B-M6): an agent whose owner is gone is paused by the admin, not turned into a running team agent
check(A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "fkbot", "display_name": "Fk Bot"}).ok, "an agent for the orphan check")
AGU = sql("SELECT a.user_id FROM agents a JOIN users u ON u.id=a.user_id WHERE u.username='fkbot'")[0][0]
sql(f"ALTER TABLE agents DROP CONSTRAINT {fk_name('agents', 'owner_id')}", write=True)
sql("UPDATE agents SET owner_id=999999, admin_paused=0, office_drafts=1 WHERE user_id=?", (AGU,), write=True)
FK_RUN = ("from kalmido.core.db import DATABASE_URL\nfrom kalmido.core.pg import connect_direct\nfrom kalmido.core.fkeys import fk_ensure\n"
          "o = connect_direct(DATABASE_URL)\nprint('done', sorted(fk_ensure(o).items()))\no.commit()\no.close()")  # the login role, like init_db
out = in_app(FK_RUN)
# loading the app runs init_db, which runs fk_ensure (the start path); the call after it then finds nothing to do
check(("('doc_meta.task_id', 1)" in out or "doc_meta.task_id=1" in out) and (not HB.ok or "('habits.user_id', 1)" in out or "habits.user_id=1" in out),
      "#2174: fk_ensure (at the start) cleans the orphans and adds the keys " + out[-400:])
check(sql("SELECT task_id FROM doc_meta WHERE node_id=?", (R_BOOKED,)) == [(None,)], "#2174: the orphaned task reference is emptied")
check(not HB.ok or not sql("SELECT 1 FROM habits WHERE id=?", (HB.json()["id"],)), "#2174: the habit of a gone person is deleted (CASCADE)")
check(sql("SELECT owner_id, admin_paused, office_drafts FROM agents WHERE user_id=?", (AGU,)) == [(None, 1, 0)],
      "#2174 B-M6: the orphaned agent is paused by the admin, without office drafts")
check(fk_name("doc_meta", "task_id") == "fk2103_doc_meta_task_id" and fk_name("habits", "user_id") == "fk2103_habits_user_id", "#2174: the keys are back")
g = sql("SELECT value FROM settings WHERE key='fk2103_orphans'")
check(g and json.loads(g[0][0]).get("doc_meta.task_id") == 1, f"#2174: the counts in fk2103_orphans {g}")
check("done []" in in_app(FK_RUN), "#2174: a second run does nothing")
sql("UPDATE doc_meta SET task_id=? WHERE node_id=?", (TK, R_BOOKED), write=True)
sql("DELETE FROM tasks WHERE id=?", (TK,), write=True)
check(sql("SELECT task_id FROM doc_meta WHERE node_id=?", (R_BOOKED,)) == [(None,)], "#2174: deleting the task empties the reference (ON DELETE SET NULL)")
try:
    sql("UPDATE doc_meta SET task_id=999998 WHERE node_id=?", (R_BOOKED,), write=True)
    check(False, "#2174: a reference to a task that does not exist is refused")
except Exception:  # noqa: BLE001 -- the foreign key violation
    check(True, "")

# the schema rule: every *_id column of schema.py has a key or the marker "no FK" (the columns of 2.102 are the frozen
# list p2103_c_fk_legacy.txt: it may only shrink)
SCHEMA_PY = os.path.join(N, "..", "kalmido", "core", "schema.py")
if os.path.exists(SCHEMA_PY):
    src = open(SCHEMA_PY, encoding="utf-8").read()
    legacy = {ln.strip() for ln in open(os.path.join(N, "p2103_c_fk_legacy.txt"), encoding="utf-8") if ln.strip() and not ln.startswith("#")}
    sch = re.search(r'SCHEMA = """(.*?)"""', src, re.S).group(1)
    bad = []
    for t in re.finditer(r"((?:--[^\n]*\n)*)CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", sch, re.S):
        if "no FK" in t.group(1):
            continue
        for line in t.group(3).split("\n"):
            for col in re.findall(r"(\w+_id) BIGINT(?! GENERATED)([^,]*)", line):
                if "REFERENCES" not in col[1] and "PRIMARY KEY" not in col[1] and "no FK" not in line and f"{t.group(2)}.{col[0]}" not in legacy:
                    bad.append(f"{t.group(2)}.{col[0]}")
    for line in src.split("\n"):
        m = re.match(r'\s*\("(\w+)", "(\w+_id)", "ALTER TABLE \w+ ADD COLUMN \w+ BIGINT([^"]*)"\)', line)
        if m and "REFERENCES" not in m.group(3) and "no FK" not in line and f"{m.group(1)}.{m.group(2)}" not in legacy:
            bad.append(f"{m.group(1)}.{m.group(2)}")
    check(not bad, f"#2174: every new *_id column has REFERENCES or a 'no FK' comment: {bad}")

print(f"p2103_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
