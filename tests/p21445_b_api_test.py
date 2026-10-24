#!/usr/bin/env python3
"""2.144.5 part B, own container (start.sh with KALMIDO_SECRET_KEY, mode workspaces). Invented names only.
 - #2410 the mailbox of a workspace (hub_mailboxes) moves with the exports: the organisation export carries servers, user
   names and sender but never the passwords; imported into an empty organisation and into the private space (org ->
   private) it keeps server / user and asks for the passwords again (error "password", *_password_set false); the account
   export carries the private mailbox (no passwords), its import into an organisation (private -> org) keeps server / user,
   undo removes it again (2.144.5 A2, review R6/R7: imported switched off, undo keeps a changed one); a workspace that has a mailbox keeps its own (warning); the boundary check reports a mailbox whose
   ws does not match its organisation / owner; a person without organisation exports and imports their own mailbox
 - #2379 CalDAV: a PUT without any ATTENDEE from a client (app password) that never wrote one keeps the attendees and their
   answers; a client that wrote ATTENDEE before removes them by leaving them out (as before); 2.144.5 A2 (review R8): a PUT
   refused by If-Match learns nothing, learning adds to the known properties
usage: p21445_b_api_test.py <datadir>      (P21445B_NOSTART=1: the server already runs like that)"""
# freelancer-matrix: hub
import base64
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.206.0 (#2762): shared helpers (tests/kt.py)
FEAT = "cal,collab,comments,events,contacts,clients"
PW_IMAP, PW_SMTP, PW_PRIV = "imap-pw-Zq71", "smtp-pw-Zq72", "priv-pw-Zq73"


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def box(ws):
    r = dbx("SELECT org_id, owner_id, imap_host, imap_port, imap_user, smtp_host, smtp_port, smtp_user, from_addr, from_name, secret, error "
            "FROM hub_mailboxes WHERE ws=?", (ws,))
    return dict(zip(("org_id", "owner_id", "imap_host", "imap_port", "imap_user", "smtp_host", "smtp_port", "smtp_user", "from_addr",
                     "from_name", "secret", "error"), r[0])) if r else None


def upload(s, data, name="export.kalmido-export"):
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


def opened(s, data, rk=None):
    iid = upload(s, data)
    j = wait(s, iid)
    if rk:
        check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {j.get('error')}")
        check(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
        j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    return iid


def run(s, iid, target):
    # 2.269.0 (#3046): "again" = the person saw the preview's warning (a second import of one export is 409 without it)
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    j = wait(s, iid)
    check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')}")
    return j


def warnings(j):
    return " | ".join(x.get("text", "") for x in (j.get("result") or {}).get("warnings", []))


def org_export(s, oid):
    r = s.post(B + f"/api/orgs/{oid}/export")
    check(r.status_code == 202, f"organisation export {oid} started {r.text[:120]}")
    for _ in range(960):
        if s.get(B + f"/api/orgs/{oid}/export").json().get("state") != "running":
            break
        time.sleep(0.25)
    ox = s.get(B + f"/api/orgs/{oid}/export/file").content
    rk = s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
    check(ox[:13] == b"KALMIDO-ORGX\n" and rk, f"organisation export {oid} + recovery key")
    return ox, rk


def acct_export(s, secs=120):
    r = s.post(B + "/api/account/export")
    assert r.status_code == 202, r.text
    for _ in range(secs * 4):
        if s.get(B + "/api/account/export").json().get("state") != "running":
            break
        time.sleep(0.25)
    r = s.get(B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    return r.content


_spec = importlib.util.spec_from_file_location("kx", os.path.join(N, "..", "tools", "kalmido_export_decrypt.py"))
KX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(KX)


def open_archive(ox, rk):
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "a.kalmido-export"), os.path.join(d, "a.zip")
        with open(src, "wb") as f:
            f.write(ox)
        KX.decrypt(src, dst, KX.parse_key(rk))
        with open(dst, "rb") as f:
            return zipfile.ZipFile(io.BytesIO(f.read()))


# ---------------------------------------------------------------- server, people, organisations
if not os.environ.get("P21445B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Postfach", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORGS = {}
for n in ("Alpha Team", "Gamma Leer", "Delta Leer"):
    r = A.post(B + "/api/admin/orgs", json={"name": n, "admin_id": ALICE})
    assert r.status_code == 201, r.text
    ORGS[n] = r.json()["id"]
ORG, ORG3, ORG4 = ORGS["Alpha Team"], ORGS["Gamma Leer"], ORGS["Delta Leer"]
A.post(B + "/api/lists", json={"name": "Alpha Projekt", "org_id": ORG})

# ================================================================== #2410 the organisation's mailbox
MB = {"imap_host": "imap.example.com", "imap_port": 993, "imap_user": "team@example.com", "imap_password": PW_IMAP, "imap_folder": "INBOX",
      "smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_tls": "starttls", "smtp_user": "team@example.com", "smtp_password": PW_SMTP,
      "from_addr": "team@example.com", "from_name": "Alpha Team"}
r = A.put(B + "/api/hubmail/mailbox", json={"ws": f"org:{ORG}", **MB})
check(r.ok and r.json()["box"]["imap_password_set"] is True, f"setup: Alpha's mailbox {r.text[:200]}")

OX, RK = org_export(A, ORG)
z = open_archive(OX, RK)
check("hub/mailbox.json" in z.namelist(), "#2410: the organisation export has the mailbox")
rows = json.loads(z.read("hub/mailbox.json")) if "hub/mailbox.json" in z.namelist() else []
mb = rows[0] if rows else {}
check(len(rows) == 1 and mb.get("imap_host") == "imap.example.com" and mb.get("imap_user") == "team@example.com"
      and mb.get("smtp_host") == "smtp.example.com" and mb.get("smtp_port") == 587 and mb.get("from_addr") == "team@example.com",
      f"#2410: server, port, user, sender in the export {mb}")
check("secret" not in mb, "#2410: no secret column in the export")
raw_all = b"".join(z.read(n) for n in z.namelist())
check(PW_IMAP.encode() not in raw_all and PW_SMTP.encode() not in raw_all, "#2410: no password anywhere in the organisation export")

# into an empty organisation
iid = opened(A, OX, RK)
j = run(A, iid, ORG3)
b3 = box(f"o{ORG3}")
check(b3 and b3["org_id"] == ORG3 and b3["owner_id"] is None and b3["imap_host"] == "imap.example.com" and b3["imap_user"] == "team@example.com"
      and b3["smtp_user"] == "team@example.com" and b3["from_name"] == "Alpha Team", f"#2410: Gamma has the mailbox with server and user {b3}")
check(b3 and b3["secret"] == "" and b3["error"] == "password", f"#2410: without passwords, asks for them {b3 and (b3['secret'][:4], b3['error'])}")
# 2.144.5 A2 (#2410, review R6): switched off until the passwords are back (sending goes through the server meanwhile)
check(one("SELECT active FROM hub_mailboxes WHERE ws=?", (f"o{ORG3}",)) == 0, "R6: the imported mailbox is switched off")
g3 = A.get(B + f"/api/hubmail/mailbox?ws=org:{ORG3}").json().get("box") or {}
check(g3.get("imap_password_set") is False and g3.get("smtp_password_set") is False and g3.get("error") == "password" and g3.get("error_text")
      and g3.get("active") is False,
      f"#2410: the settings show 'enter the password' {g3}")
check("passwords" in warnings(j), f"#2410: the report says the passwords must be entered again: {warnings(j)}")
r = A.put(B + "/api/hubmail/mailbox", json={"ws": f"org:{ORG3}", "imap_host": "imap.example.com"})
check(r.status_code == 400, "#2410: saving without the password asks for it (400)")
r = A.put(B + "/api/hubmail/mailbox", json={"ws": f"org:{ORG3}", "imap_password": "new-imap", "smtp_password": "new-smtp"})
check(r.ok and r.json()["box"]["imap_password_set"] is True and r.json()["box"]["imap_host"] == "imap.example.com",
      f"#2410: the passwords entered again, the server stays {r.text[:200]}")

# org -> private (no private mailbox yet)
check(box(f"u{ALICE}") is None, "setup: no private mailbox yet")
iid = opened(A, OX, RK)
j = run(A, iid, "private")
bp = box(f"u{ALICE}")
check(bp and bp["org_id"] is None and bp["owner_id"] == ALICE and bp["imap_host"] == "imap.example.com" and bp["smtp_user"] == "team@example.com"
      and bp["secret"] == "", f"#2410: organisation -> private keeps server and user {bp}")
# again into Gamma: it has its own mailbox now, it stays
iid = opened(A, OX, RK)
j = run(A, iid, ORG3)
check(box(f"o{ORG3}")["secret"] != "" and "already has a mailbox" in warnings(j), f"#2410: a workspace keeps its own mailbox: {warnings(j)}")

# ================================================================== #2410 the account export (private -> org)
r = A.put(B + "/api/hubmail/mailbox", json={"ws": "private", "imap_password": PW_PRIV, "smtp_password": PW_PRIV, "from_name": "Alice privat"})
check(r.ok and r.json()["box"]["imap_password_set"] is True, f"setup: the private mailbox with passwords {r.text[:200]}")
EXP = acct_export(A)
za = zipfile.ZipFile(io.BytesIO(EXP))
check("data/mailbox.json" in za.namelist(), "#2410: the account export has the private mailbox")
am = (json.loads(za.read("data/mailbox.json")) or [{}])[0] if "data/mailbox.json" in za.namelist() else {}
check(am.get("imap_host") == "imap.example.com" and am.get("imap_user") == "team@example.com" and am.get("from_name") == "Alice privat"
      and "secret" not in am, f"#2410: server, user, sender, no secret {am}")
check(PW_PRIV.encode() not in b"".join(za.read(n) for n in za.namelist()), "#2410: no password anywhere in the account export")
j0 = A.get(B + "/api/export.json")
check(j0.ok and PW_PRIV not in j0.text and "imap.example.com" in j0.text, "#2410: the JSON export has it too, without the password")
iid = opened(A, EXP)
j = run(A, iid, ORG4)
b4 = box(f"o{ORG4}")
check(b4 and b4["org_id"] == ORG4 and b4["owner_id"] is None and b4["imap_host"] == "imap.example.com" and b4["from_name"] == "Alice privat"
      and b4["secret"] == "" and b4["error"] == "password", f"#2410: private -> organisation keeps server and user {b4}")
check(box(f"u{ALICE}")["secret"] != "", "#2410: the private mailbox itself is untouched")
iid_db = (j.get("result") or {}).get("import_id")
r = A.post(B + f"/api/imports/{iid_db}/undo")
check(r.ok and box(f"o{ORG4}") is None, f"#2410: undo removes the mailbox again {r.text[:200]}")
# 2.144.5 A2 (#2410, review R7): a mailbox changed after the import (saved in the settings: error cleared, e.g. an SMTP
# box without a user and so without a password) stays on undo
iid = opened(A, EXP)
j = run(A, iid, ORG4)
dbx("UPDATE hub_mailboxes SET error='' WHERE ws=?", (f"o{ORG4}",))
r = A.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok and box(f"o{ORG4}") is not None, f"R7: undo keeps a mailbox changed since the import {r.text[:200]}")

# ================================================================== #2410 the boundary check
dbx("INSERT INTO hub_mailboxes(org_id, owner_id, ws, imap_host, imap_user, created_by, created_at, updated_at) "
    "VALUES(?, NULL, 'o999999', 'imap.example.com', 'x@example.com', ?, '2026-10-21T10:00:00Z', '2026-10-21T10:00:00Z')", (ORG4, ALICE))
bad = one("SELECT id FROM hub_mailboxes WHERE ws='o999999'")
bd = A.get(B + "/api/admin/orgs").json().get("boundary") or {}
hits = [x for x in bd.get("details") or [] if x.get("kind") == "hub_mailbox"]
check([x["id"] for x in hits] == [bad], f"#2410: the boundary check names the mailbox in the wrong workspace {hits} {bd.get('violations')}")
dbx("DELETE FROM hub_mailboxes WHERE ws='o999999'")
bd = A.get(B + "/api/admin/orgs").json().get("boundary") or {}
check(not [x for x in bd.get("details") or [] if x.get("kind") == "hub_mailbox"], "#2410: the right ones are no finding")

# ================================================================== #2410 a person without organisation (P4)
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
r = Fr.put(B + "/api/hubmail/mailbox", json={"ws": "private", "smtp_host": "smtp.example.org", "smtp_port": 465, "smtp_tls": "ssl",
                                             "smtp_user": "frida@example.org", "smtp_password": PW_PRIV, "from_addr": "frida@example.org"})
check(r.ok, f"freelancer: her private mailbox (sending only) {r.text[:200]}")
FEXP = acct_export(Fr)
zf = zipfile.ZipFile(io.BytesIO(FEXP))
fm = (json.loads(zf.read("data/mailbox.json")) or [{}])[0] if "data/mailbox.json" in zf.namelist() else {}
check(fm.get("smtp_host") == "smtp.example.org" and fm.get("smtp_tls") == "ssl" and "secret" not in fm
      and PW_PRIV.encode() not in b"".join(zf.read(n) for n in zf.namelist()), f"freelancer: the account export has her mailbox, no password {fm}")
check(Fr.delete(B + "/api/hubmail/mailbox?ws=private").ok and box(f"u{FID}") is None, "freelancer: removes her mailbox")
iid = opened(Fr, FEXP)
j = run(Fr, iid, "private")
bf = box(f"u{FID}")
check(bf and bf["owner_id"] == FID and bf["org_id"] is None and bf["smtp_host"] == "smtp.example.org" and bf["smtp_port"] == 465
      and bf["secret"] == "", f"freelancer: her import brings it back without the password {bf}")
gf = Fr.get(B + "/api/hubmail/mailbox?ws=private").json().get("box") or {}
check(gf.get("smtp_password_set") is False and gf.get("error") == "password", f"freelancer: the settings ask for the password {gf}")

# ================================================================== #2379 CalDAV: attendees when a PUT leaves ATTENDEE out
for u, n in (("bob", "Bob"),):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
BOB = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok  # alice may invite him
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
CAL = A.post(B + "/api/evcals", json={"name": "Privat Termine", "org_id": None}).json()


class Dav:
    def __init__(self, user, pw, ua):
        self.s = requests.Session()
        self.s.auth = (user, pw)
        self.s.headers["User-Agent"] = ua

    def put(self, path, body, h=None):
        return self.s.request("PUT", B + path, data=body.encode(), headers={"Content-Type": "text/calendar; charset=utf-8", **(h or {})},
                              allow_redirects=False)


def ics(uid, title, *extra):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Example//Test//EN", "BEGIN:VEVENT", f"UID:{uid}", "DTSTAMP:20261021T080000Z",
             "DTSTART:20261110T090000Z", "DTEND:20261110T100000Z", f"SUMMARY:{title}", *extra, "END:VEVENT", "END:VCALENDAR", ""]
    return "\r\n".join(lines)


WC = f"/dav/calendars/alice/e{CAL['id']}/"


def atts(eid):
    return sorted((a.get("email") or str(a.get("user_id")), a.get("partstat")) for a in A.get(B + f"/api/events/{eid}").json().get("attendees", []))


# the event with attendees, made in the app; bob answers
EV = A.post(B + "/api/events", json={"cal_id": CAL["id"], "title": "Abstimmung", "start": "2026-11-10T10:00", "end": "2026-11-10T11:00",
                                     "attendees": [{"user_id": BOB}, {"email": "guest@example.net"}]})
check(EV.ok, f"setup: an event with bob and a guest {EV.text[:200]}")
EID = EV.json().get("id")
r = Bo.post(B + f"/api/events/{EID}/rsvp", json={"partstat": "accepted"})
before = atts(EID)
check(len(before) == 2 and (str(BOB), "accepted") in before, f"setup: two attendees, bob accepted {before} {r.status_code} {r.text[:120]}")
HREF = one("SELECT href FROM events WHERE id=?", (EID,))
UID_ = one("SELECT uid FROM events WHERE id=?", (EID,))

# client A: never writes ATTENDEE
pa = A.post(B + "/api/me/app-passwords", json={"name": "Client A"}).json()["password"]
ca = Dav("alice", pa, "ExampleCal/1.0")
r = ca.put(WC + HREF, ics(UID_, "Abstimmung neu"))
check(r.status_code == 204, f"#2379: client A changes the title {r.status_code} {r.text[:200]}")
check(A.get(B + f"/api/events/{EID}").json().get("title") == "Abstimmung neu", "#2379: the change is stored")
check(atts(EID) == before, f"#2379: a client that never wrote ATTENDEE keeps the attendees and bob's answer {atts(EID)}")
check(one("SELECT caps FROM app_passwords WHERE name='Client A'") in ("", None), "#2379: client A learned nothing")

# client B: writes ATTENDEE first, then leaves them out = removed
pb = A.post(B + "/api/me/app-passwords", json={"name": "Client B"}).json()["password"]
cb = Dav("alice", pb, "OtherCal/2.0")
# 2.144.5 A2 (#2379, review R8): a PUT refused by If-Match teaches nothing; learning adds to what the password knew
dbx("UPDATE app_passwords SET caps='CATEGORIES' WHERE name='Client B'")
r = cb.put(WC + HREF, ics(UID_, "Abstimmung B", f"ATTENDEE;CN=Bob:urn:kalmido:user:{BOB}"), {"If-Match": '"stale-etag"'})
check(r.status_code == 412 and one("SELECT caps FROM app_passwords WHERE name='Client B'") == "CATEGORIES",
      f"R8: a refused PUT (If-Match) learns nothing {r.status_code} {one('SELECT caps FROM app_passwords WHERE name=?', ('Client B',))}")
r = cb.put(WC + HREF, ics(UID_, "Abstimmung B", "ORGANIZER:mailto:alice@example.com",
                          f"ATTENDEE;CN=Bob;PARTSTAT=ACCEPTED;X-KALMIDO-USER={BOB}:urn:kalmido:user:{BOB}", "ATTENDEE;CN=Guest:mailto:guest@example.net"))
check(r.status_code == 204 and len(atts(EID)) == 2 and (str(BOB), "accepted") in atts(EID), f"#2379: client B writes both attendees {r.status_code} {atts(EID)}")
check(sorted((one("SELECT caps FROM app_passwords WHERE name='Client B'") or "").split(",")) == ["ATTENDEE", "CATEGORIES"],
      "#2379: client B is known to write ATTENDEE (R8: next to what it knew)")
r = cb.put(WC + HREF, ics(UID_, "Abstimmung B2"))
check(r.status_code == 204 and atts(EID) == [], f"#2379: client B leaves them out = removed (as before) {atts(EID)}")
# client A again: no attendees now, still nothing to keep; a new event without ATTENDEE from A stays without
r = ca.put(WC + "new-a.ics", ics("new-a@example", "Neu von A"))
check(r.status_code == 201 and one("SELECT COUNT(*) FROM event_attendees a JOIN events e ON e.id=a.event_id WHERE e.uid='new-a@example'") == 0,
      f"#2379: a new event of client A {r.status_code}")

if FAILS:  # the container log once (was in the suite's own check(), 2.206.0 #2762)
    print(subprocess.run(["docker", "logs", "--tail", "60", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True).stdout[-5000:], flush=True)
print(f"p21445_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
