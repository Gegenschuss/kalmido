#!/usr/bin/env python3
"""2.148.1 API tests, part D (#2485 #2488 #2489 #2495): resource limits, filed mail files, assistant lists, agent actions.
Invented people only (example.com).
freelancer-matrix: personal
 - #2485 an .xlsx with a huge table range is answered quickly (columns capped), an encrypted .xlsx is a 400 (not a 500);
   a table holds a capped number of stored cells (400 "The table is full"), range formulas share a budget per evaluation
   (an error value instead of minutes of work); a sheet import of a sparse file works
 - #2488 a file filed with a hub mail follows the mail's rule: the folder's owner / an organisation admin without the
   mail's rights gets 404 for it and does not see it in the listing; the mail's recipient does
 - #2489 assistant: only own lists can be shared (someone else's list 403); a person without an organisation shares hers
 - #2495 agents: deleting / restoring an invited event through an agent mails nothing (a person's delete does);
   a public form and deleting an address book wait for approval (202); an internal form of a person without an
   organisation is private; a form of a list in the trash takes nothing in; the assignee alone cannot decide a deploy
   request
usage: p21481_d_api_test.py <datadir>      (P21481D_NOSTART=1: a running server started with the same EXTRA, no start.sh)"""
# tenant-matrix: personal
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import date, timedelta

import requests

import dbx as dbxm
from freelancer_fixture import FEATURES, freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]
NOSTART = os.environ.get("P21481D_NOSTART") == "1"
FEAT = FEATURES + ",sheets"
ENV = (" -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test"
       " -e KALMIDO_SHEET_RANGE_BUDGET=50 -e KALMIDO_SHEET_CELLS_MAX=25"
       " -e KALMIDO_AI_BASE_URL=http://127.0.0.1:8089/v1 -e KALMIDO_AI_MODEL=fake-1 -e KALMIDO_AI_KEY=test-key -e KALMIDO_AI_NAME=Fake-AI")


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)
        if len(FAILS) == 1:
            print(subprocess.run(["docker", "logs", "--tail", "60", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True).stdout[-6000:], flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        cur = c.execute(sql, args)
        rows = cur.fetchall() if sql.lstrip().upper().startswith("SELECT") or "RETURNING" in sql.upper() else []
        c.commit()
        return rows
    finally:
        c.close()


def mails(to=None):
    try:
        out = [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []
    return [m for m in out if not to or to in json.dumps(m["to"])]


def wait_mail(to, n, secs=8):
    for _ in range(secs * 5):
        if len(mails(to)) >= n:
            break
        time.sleep(0.2)
    return mails(to)


def xlsx(parts):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)
    return b.getvalue()


NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
RELNS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'


def book(ref, cells='<row r="1"><c r="A1" t="inlineStr"><is><t>Name</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>Acme</t></is></c></row>'):
    """A workbook with one sheet "Kontakte" and a table over ref."""
    return xlsx({
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "xl/workbook.xml": f'<?xml version="1.0"?><workbook {NS}><sheets><sheet name="Kontakte" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<?xml version="1.0"?><Relationships {RELNS}><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0"?><worksheet {NS}><sheetData>{cells}</sheetData></worksheet>',
        "xl/worksheets/_rels/sheet1.xml.rels": f'<?xml version="1.0"?><Relationships {RELNS}><Relationship Id="rId1" Type="table" Target="../tables/table1.xml"/></Relationships>',
        "xl/tables/table1.xml": f'<?xml version="1.0"?><table {NS} id="1" name="Kunden" displayName="Kunden" ref="{ref}"/>',
    })


def encrypted(raw):
    """The same archive with the 'encrypted' flag set on every entry (local header + central directory)."""
    b = bytearray(raw)
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = b.find(sig)
        while i >= 0:
            b[i + off] |= 1
            i = b.find(sig, i + 4)
    return bytes(b)


# ---------------------------------------------------------------- start
if not NOSTART:
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + ENV),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
if not dbx("SELECT email FROM users WHERE id=?", (ALICE,))[0][0]:
    dbx("UPDATE users SET email='alice@example.com' WHERE id=?", (ALICE,))
FID, Fr = freelancer(B, A, features=FEAT)  # freelancer-matrix: personal
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure", "calendar", "contacts", "delete"],
                                          "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
dbx("INSERT INTO user_settings(user_id,key,value) VALUES(?,'features',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
    (AG, FEAT))  # the agent's own module switches: events, contacts on

# ================================================================== #2485 limits
# legacy import: a table range far beyond the columns is capped (fast answer), an encrypted file is a 400
t0 = time.time()
r = Fr.post(B + "/api/office/legacy/preview", files={"file": ("old.xlsx", book("A1:ZZZZZ2000"), "application/octet-stream")})
check(r.status_code in (200, 400) and time.time() - t0 < 20, f"a huge table range: quick answer {r.status_code} {time.time() - t0:.1f}s {r.text[:160]}")
r = Fr.post(B + "/api/office/legacy/preview", files={"file": ("old.xlsx", encrypted(book("A1:A2")), "application/octet-stream")})
check(r.status_code == 400, f"an encrypted .xlsx: 400 {r.status_code} {r.text[:160]}")
r = Fr.post(B + "/api/office/legacy/preview", files={"file": ("old.xlsx", book("A1:A2"), "application/octet-stream")})
check(r.ok, f"a normal file still reads {r.status_code} {r.text[:160]}")
# 2.148.1 G (#2496): a part in a two-byte encoding is refused (legacy import and table import)
z16 = zipfile.ZipFile(io.BytesIO(book("A1:A2")))
w16 = {n: z16.read(n) for n in z16.namelist()}
w16["xl/workbook.xml"] = w16["xl/workbook.xml"].decode().replace('<?xml version="1.0"?>', '<?xml version="1.0" encoding="UTF-16"?>').encode("utf-16")
w16 = xlsx(w16)
r = Fr.post(B + "/api/office/legacy/preview", files={"file": ("old.xlsx", w16, "application/octet-stream")})
check(r.status_code == 400, f"legacy import: a two-byte encoded part 400 {r.status_code} {r.text[:160]}")
r = Fr.post(B + "/api/sheets/import", files={"file": ("w16.xlsx", w16, "application/octet-stream")}, data={"space": "private"})
check(r.status_code == 400, f"table import: a two-byte encoded part 400 {r.status_code} {r.text[:160]}")

# sheets (the test server: range budget 50 cells, at most 25 stored cells per table)
r = Fr.post(B + "/api/sheets", json={"title": "Budget", "space": "private"})
check(r.status_code == 201, "the freelancer makes a table " + r.text[:160])
SH = r.json()["id"]


def put(s, cells):
    return s.put(B + f"/api/sheets/{SH}/cells", json={"cells": [{"cell": a, "raw": v} for a, v in cells]})


r = put(Fr, [(f"A{i}", str(i)) for i in range(1, 11)])
check(r.ok, "ten numbers " + r.text[:160])
r = put(Fr, [("B1", "=SUM(A1:A10)")])
check(r.ok, "one sum " + r.text[:160])
cells = {x["addr"]: x for x in Fr.get(B + f"/api/sheets/{SH}").json()["cells"]}
check(cells.get("B1", {}).get("value") == 55 and not cells["B1"].get("error"), f"a sum within the budget: 55 {cells.get('B1')}")
r = put(Fr, [(f"B{i}", "=SUM(A1:A10)") for i in range(2, 11)])
check(r.ok, "nine more sums " + r.text[:160])
# 2.148.1 G (#2485): the same range in every row counts once per evaluation
cells = {x["addr"]: x for x in Fr.get(B + f"/api/sheets/{SH}").json()["cells"]}
check(all(cells.get(f"B{i}", {}).get("value") == 55 for i in range(1, 11)), f"the same range in ten rows fits the budget {[cells.get(f'B{i}', {}).get('value') for i in range(1, 11)]}")
r = put(Fr, [(f"B{i}", f"=SUM(A1:A{i})") for i in range(2, 11)])
check(r.ok, "nine running totals " + r.text[:160])
cells = {x["addr"]: x for x in Fr.get(B + f"/api/sheets/{SH}").json()["cells"]}
errs = [a for a, x in cells.items() if x.get("error") == "type"]
check(errs and all(cells[a].get("error_text") for a in errs), f"over the range budget: an error value with a text {errs}")
r = put(Fr, [(f"C{i}", "x") for i in range(1, 11)])
check(r.status_code == 400 and "table is full" in r.text, f"over the cell cap of the table: 400 {r.status_code} {r.text[:160]}")
check(put(Fr, [("A1", "7")]).ok, "changing a stored cell still works when full")
r = Fr.post(B + f"/api/sheets/{SH}/tabs", json={"copy_of": SH})  # 2.148.1 G (#2485)
check(r.status_code == 400 and "table is full" in r.text, f"a sheet copy over the cell cap of the table: 400 {r.status_code} {r.text[:160]}")
# an .xlsx import of a sparse sheet (one cell far right, one far down) works
sparse = '<row r="1"><c r="A1"><v>1</v></c></row><row r="40"><c r="H40"><v>2</v></c></row>'
r = Fr.post(B + "/api/sheets/import", files={"file": ("sparse.xlsx", book("A1:A1", sparse), "application/octet-stream")}, data={"space": "private"})
check(r.status_code == 201, f"a sparse .xlsx imports {r.status_code} {r.text[:200]}")

# 2.148.1 G (#2485): a mail over the size cap is marked seen and skipped (never fetched), also without a workspace cap
code = """
from kalmido.integrations import mail as m
class M:
    def __init__(s): s.fetched, s.seen = [], []
    def read(s, n): return b""
    def select(s, f): return "OK", [b"1"]
    def uid(s, cmd, *a):
        if cmd == "SEARCH": return "OK", [b"7"]
        if cmd == "FETCH" and a[1] == "(RFC822.SIZE)": return "OK", [b"7 (UID 7 RFC822.SIZE 99999999999)"]
        if cmd == "FETCH": s.fetched.append(a[0]); return "OK", []
        if cmd == "STORE": s.seen.append(a[0]); return "OK", []
x = M()
print(m.mail_fetch(x, "INBOX", lambda c, raw: True), len(x.fetched), len(x.seen))
"""
r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=120)
check(r.stdout.strip().splitlines()[-1:] == ["0 0 1"], f"mail fetch: a too large mail is skipped and marked seen {r.stdout[-120:]} {r.stderr[-300:]}")

# 2.148.1 G (#2485): a slowly answering bookmark server ends at the sync's deadline
code = """
import socket, threading, time, urllib.request
from kalmido.life import karakeep as kk
from kalmido.calendars import subscriptions as sub
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
def slow():
    s, _ = srv.accept(); s.recv(4096)
    s.sendall(b"HTTP/1.1 200 OK\\r\\nContent-Type: application/json\\r\\nContent-Length: 100000\\r\\n\\r\\n")
    for _ in range(40):
        time.sleep(0.25)
        try: s.sendall(b" ")
        except OSError: break
    s.close()
threading.Thread(target=slow, daemon=True).start()
kk.unseal = lambda *a: "key"
sub.cal_allow = lambda c: None
sub._cal_opener = lambda allow: urllib.request.build_opener()
kk._KK_END.t = time.monotonic() + 1.5
t0 = time.monotonic()
try:
    kk.kk_req(None, {"user_id": 1, "token": "x", "url": "http://127.0.0.1:%d" % srv.getsockname()[1]}, "/bookmarks")
    print("answer", round(time.monotonic() - t0, 1))
except kk.KkError as e:
    print("stopped", round(time.monotonic() - t0, 1))
"""
r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=120)
last = (r.stdout.strip().splitlines() or [""])[-1].split()
check(last[:1] == ["stopped"] and float(last[1]) < 5, f"bookmark sync: a slow server stops at the deadline {r.stdout[-120:]} {r.stderr[-300:]}")

# ================================================================== #2488 filed mail files
r = A.post(B + "/api/files/folders", json={"name": "E-Mails", "space": f"org:{ORG}"})
check(r.ok, "alice makes the mail folder " + r.text[:160])
FOLD = r.json().get("id") or r.json().get("node", {}).get("id")
check(A.patch(B + f"/api/files/nodes/{FOLD}", json={"org_access": "edit"}).ok, "... open for the organisation")
r = Ca.post(B + "/api/files/upload", files={"file": ("mail.eml", b"From: x@example.com\r\nSubject: private\r\n\r\nhello", "message/rfc822")},
            data={"parent_id": str(FOLD)})
check(r.status_code == 201, "a file in the folder " + r.text[:160])
EML = r.json()["items"][0]["id"]
r = Ca.post(B + "/api/files/upload", files={"file": ("plain.txt", b"just a file", "text/plain")}, data={"parent_id": str(FOLD)})
PLAIN = r.json()["items"][0]["id"]
ws = f"o{ORG}"
MID = dbx("INSERT INTO hub_mails(org_id, owner_id, ws, message_id, subject, eml_id, folder_id, created_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",
          (ORG, CAROL, ws, "<d1@example.com>", "", EML, FOLD, "2026-10-21T08:00:00Z"))[0][0]
dbx("UPDATE fs_nodes SET hub_mail_id=? WHERE id=?", (MID, EML))  # as the filing marks it (hub/hubmail.py)
check(A.get(B + f"/api/files/nodes/{EML}").status_code == 404, "the folder's owner (an org admin) without the mail's rights: 404")
check(A.get(B + f"/api/files/nodes/{EML}/content").status_code == 404, "... no download either")
kids = [x["id"] for x in A.get(B + "/api/files", params={"parent": FOLD}).json().get("items", [])]
check(EML not in kids and PLAIN in kids, f"... not in the listing, the other file is {kids}")
check(Bo.get(B + f"/api/files/nodes/{EML}").status_code == 404, "a member with folder access: 404")
check(Ca.get(B + f"/api/files/nodes/{EML}").ok, "the mail's recipient reads it")
check(Ca.get(B + f"/api/files/nodes/{EML}/content").ok, "... and downloads it")
# 2.148.1 G (#2488): an external link of the folder follows the same rule (its creator's rights)
r = A.post(B + f"/api/files/nodes/{FOLD}/ext-links", json={})
check(r.ok and r.json().get("links"), "an external link of the folder " + r.text[:160])
XP = re.sub(r"^https?://[^/]+", "", r.json()["links"][0]["url"]) if r.ok else "/s/f/x"
page = requests.get(B + XP, timeout=30).text
check("mail.eml" not in page and "plain.txt" in page, "external folder link: the filed mail is not listed, the other file is")
r = requests.get(B + XP + f"/d/{EML}", timeout=30, allow_redirects=False)
check(r.status_code != 200 and b"hello" not in r.content, f"external folder link: no download of the filed mail {r.status_code}")
check(requests.get(B + XP + f"/d/{PLAIN}", timeout=30).content == b"just a file", "external folder link: the other file downloads")

# 2.148.1 G (#2488): a sent mail's filed .eml follows the same rule
CL = Ca.post(B + "/api/lists", json={"name": "Carol project", "org_id": ORG, "kind": "project"}).json()["id"]
r = Ca.post(B + "/api/hubmail/send", json={"list_id": CL, "to": "client@example.com", "subject": "Project news", "text": "Launch."})
check(r.status_code == 201, f"carol sends a project mail {r.status_code} {r.text[:200]}")
OM = (r.json().get("mail") or {}).get("id") if r.status_code == 201 else None
row = dbx("SELECT eml_id, folder_id FROM hub_mails WHERE id=?", (OM,)) if OM else []
OEML = row[0][0] if row else None
check(OEML and dbx("SELECT hub_mail_id FROM fs_nodes WHERE id=?", (OEML,))[0][0] == OM, f"the sent mail's .eml is marked {row}")
check(OEML and Bo.get(B + f"/api/files/nodes/{OEML}").status_code == 404, "a member without the project: the sent .eml 404")
check(OEML and Ca.get(B + f"/api/files/nodes/{OEML}").ok, "the sender reads it")

# ================================================================== #2489 assistant: own lists only
AL = A.post(B + "/api/lists", json={"name": "Alice work", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{AL}/members", json={"user_id": BOB, "role": "edit"})
BL = Bo.post(B + "/api/lists", json={"name": "Bob work", "org_id": ORG}).json()["id"]
Bo.patch(B + "/api/settings", json={"assistant_on": "1"})
r = Bo.put(B + "/api/assistant/lists", json={"list_ids": [AL]})
check(r.status_code == 403, f"assistant: a list of someone else 403 {r.status_code} {r.text[:160]}")
r = Bo.put(B + "/api/assistant/lists", json={"list_ids": [BL]})
check(r.ok and [x["id"] for x in r.json()["lists"]] == [BL], "assistant: the own list " + r.text[:160])
FL = Fr.post(B + "/api/lists", json={"name": "Freelance"}).json()["id"]
Fr.patch(B + "/api/settings", json={"assistant_on": "1"})
r = Fr.put(B + "/api/assistant/lists", json={"list_ids": [FL]})
check(r.ok and [x["id"] for x in r.json()["lists"]] == [FL], "assistant: a person without an organisation shares her own list " + r.text[:160])

# ================================================================== #2495 agents
D = (date.today() + timedelta(days=5)).isoformat()
CAL = A.post(B + "/api/evcals", json={"name": "Team calendar", "org_id": ORG}).json()["id"]
r = A.put(B + f"/api/evcals/{CAL}/members", json={"user_id": AG, "role": "edit"})
check(r.ok, "the calendar is shared with the agent " + r.text[:160])
r = A.post(B + "/api/events", json={"cal_id": CAL, "title": "Agent meeting", "start": f"{D}T10:00", "end": f"{D}T11:00", "tz": "Europe/Berlin",
                                    "send_invites": True, "attendees": [{"email": "guest1@example.com", "name": "Guest"}]})
check(r.status_code == 201, "alice invites a guest " + r.text[:160])
E1 = r.json().get("id")
check(len(wait_mail("guest1@example.com", 1)) == 1, "... one invitation")
r = requests.delete(V + f"/events/{E1}", headers=AGH)
check(r.status_code in (200, 204), "the agent deletes it " + r.text[:160])
r = requests.post(V + f"/events/{E1}/restore", headers=AGH)
check(r.ok, "... and restores it " + r.text[:160])
time.sleep(1.5)
check(len(mails("guest1@example.com")) == 1, f"no cancellation / new invitation through the agent {len(mails('guest1@example.com'))}")
r = A.post(B + "/api/events", json={"title": "Alice meeting", "start": f"{D}T12:00", "end": f"{D}T13:00", "tz": "Europe/Berlin", "send_invites": True,
                                    "attendees": [{"email": "guest2@example.com", "name": "Guest Two"}]})
E2 = r.json().get("id")
check(len(wait_mail("guest2@example.com", 1)) == 1, "a person invites: one mail")
check(A.delete(B + f"/api/events/{E2}").ok and len(wait_mail("guest2@example.com", 2)) == 2, "a person deletes: the cancellation goes out")
# 2.148.1 G (#2495): an agent deleting its calendar sends no cancellations either
r = requests.post(V + "/event-calendars", headers=AGH, json={"name": "Agent calendar", "org_id": ORG})
check(r.status_code == 201, "the agent makes a calendar " + r.text[:160])
ACAL = r.json().get("id")
r = requests.put(V + f"/event-calendars/{ACAL}/members/{ALICE}", headers=AGH, json={"role": "edit"})
check(r.ok, "... shares it with alice " + r.text[:160])
r = A.post(B + "/api/events", json={"cal_id": ACAL, "title": "Shared meeting", "start": f"{D}T14:00", "end": f"{D}T15:00", "tz": "Europe/Berlin",
                                    "send_invites": True, "attendees": [{"email": "guest3@example.com", "name": "Guest Three"}]})
check(r.status_code == 201 and len(wait_mail("guest3@example.com", 1)) == 1, "alice invites a guest into it: one mail " + r.text[:160])
r = requests.delete(V + f"/event-calendars/{ACAL}", headers=AGH)
check(r.status_code == 204, "the agent deletes the calendar " + r.text[:160])
time.sleep(1.5)
check(len(mails("guest3@example.com")) == 1, f"no cancellation through the agent {len(mails('guest3@example.com'))}")

# forms: public = approval, internal private form of a freelancer, trash
r = requests.post(V + "/lists", headers=AGH, json={"name": "Agent intake"})
check(r.status_code == 201, "the agent makes a list " + r.text[:160])
GL = r.json()["id"]
r = requests.post(V + f"/lists/{GL}/forms", headers=AGH, json={"title": "Contact us", "access": "public"})
check(r.status_code == 202 and r.json().get("approval_required") is True, f"an agent's public form waits for approval {r.status_code} {r.text[:160]}")
check(not dbx("SELECT 1 FROM forms WHERE list_id=?", (GL,)), "... nothing created yet")
r = requests.post(V + f"/lists/{GL}/forms", headers=AGH, json={"title": "Team only", "access": "org"})
check(r.status_code == 201, "an internal form: at once " + r.text[:160])
GF = r.json().get("id")
r = requests.patch(V + f"/forms/{GF}", headers=AGH, json={"access": "public"})
check(r.status_code == 202, f"making it public waits for approval {r.status_code} {r.text[:160]}")
r = Fr.post(B + f"/api/lists/{FL}/forms", json={"title": "Internal", "access": "org"})
check(r.status_code == 201, "the freelancer's internal form " + r.text[:160])
URL = r.json()["url"]
path = "/f/" + URL.rsplit("/f/", 1)[1]
check(Fr.get(B + path).status_code == 200, "... opens for herself")
check(Bo.get(B + path).status_code == 404, "... another account of the server: not available (private)")
r = Fr.post(B + f"/api/lists/{FL}/forms", json={"title": "Public one", "access": "public"})
PURL = r.json()["url"]
ppath = "/f/" + PURL.rsplit("/f/", 1)[1]
check(requests.get(B + ppath).status_code == 200, "a public form opens")
dbx("UPDATE lists SET deleted_at='2026-10-21T08:00:00Z' WHERE id=?", (FL,))
check(requests.get(B + ppath).status_code == 404, "its list in the trash: 404")
check(requests.post(B + ppath, data={"title": "x"}).status_code == 404, "... and no entry is taken")
dbx("UPDATE lists SET deleted_at=NULL WHERE id=?", (FL,))

# address book: deleting a whole one waits for approval
r = requests.post(V + "/address-books", headers=AGH, json={"name": "Agent book"})
check(r.status_code == 201, "the agent makes an address book " + r.text[:160])
BK = r.json().get("id")
r = requests.delete(V + f"/address-books/{BK}", headers=AGH)
check(r.status_code == 202 and dbx("SELECT 1 FROM books WHERE id=?", (BK,)), f"deleting it waits for approval {r.status_code} {r.text[:160]}")

# deploy / integrate requests: the assignee alone does not decide
DL = A.post(B + "/api/lists", json={"name": "Code", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{DL}/members", json={"user_id": BOB, "role": "edit"})
A.put(B + f"/api/lists/{DL}/members", json={"user_id": AG, "role": "edit"})
dbx("UPDATE lists SET agent_members=1 WHERE id=?", (DL,))
T = A.post(B + "/api/tasks", json={"title": "Ship it", "list_id": DL, "assignee_id": BOB}).json()["id"]
r = requests.post(V + f"/tasks/{T}/comments", headers=AGH, json={"body": "Ready to integrate",
                  "suggestion": {"kind": "integrate", "source": "feat/x", "target": "main", "evidence": "tests green"}})
check(r.status_code in (200, 201), "the agent asks to integrate " + r.text[:160])
K = r.json().get("id") or r.json().get("comment", {}).get("id")
r = Bo.post(B + f"/api/comments/{K}/decide", json={"decision": "approve"})
check(r.status_code == 403, f"the assignee alone cannot decide {r.status_code} {r.text[:160]}")
r = A.post(B + f"/api/comments/{K}/decide", json={"decision": "approve"})
check(r.ok, "the list owner decides " + r.text[:160])

print(f"p21481_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
