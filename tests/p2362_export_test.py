#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.362.0 (#3090 #3092 #3096 #3131): the organisation and the account export leave nothing out silently. Invented names
only (example.com).
 - an organisation with a receipt billed on a document of another organisation, an open channel with a message, a file and
   a member, a closed channel of bob (alice is no member), a group conversation, a closed month of the logbook, a section
   template of the organisation, a contact on a task, a suppressed newsletter address and an encrypted task note of alice;
   exported and imported into an EMPTY organisation:
   #3131 the receipt stays billed ("billed, invoice missing": billed_at kept, no document; /receipts/billed names it, so
         billing it again is refused), the import warns, the unbill frees it on purpose
   #3092 the open channel comes with its member, message and file (the bytes download), the closed channel of bob and the
         group conversation stay out
   #3096 the closed month, the section template, the contact on the task and the suppressed address come along
   #3090 alice's encrypted task note carries the old AAD (legacy_aad) so she opens it again
 - a person without organisation (freelancer, P4) moves a project with a project note and an encrypted task note by account
   export / import (#3090): both in the file, both taken over (the note on the new project, the encrypted note with the old
   AAD, returned by GET .../enc-note)
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2362_NOSTART=1 = the server already runs like that).
usage: p2362_export_test.py <datadir>"""
# freelancer-matrix: own
# tenant-matrix: own
import base64
import io
import json
import os
import subprocess
import sys
import time
import zipfile

import requests

import dbx as dbxm
from freelancer_fixture import FEATURES, freelancer
from kt import FAILS, OKS, check, sess, su_get

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
D = "/api/office/docs"
NOTE = json.dumps({"v": 1, "iv": "AAAAAAAAAAAAAAAA", "ct": "c2VjcmV0LW5vdGU="})  # a browser ciphertext as stored (never opened here)


def ok(r, what, codes=(200, 201, 202, 204)):
    check(r.status_code in codes, f"{what}: {r.status_code} {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        return {}


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


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


def upload(s, data, name="alpha.kalmido-export"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid, secs=240):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def run(s, iid, target, people=None):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": target, "people": people or {}, "again": True})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    return wait(s, iid)


# ---------------------------------------------------------------- server, people, organisations
if not os.environ.get("P2362_NOSTART"):
    env = dict(os.environ, EXTRA=f"-e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Umzug", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
BOB = ok(A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Mitglied", "password": "password123",
                                         "email": "bob@example.com"}), "bob").get("id")
CARL = ok(A.post(B + "/api/users", json={"username": "carl", "display_name": "Carl Dritter", "password": "password123",
                                          "email": "carl@example.com"}), "carl").get("id")
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
orgs = {}
for name in ("Alpha Quelle", "Beta Fremd", "Gamma Leer"):
    r = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": ALICE})
    assert r.status_code == 201, r.text
    orgs[name] = r.json()["id"]
ORG, ORGB, ORG3 = orgs["Alpha Quelle"], orgs["Beta Fremd"], orgs["Gamma Leer"]
for em in ("bob@example.com", "carl@example.com"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": em, "role": "member"}).ok
assert A.put(B + f"/api/orgs/{ORG3}/members", json={"email": "bob@example.com", "role": "member"}).ok

# a document of another organisation (never in the export of alpha)
A.patch(B + "/api/settings", json={"workspace": f"org:{ORGB}"})
CLB = ok(A.post(B + "/api/clients", json={"name": "Kunde Fremd", "email": "fremd@example.com", "org_id": ORGB}), "client of beta").get("id")
FOREIGN = ok(A.post(B + D, json={"kind": "invoice", "client_id": CLB, "items": [{"title": "Fremd", "qty": 1, "rate": 50}]}),
             "a draft invoice of beta").get("id")

# ---------------------------------------------------------------- the source organisation
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
ok(A.put(B + "/api/office/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "street": "Hafenweg 2", "zip": "12345",
                                                               "city": "Musterstadt", "iban": "DE02120300000000202051",
                                                               "tax_number": "12/345/67890"}, "lang": "en", "currency": "EUR"}),
   "office settings")
# #3131: a receipt billed on beta's invoice (the invoice does not come along)
r = A.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files={"files": ("taxi-beleg.pdf", tiny_pdf("Taxi Beleg"), "application/pdf")})
check(r.status_code == 201, f"receipt uploaded {r.status_code} {r.text[:160]}")
RN = r.json()["ids"][0] if r.status_code == 201 else 0
ok(A.put(B + f"/api/docs/{RN}/receipt", json={"category": "Travel", "keep": True}), "marked as a receipt")
dbx("UPDATE rc_receipts SET billed_doc_id=?, billed_at=? WHERE node_id=?", (FOREIGN, "2026-10-16T10:00:00+00:00", RN))
check(one("SELECT billed_doc_id FROM rc_receipts WHERE node_id=?", (RN,)) == FOREIGN, "setup: the receipt is billed")
# a project with a task (contact on it, alice's encrypted note)
LO = ok(A.post(B + "/api/lists", json={"name": "Umzug Projekt", "org_id": ORG}), "org list")["id"]
ok(A.put(B + f"/api/lists/{LO}/members", json={"user_id": BOB, "role": "edit"}), "share the list")
TK = ok(A.post(B + "/api/tasks", json={"title": "Drehplan", "list_id": LO}), "task")["id"]
dbx("INSERT INTO task_enc_notes(task_id, user_id, body, updated_at) VALUES(?,?,?,?)", (TK, ALICE, NOTE, "2026-10-20T10:00:00Z"))
BK = ok(A.post(B + "/api/books", json={"name": "Team Kontakte", "org_id": ORG}), "an address book of the organisation").get("id")
if not one("SELECT org_id FROM books WHERE id=?", (BK,)):
    dbx("UPDATE books SET org_id=?, owner_org_id=? WHERE id=?", (ORG, ORG, BK))  # the shape of the API is not what this suite checks
CO = ok(A.post(B + "/api/contacts", json={"book_id": BK, "fn": "Kim Kontakt"}), "a contact").get("id")
dbx("INSERT INTO contact_tasks(contact_id, task_id, kind, added_by, added_at) VALUES(?,?,?,?,?)", (CO, TK, "waiting", ALICE, "2026-10-20T10:00:00Z"))
# #3092: an open channel (member bob, a message with a file), bob's closed channel, a group of three
CH = ok(A.post(B + "/api/team/channels", json={"name": "Allgemein Umzug", "org_id": ORG, "open": True, "members": [BOB]}), "open channel").get("id")
FILE = b"Ablaufplan Umzug\n" * 20
ok(A.post(B + f"/api/team/rooms/{CH}/messages", data={"body": "Hier der Plan"}, files=[("file", ("plan.txt", FILE, "text/plain"))]),
   "a message with a file")
CH2 = ok(Bo.post(B + "/api/team/channels", json={"name": "Bob Geheim", "org_id": ORG, "open": False}), "bob's closed channel").get("id")
ok(Bo.post(B + f"/api/team/rooms/{CH2}/messages", json={"body": "nur fuer bob"}), "a message in bob's channel")
GR = ok(A.post(B + "/api/team/groups", json={"members": [BOB, CARL], "name": "Kaffee Runde"}), "a group").get("id")
ok(A.post(B + f"/api/team/rooms/{GR}/messages", json={"body": "privat unter uns"}), "a message in the group")
# #3096: a closed month of the logbook, a section template of the organisation, a suppressed newsletter address
VH = ok(A.post(B + "/api/office/vehicles", json={"name": "Transporter", "plate": "M-AB 123", "kind": "company", "odo_start": 1000}),
        "vehicle").get("id")
ok(A.post(B + "/api/office/logbook/close", json={"month": "2026-03", "vehicle_id": VH}), "close March")
ok(A.post(B + "/api/section-templates", json={"name": "Dreh Ablauf", "space": f"org:{ORG}", "sections": ["Vorbereitung", "Dreh", "Schnitt"]}),
   "section template of the organisation")
HSUP = "a" * 64
dbx("INSERT INTO nl_suppress(ws, org_id, email_hash, kind, at) VALUES(?,?,?,?,?)", (f"o{ORG}", ORG, HSUP, "unsubscribed", "2026-10-01T10:00:00Z"))

# ---------------------------------------------------------------- export, import into the empty organisation
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, f"organisation export started {r.text[:120]}")
xs = None
for _ in range(960):
    xs = A.get(B + f"/api/orgs/{ORG}/export").json().get("state")
    if xs in ("done", "failed"):
        break
    time.sleep(0.25)
check(xs == "done", f"organisation export done {xs}")
OX = su_get(A, B + f"/api/orgs/{ORG}/export/file").content
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
iid = upload(A, OX)
wait(A, iid)
check(A.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": RK}).status_code == 202, "the recovery key is taken")
j = wait(A, iid)
check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
pp = {x.get("name"): x for x in (j.get("preview") or {}).get("people", [])}
check(pp.get("Bob Mitglied", {}).get("found") is True, f"preview: bob is found {pp.get('Bob Mitglied')}")
j = run(A, iid, ORG3, people={pp.get("Bob Mitglied", {}).get("key", "x"): {"share": True}})
check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')}")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG3}"})

# #3131: billed, invoice missing -- never open again
rc = dbx("SELECT node_id, billed_doc_id, billed_at FROM rc_receipts WHERE org_id=?", (ORG3,))
check(len(rc) == 1, f"the receipt came along {[dict(x) for x in rc]}")
NRN = rc[0]["node_id"] if rc else 0
check(rc and rc[0]["billed_doc_id"] is None and (rc[0]["billed_at"] or "").startswith("2026-10-16"),
      f"#3131: billed, the invoice missing (billing date kept) {[dict(x) for x in rc]}")
bl = ok(A.get(B + f"/api/office/receipts/billed?ids={NRN}"), "billed receipts").get("billed", {})
# the billing refuses every receipt this answer names (office/outlays.py au_bill_post: 409), so it is never billed twice
check((bl.get(str(NRN)) or {}).get("missing") == 1, f"#3131: the bookkeeping shows it billed, invoice missing {bl}")
W = {x.get("text", ""): x.get("count", 1) for x in (j.get("result") or {}).get("warnings", [])}
check(any("stay billed (invoice missing)" in k for k in W), f"#3131: the import says so {W}")
ok(A.post(B + "/api/office/receipts/unbill", json={"node_ids": [NRN]}), "unbill on purpose")
check(not one("SELECT billed_at FROM rc_receipts WHERE node_id=?", (NRN,)), "#3131: the unbill frees it on purpose")

# #3092: the open channel with its member, message and file; not bob's closed channel, not the group
ch = dbx("SELECT id, kind, name, org_id, is_open FROM tchat_rooms WHERE org_id=? AND kind='channel'", (ORG3,))
check([x["name"] for x in ch] == ["Allgemein Umzug"], f"#3092: only the open channel came along {[dict(x) for x in ch]}")
NCH = ch[0]["id"] if ch else 0
check(ch and ch[0]["is_open"] == 1, "#3092: it stays open")
mem = {x[0] for x in dbx("SELECT user_id FROM tchat_members WHERE room_id=?", (NCH,))}
check(mem == {ALICE, BOB}, f"#3092: alice and the ticked bob are its members {mem}")
msg = dbx("SELECT id, body FROM tchat_msgs WHERE room_id=?", (NCH,))
check([x["body"] for x in msg] == ["Hier der Plan"], f"#3092: the message came along {[dict(x) for x in msg]}")
tf = dbx("SELECT id, name, org_id, message_id FROM tchat_files WHERE room_id=?", (NCH,))
check(len(tf) == 1 and tf[0]["name"] == "plan.txt" and tf[0]["org_id"] == ORG3 and msg and tf[0]["message_id"] == msg[0]["id"],
      f"#3092: the file row hangs on the new message {[dict(x) for x in tf]}")
if tf:
    r = A.get(B + f"/api/team/files/{tf[0]['id']}")
    check(r.status_code == 200 and r.content == FILE, f"#3092: the file opens with its bytes {r.status_code} {len(r.content)}")
check(not dbx("SELECT 1 FROM tchat_msgs WHERE body IN ('nur fuer bob', 'privat unter uns') AND room_id NOT IN (?,?)", (CH2, GR)),
      "#3092: neither bob's closed channel nor the group conversation was copied")

# #3096: closed month, section template, contact on the task, suppressed address
NVH = one("SELECT id FROM office_vehicles WHERE org_id=?", (ORG3,))
check(dbx("SELECT 1 FROM office_drive_closed WHERE org_id=? AND vehicle_id=? AND month='2026-03'", (ORG3, NVH)),
      "#3096: March stays closed in the logbook (GoBD)")
st = dbx("SELECT user_id, sections FROM section_templates WHERE org_id=?", (ORG3,))
check(len(st) == 1 and st[0]["user_id"] == ALICE and "Schnitt" in st[0]["sections"], f"#3096: the section template {[dict(x) for x in st]}")
NL = one("SELECT id FROM lists WHERE org_id=? AND name='Umzug Projekt'", (ORG3,))
NTK = one("SELECT id FROM tasks WHERE list_id=? AND title='Drehplan'", (NL,))
check(dbx("SELECT 1 FROM contact_tasks ct JOIN contacts c ON c.id=ct.contact_id WHERE ct.task_id=? AND ct.kind='waiting' AND c.id<>?", (NTK, CO)),
      "#3096: the contact hangs on the new task")
check(dbx("SELECT 1 FROM nl_suppress WHERE ws=? AND org_id=? AND email_hash=?", (f"o{ORG3}", ORG3, HSUP)),
      "#3096: the unsubscribed address stays suppressed")
# #3090: the organisation import keeps the old AAD of alice's encrypted note
en = dbx("SELECT user_id, body, legacy_aad FROM task_enc_notes WHERE task_id=?", (NTK,))
check(len(en) == 1 and en[0]["body"] == NOTE and en[0]["legacy_aad"] == f"kalmido-note:v1:{TK}:{ALICE}",
      f"#3090: the encrypted note keeps its old AAD {[dict(x) for x in en]}")

# ---------------------------------------------------------------- P4 / #3090: a freelancer moves notes by account export / import
FID, Fr = freelancer(B, A, features=FEATURES)
FL = ok(Fr.post(B + "/api/lists", json={"name": "Frei Notizen"}), "freelancer list")["id"]
ok(Fr.post(B + f"/api/lists/{FL}/notes", json={"title": "Briefing", "body": "Kunde mag Blau"}), "a project note")
FT = ok(Fr.post(B + "/api/tasks", json={"title": "Schnitt", "list_id": FL}), "a task")["id"]
dbx("INSERT INTO task_enc_notes(task_id, user_id, body, updated_at) VALUES(?,?,?,?)", (FT, FID, NOTE, "2026-10-20T10:00:00Z"))
r = Fr.post(B + "/api/account/export")
check(r.status_code == 202, f"account export started {r.text[:120]}")
for _ in range(480):
    if Fr.get(B + "/api/account/export").json().get("state") != "running":
        break
    time.sleep(0.25)
AX = su_get(Fr, B + "/api/account/export/file").content
zf = zipfile.ZipFile(io.BytesIO(AX))
notes = json.loads(zf.read("data/notes.json")) if "data/notes.json" in zf.namelist() else []
encn = json.loads(zf.read("data/task_enc_notes.json")) if "data/task_enc_notes.json" in zf.namelist() else []
check([x.get("title") for x in notes] == ["Briefing"], f"#3090: the project note is in the account export {notes}")
check(len(encn) == 1 and encn[0].get("body") == NOTE, f"#3090: the encrypted task note is in the account export {encn}")
ej = Fr.get(B + "/api/export.json").json()
check([x.get("title") for x in ej.get("notes", [])] == ["Briefing"] and len(ej.get("task_enc_notes", [])) == 1,
      "#3090: export.json carries both too")
GID, Gr = freelancer(B, A, name="greta", features=FEATURES)
iid = upload(Gr, AX, "frida.zip")
j = wait(Gr, iid)
check(j.get("state") == "preview" and (j.get("preview") or {}).get("counts", {}).get("notes") == 1,
      f"freelancer: the preview counts the note {j.get('state')} {(j.get('preview') or {}).get('counts')}")
j = run(Gr, iid, "private")
check(j.get("state") == "done", f"freelancer: import done {j.get('error')}")
GL = one("SELECT id FROM lists WHERE owner_id=? AND name='Frei Notizen'", (GID,))
gn = dbx("SELECT title, body, created_by FROM notes WHERE list_id=?", (GL,))
check(len(gn) == 1 and gn[0]["title"] == "Briefing" and gn[0]["created_by"] == GID, f"#3090: the note is on the new project {[dict(x) for x in gn]}")
GT = one("SELECT id FROM tasks WHERE list_id=? AND title='Schnitt'", (GL,))
ge = Gr.get(B + f"/api/tasks/{GT}/enc-note")
check(ge.status_code == 200 and ge.json().get("legacy_aad") == f"kalmido-note:v1:{FT}:{FID}",
      f"#3090: greta's encrypted note answers with the old AAD {ge.status_code} {ge.text[:200]}")
check(not dbx("SELECT 1 FROM org_members WHERE user_id IN (?,?)", (FID, GID)), "freelancer: still in no organisation")

if FAILS:
    ct = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
    print(subprocess.run(["docker", "logs", "--tail", "60", ct], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True).stdout[-6000:], flush=True)
print(f"p2362_export: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
