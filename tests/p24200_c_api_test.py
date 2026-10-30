#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.420.0 API tests, part C (#3448): a person ticks receipts as checked (who + when, like DATEV). Invented companies,
people and figures only.
tenant-matrix: office
freelancer-matrix: office
 - POST /api/office/books/receipts/checked: one receipt and several at once, who + when stored, ticking again changes
   nothing (changed = only the receipts whose state changed), untick clears who + when; bad bodies 400
 - the receipts list: fields checked_at / checked_by, the filter checked=yes|no (bad value 400); the receipt sheet shows it
 - exports: receipts.csv (Checked on / Checked by after Paid on), GoBD receipts.csv (Geprueft_am / Geprueft_von after
   Bezahlt_am, every line as wide as index.xml), DATEV booking batch (Zusatzinformation Art 1 "Geprueft" + the day)
 - a locked month: ticking and unticking a receipt there 409, a multiple choice with one of them changes nothing
 - rights: a member 403, an agent token 403 (it only reads the state in GET /api/v1/documents/<id>), another
   organisation 404 and nothing changed; a person without organisation uses it fully (her own agent reads, cannot tick)
usage: p24200_c_api_test.py <datadir>      (P2420C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import csv
import io
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import date

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import check, done, sess  # noqa: E402  shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
RL = O + "/books/receipts"
CK = RL + "/checked"
TODAY = date.today().isoformat()
Y = date.today().year
LY = Y - 1


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
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


def receipt(s, ws, name, amount, day, category="Material", vat="19"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    r = s.patch(B + f"/api/docs/{nid}", json={"date": day, "amount": amount})
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": category, "vat_pct": vat, "project_id": None, "keep": True})
    assert r.ok, r.text
    return nid


def get(s, q=""):
    r = s.get(B + RL + ("?" + q if q else ""))
    assert r.ok, (q, r.status_code, r.text[:300])
    return r.json()


def ids(j):
    return sorted(x["node_id"] for x in j["rows"])


def tick(s, nids, on=True):
    return s.post(B + CK, json={"node_ids": nids, "checked": on})


def state(nid):
    return tuple(dbx("SELECT checked_at, checked_by FROM rc_receipts WHERE node_id=?", (nid,))[0])


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t, "X-Requested-With": "kalmido"})
    return s


if os.environ.get("P2420C_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
uids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
A.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel GmbH"}, "currency": "EUR"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "files:read"], "username": "claude", "display_name": "Claude"}).json()
AG = tok(ag["token"])

WS = f"org:{ORG}"
R1 = receipt(A, WS, "papier.pdf", "119.00", f"{Y}-01-10")
R2 = receipt(A, WS, "toner.pdf", "59.50", f"{Y}-01-11")
R3 = receipt(A, WS, "kabel.pdf", "23.80", f"{Y}-01-12")
R0 = receipt(A, WS, "alt.pdf", "11.90", f"{LY}-01-10")  # last year's January: locked below
R9 = receipt(A, WS, "alt2.pdf", "17.85", f"{LY}-01-20")
ALL = f"from={LY}-01-01&to={TODAY}"

# ---------------------------------------------------------------- nothing checked yet
j = get(A, ALL)
check(ids(j) == sorted([R0, R1, R2, R3, R9]) and all(x["checked_at"] is None and x["checked_by"] is None for x in j["rows"]),
      f"before: every receipt unchecked {[(x['node_id'], x['checked_at']) for x in j['rows']]}")

# ---------------------------------------------------------------- one receipt
r = tick(A, [R1])
check(r.ok and r.json()["changed"] == [R1], "tick one receipt " + r.text[:300])
row = (r.json().get("rows") or [{}])[0]
check(row.get("node_id") == R1 and row.get("checked_by") == "Alice Admin" and str(row.get("checked_at") or "")[:10] == TODAY,
      f"who + when in the answer {row}")
at, by = state(R1)
check(by == ALICE and str(at or "")[:10] == TODAY, f"who + when stored {(at, by)}")
r = tick(A, [R1])
check(r.ok and r.json()["changed"] == [] and state(R1) == (at, by), "ticking again changes nothing (keeps the first who + when)")
sh = A.get(B + f"/api/docs/{R1}/receipt").json()["receipt"]
check(sh.get("checked_at") == at and (sh.get("checked_by") or {}).get("name") == "Alice Admin", f"the receipt sheet shows it {sh}")

# ---------------------------------------------------------------- several at once, the filter
r = tick(A, [R1, R2, R3, R2])
check(r.ok and sorted(r.json()["changed"]) == [R2, R3] and len(r.json()["rows"]) == 3, "multiple choice: only the unchecked ones change " + r.text[:300])
r = tick(A, [R3], False)
check(r.ok and r.json()["changed"] == [R3] and state(R3) == (None, None), "untick: who + when cleared " + r.text[:200])
check(ids(get(A, ALL + "&checked=yes")) == sorted([R1, R2]), "filter checked=yes")
check(ids(get(A, ALL + "&checked=no")) == sorted([R0, R3, R9]), "filter checked=no")
check(ids(get(A, ALL + "&checked=all")) == sorted([R0, R1, R2, R3, R9]), "filter checked=all")
check(A.get(B + RL + "?checked=maybe").status_code == 400, "filter: a wrong value 400")
lr = {x["node_id"]: x for x in get(A, ALL)["rows"]}
check(lr[R2]["checked_by"] == "Alice Admin" and lr[R2]["checked_at"] and lr[R3]["checked_at"] is None, f"list fields {lr[R2]}")

# ---------------------------------------------------------------- bad bodies
for bad in ({}, {"node_ids": [R1]}, {"checked": True}, {"node_ids": [], "checked": True}, {"node_ids": "1", "checked": True},
            {"node_ids": [R1], "checked": "yes"}, {"node_ids": ["x"], "checked": True}, {"node_ids": [True], "checked": True},
            {"node_ids": [-1], "checked": True}, {"node_ids": list(range(1, 502)), "checked": True},
            {"node_ids": [R1], "checked": True, "by": ALICE}):
    check(A.post(B + CK, json=bad).status_code == 400, f"bad body 400: {str(bad)[:80]}")
check(tick(A, [R1, 99999999]).status_code == 404, "an unknown id 404 (all or nothing)")

# ---------------------------------------------------------------- exports
r = A.get(B + RL + ".csv?" + ALL)
t = r.content.decode("utf-8").lstrip("﻿")
delim = ";" if t.split("\r\n", 1)[0].count(";") > t.split("\r\n", 1)[0].count(",") else ","
rows = list(csv.reader(io.StringIO(t), delimiter=delim))
head = rows[0] if rows else []
check(r.ok and head[:4] == ["Receipt date", "Paid on", "Checked on", "Checked by"] and head[-1] == "Kalmido ID", f"CSV: the new columns {head}")
body = {int(x[-1]): dict(zip(head, x)) for x in rows[1:]}
d1 = body.get(R1, {})
check(d1.get("Checked by") == "Alice Admin" and d1.get("Checked on") in (TODAY, f"{TODAY[8:10]}.{TODAY[5:7]}.{TODAY[:4]}")
      and body.get(R3, {}).get("Checked on") == "" and body.get(R3, {}).get("Checked by") == "", f"CSV: values {d1} {body.get(R3)}")
r = A.get(B + RL + ".csv?" + ALL + "&checked=yes")
check(r.ok and sorted(int(x[-1]) for x in list(csv.reader(io.StringIO(r.content.decode("utf-8").lstrip("﻿")), delimiter=delim))[1:]) == sorted([R1, R2]),
      "CSV follows the filter checked=yes")

r = A.get(B + O + f"/gobd/export?from={LY}-01-01&to={TODAY}")
check(r.ok, "GoBD export " + str(r.status_code))
z = zipfile.ZipFile(io.BytesIO(r.content))
tb = {}
for tt in ET.fromstring(z.read("index.xml")).iter("Table"):
    tb[tt.findtext("URL")] = [c.findtext("Name") for c in tt.find("VariableLength") if c.tag in ("VariablePrimaryKey", "VariableColumn")]
cols = tb.get("receipts.csv", [])
check(cols[:5] == ["Beleg_ID", "Belegdatum", "Bezahlt_am", "Geprueft_am", "Geprueft_von"], f"GoBD: Geprueft_am / Geprueft_von after Bezahlt_am {cols}")
grc = list(csv.reader(io.StringIO(z.read("receipts.csv").decode("utf-8"), newline=""), delimiter=";", quotechar='"'))
check(grc and all(len(x) == len(cols) for x in grc), "GoBD: every receipts line as wide as index.xml")
gr = {x[0]: dict(zip(cols, x)) for x in grc}
check(gr.get(str(R1), {}).get("Geprueft_von") == "Alice Admin" and gr.get(str(R1), {}).get("Geprueft_am") == f"{TODAY[8:10]}.{TODAY[5:7]}.{TODAY[:4]}"
      and gr.get(str(R3), {}).get("Geprueft_am") == "", f"GoBD: values {gr.get(str(R1))} {gr.get(str(R3))}")

r = A.put(B + O + "/settings", json={"datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}})
check(r.ok, "DATEV numbers " + r.text[:160])
r = A.get(B + O + f"/datev/extf?from={Y}-01-01&to={TODAY}")
check(r.ok, "DATEV batch " + r.text[:200])
lines = r.content.decode("cp1252").split("\r\n")
hd = [x.strip('"') for x in lines[1].split(";")] if len(lines) > 1 else []
ia, ii, ib = hd.index("Zusatzinformation - Art 1"), hd.index("Zusatzinformation - Inhalt 1"), hd.index("Belegfeld 1")
dl = {x.split(";")[ib].strip('"'): x.split(";") for x in lines[2:] if x}
mark = {k: (v[ia].strip('"'), v[ii].strip('"')) for k, v in dl.items()}
day = f"{TODAY[8:10]}.{TODAY[5:7]}.{TODAY[:4]}"
check(mark.get(f"B{R1}") == ("Geprueft", day) and mark.get(f"B{R2}") == ("Geprueft", day) and mark.get(f"B{R3}") == ("", ""),
      f"DATEV: checked receipts carry Zusatzinformation Geprueft + day {mark}")

# ---------------------------------------------------------------- a locked month
check(tick(A, [R0]).ok, "tick a receipt of last January before the lock")
r = A.post(B + O + "/periods/lock", json={"through": f"{LY}-01", "confirm": f"01/{LY}"})
check(r.ok, "January of last year locked " + r.text[:200])
before = state(R0)
r = tick(A, [R0], False)
check(r.status_code == 409 and state(R0) == before, f"untick in a locked month 409 ({r.status_code})")
r = tick(A, [R9])
check(r.status_code == 409 and state(R9) == (None, None), f"tick in a locked month 409 ({r.status_code})")
r = tick(A, [R3, R9])
check(r.status_code == 409 and state(R3) == (None, None), "multiple choice with a locked receipt: 409, nothing changed")
check(tick(A, [R3]).ok and tick(A, [R3], False).ok, "an open month still ticks")

# ---------------------------------------------------------------- rights
check(tick(Bo, [R3]).status_code == 403 and state(R3) == (None, None), "a member 403")
r = AG.post(B + CK, json={"node_ids": [R3], "checked": True})
check(r.status_code == 403 and state(R3) == (None, None), f"an agent token 403 ({r.status_code})")
r = tick(Ca, [R3])
check(r.status_code == 404 and state(R3) == (None, None), f"another organisation: 404, nothing changed ({r.status_code})")
check(tick(Ca, [R1], False).status_code == 404 and state(R1)[0] is not None, "another organisation cannot untick either")
check(get(Ca, ALL)["rows"] == [], "another organisation sees none of Alpha's receipts")

# ---------------------------------------------------------------- a person without organisation (personal office)
# freelancer-matrix: office
FID, Fr = freelancer(B, A, "frida")
Fr.patch(B + "/api/settings", json={"features": FEAT})
F1 = receipt(Fr, "private", "eigen.pdf", "59.50", f"{Y}-01-15")
F2 = receipt(Fr, "private", "zweit.pdf", "11.90", f"{Y}-01-16")
r = tick(Fr, [F1, F2])
check(r.ok and sorted(r.json()["changed"]) == sorted([F1, F2]) and all(x["checked_by"] == "Frida" for x in r.json()["rows"]),
      "freelancer: ticks her receipts " + r.text[:200])
check(tick(Fr, [F2], False).ok and ids(get(Fr, "checked=yes")) == [F1] and ids(get(Fr, "checked=no")) == [F2], "freelancer: untick + filter")
check(tick(A, [F1], False).status_code == 404 and state(F1)[0] is not None, "Alpha's admin cannot touch the freelancer's receipt")
check(tick(Fr, [R1], False).status_code == 404, "the freelancer cannot touch Alpha's receipt")
fa = A.post(B + "/api/admin/agents", json={"scopes": ["read", "files:read"], "username": "fridabot", "display_name": "Fridabot"}).json()
dbx("DELETE FROM org_members WHERE user_id=?", (fa["id"],), write=True)
dbx("UPDATE agents SET org_id=NULL, owner_id=? WHERE user_id=?", (FID, fa["id"]), write=True)
r = Fr.post(B + f"/api/files/nodes/{F1}/shares", json={"agent_id": fa["id"], "role": "view"})
check(r.ok, "freelancer shares her receipt with her agent " + r.text[:200])
FA = tok(fa["token"])
r = FA.get(V + f"/documents/{F1}")
rc = r.json().get("receipt_checked") if r.ok else None
check(r.ok and isinstance(rc, dict) and rc.get("by") == "Frida" and str(rc.get("at") or "")[:10] == TODAY, f"her agent reads the tick {r.status_code} {rc}")
r = FA.post(B + CK, json={"node_ids": [F1], "checked": False})
check(r.status_code == 403 and state(F1)[0] is not None, f"her agent cannot untick (403, {r.status_code})")

sys.exit(done("p24200_c_api"))
