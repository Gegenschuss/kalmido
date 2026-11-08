#!/usr/bin/env python3
"""2.237.0 D (#2870): the organisation import takes nobody else's account as author, and its undo checks rights and locks.
Invented names only.
 - an organisation with chat (alice + bob), a reaction of bob, time entries of alice + bob, a timesheet decided by bob,
   an absence of bob entered by bob and an office (a draft and a finalised invoice) is exported and imported into an
   EMPTY organisation with bob ticked: no author / decider / creator column names bob (chat, reaction, timesheet,
   absence creator); bob stays where the import shares (task people) or an admin enters it in the app too (his absence);
   his time entry goes to alice with his name in front of the note; the office log says "imported" for the documents
 - undo as an admin who is no admin of the target any more: 403, nothing removed
 - undo after a document of the import was finalised in the target: 409, nothing removed
 - undo by the admin of another target (the finalised invoice of the file was finalised there before): works, nothing left
   but that invoice with its client and its log entry (2.593.0 #4864: a document imported as finalised stays)
 - a person without organisation (freelancer) imports it privately: unchanged (no rows of others)
 - 2.459.0 (#3849): the organisation's symbol, a list icon and a header picture come back from files/pictures (new tokens, sealed,
   served): a target with a symbol keeps it, into the private workspace the list pictures only, the undo removes them (a picture
   changed since stays), a doctored archive (foreign ids, odd names, no picture, tokens in lists.json) sets nothing of its own
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2237D_NOSTART=1 = the server already runs like that).
usage: p2237_d_orgimport_test.py <datadir>"""
# freelancer-matrix: admin
# tenant-matrix: own
import base64
import glob
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import time
import zipfile
import zlib

import requests

import dbx as dbxm
from freelancer_fixture import FEATURES, freelancer
from kt import FAILS, OKS, check, sess, su_get

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
O, D = "/api/office", "/api/office/docs"


def png(rgb, size=16):
    """A small PNG (no Pillow in the test environment needed)."""
    def chunk(k, d):
        return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d))
    raw = (b"\0" + bytes(rgb) * size) * size
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def EH(email):
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


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


def opened(s, data, rk):
    iid = upload(s, data)
    j = wait(s, iid)
    check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {j.get('error')}")
    check(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
    j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    return iid


def run(s, iid, target, people=None):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": people or {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    j = wait(s, iid)
    check(j.get("state") == "done", f"import into {target} done {j.get('state')} {j.get('error')}")
    return j


def export(s, oid):
    r = s.post(B + f"/api/orgs/{oid}/export")
    check(r.status_code == 202, f"organisation export {oid} started {r.text[:120]}")
    for _ in range(960):
        if s.get(B + f"/api/orgs/{oid}/export").json().get("state") != "running":
            break
        time.sleep(0.25)
    ox = su_get(s, B + f"/api/orgs/{oid}/export/file").content  # 2.360.0 (#2496): the step-up
    rk = s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
    check(ox[:13] == b"KALMIDO-ORGX\n" and rk, f"organisation export {oid} + recovery key")
    return ox, rk


def counts(oid):
    """What an undo would remove in organisation oid (bundle 2.305: lists in the trash do not count, 2.272.0 C #3027: the undo
    puts the lists into the list trash, restorable, instead of deleting them)."""
    # 2.370.4 (#3089): the undo puts the clients into the client trash, too
    return {t: one(f"SELECT COUNT(*) FROM {t} WHERE org_id=?" + (" AND deleted_at IS NULL" if t in ("lists", "clients") else ""), (oid,))
            for t in ("lists", "office_docs", "clients", "hub_absences", "time_sheets")}


# ---------------------------------------------------------------- server, people, organisations
if not os.environ.get("P2237D_NOSTART"):
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
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Mitglied", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
orgs = {}
for name in ("Alpha Team", "Gamma Leer", "Delta Leer"):
    r = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": ALICE})
    assert r.status_code == 201, r.text
    orgs[name] = r.json()["id"]
ORG, ORG3, ORG4 = orgs["Alpha Team"], orgs["Gamma Leer"], orgs["Delta Leer"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
# bundle 2.305 (2.278.0 A #3095): an organisation import maps a ticked person only when he is a member of the target already
# (else he is invited and his rows stay out until he accepts) - bob is a member of both targets, as #2870 assumes
for o in (ORG3, ORG4):
    assert A.put(B + f"/api/orgs/{o}/members", json={"email": "bob@example.com", "role": "member"}).ok
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
NOW = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

# ---------------------------------------------------------------- the organisation's data
LO = ok(A.post(B + "/api/lists", json={"name": "Alpha Projekt", "org_id": ORG}), "org list")["id"]
ok(A.put(B + f"/api/lists/{LO}/members", json={"user_id": BOB, "role": "edit"}), "share the list with bob")
ok(A.patch(B + f"/api/lists/{LO}", json={"kind": "project", "time_tracking": True}), "a project with time tracking")
TO = ok(A.post(B + "/api/tasks", json={"title": "Dreh vorbereiten", "list_id": LO}), "task")["id"]
ok(A.patch(B + f"/api/tasks/{TO}", json={"people": [BOB]}), "bob comes along to the task")
rooms = [x for x in A.get(B + "/api/team").json().get("rooms", []) if x.get("kind") == "list" and x.get("list_id") == LO]
check(rooms, "the list has its channel")
RID = rooms[0]["id"] if rooms else 0
M1 = ok(A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Start um neun"}), "alice writes").get("id")
ok(Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Passt", "reply_to": M1}), "bob answers")
M1 = M1 or one("SELECT MIN(id) FROM tchat_msgs WHERE room_id=?", (RID,))
dbx("INSERT INTO tchat_rx(message_id,user_id,emoji,created_at) VALUES(?,?,?,?)", (M1, BOB, "up", NOW))
for s, who in ((A, "alice"), (Bo, "bob")):
    ok(s.post(B + "/api/time/entries", json={"list_id": LO, "start": "2026-10-12T09:00", "minutes": 30, "note": f"Schnitt {who}"}),
       f"time entry of {who}")
dbx("INSERT INTO time_sheets(org_id,user_id,month,state,note,log,created_at,updated_at,decided_by,decided_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
    (ORG, ALICE, "2026-09", "approved", "", "[]", NOW, NOW, BOB, NOW))
dbx("INSERT INTO hub_absences(org_id,user_id,kind,start_date,end_date,note,created_by,created_at,status,decided_by,decided_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (ORG, BOB, "vacation", "2026-11-02", "2026-11-06", "", BOB, NOW, "approved", BOB, NOW))
# the office: a finalised invoice and a draft
CL = ok(A.post(B + "/api/clients", json={"name": "Kunde Beispiel", "email": "kunde@example.com", "org_id": ORG, "street": "Musterweg 1",
                                          "zip": "12345", "city": "Musterstadt"}), "a client")["id"]
ok(A.put(B + f"{O}/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "street": "Hafenweg 2", "zip": "12345", "city": "Musterstadt",
                                                       "iban": "DE02120300000000202051", "tax_number": "12/345/67890"}, "lang": "en", "currency": "EUR"}),
   "office settings")
INV = ok(A.post(B + D, json={"kind": "invoice", "client_id": CL, "project_title": "Fertig", "service_from": "2026-05-01",
                             "items": [{"title": "Beratung", "qty": 1, "rate": 300}]}), "an invoice").get("id")
check(ok(A.post(B + f"{D}/{INV}/finalize"), "finalise").get("locked"), "the invoice is finalised")
ok(A.post(B + D, json={"kind": "invoice", "client_id": CL, "project_title": "Entwurf", "service_from": "2026-06-01",
                       "items": [{"title": "Schnitt", "qty": 1, "rate": 500}]}), "a draft")

# 2.459.0 (#3849): the pictures of the organisation and of the list
ok(A.post(B + f"/api/orgs/{ORG}/icon", files={"file": ("o.png", png((10, 120, 130)), "image/png")}), "organisation symbol")
ok(A.post(B + f"/api/lists/{LO}/icon", files={"file": ("i.png", png((200, 40, 40)), "image/png")}), "list icon")
ok(A.post(B + f"/api/lists/{LO}/header", files={"file": ("h.png", png((40, 40, 200), 64), "image/png")}), "header picture")
OLD_ICON = one("SELECT icon FROM lists WHERE id=?", (LO,))
OLD_HEAD = one("SELECT header_file FROM lists WHERE id=?", (LO,))

OX, RK = export(A, ORG)
dbx("DELETE FROM time_sheets WHERE org_id=?", (ORG,))  # one timesheet per person and month on the whole server (like a move to another server)

# ---------------------------------------------------------------- import into the empty organisation, bob ticked
iid = opened(A, OX, RK)
pv = A.get(B + f"/api/account/import/{iid}").json().get("preview") or {}
check({"what": "Pictures", "count": 3} in pv.get("taken_areas", []), f"#3849: the preview names the pictures {pv.get('taken_areas')}")
j = run(A, iid, ORG3, people={EH("bob@example.com"): {"share": True}})
NL = one("SELECT id FROM lists WHERE org_id=? AND name='Alpha Projekt'", (ORG3,))
NT = one("SELECT id FROM tasks WHERE list_id=? AND title='Dreh vorbereiten'", (NL,))
NR = one("SELECT id FROM tchat_rooms WHERE kind='list' AND list_id=?", (NL,))
check(NL and NT and NR, "list, task and channel are in the new organisation")
by = {x["body"]: x["user_id"] for x in dbx("SELECT body, user_id FROM tchat_msgs WHERE room_id=?", (NR,))}
check(by.get("Start um neun") == ALICE, f"alice's own message keeps her as author {by}")
check("Passt" in by and by["Passt"] is None, f"bob's message comes without an account as author {by}")
check(not dbx("SELECT 1 FROM tchat_rx x JOIN tchat_msgs m ON m.id=x.message_id WHERE m.room_id=? AND x.user_id=?", (NR, BOB)),
      "no reaction under bob's account")
te = dbx("SELECT user_id, note FROM time_entries WHERE list_id=? ORDER BY note", (NL,))
check(len(te) == 2 and all(x["user_id"] == ALICE for x in te), f"both time entries under the importing person {[dict(x) for x in te]}")
check(any(x["note"].startswith("Bob Mitglied: ") and "Schnitt bob" in x["note"] for x in te), f"bob's entry names him in the note {[x['note'] for x in te]}")
ts = dbx("SELECT user_id, decided_by FROM time_sheets WHERE org_id=?", (ORG3,))
check(ts and all(x["decided_by"] != BOB for x in ts), f"the timesheet is not decided by bob {[dict(x) for x in ts]}")
ab = dbx("SELECT user_id, created_by, decided_by FROM hub_absences WHERE org_id=?", (ORG3,))
check(len(ab) == 1 and ab[0]["user_id"] == BOB and ab[0]["created_by"] != BOB and ab[0]["decided_by"] != BOB,
      f"bob's absence is his (like an admin enters it), not entered or decided by him {[dict(x) for x in ab]}")
check(one("SELECT user_id FROM task_people WHERE task_id=?", (NT,)) == BOB, "bob stays on the task (sharing)")
check(not dbx("SELECT 1 FROM office_doc_log WHERE org_id=? AND user_id=?", (ORG3, BOB)), "no office log entry under bob")
nd = {x["project_title"]: x["id"] for x in dbx("SELECT id, project_title FROM office_docs WHERE org_id=?", (ORG3,))}
check({"Fertig", "Entwurf"} <= set(nd), f"both documents came along {nd}")
lg = dbx("SELECT doc_id, user_id FROM office_doc_log WHERE org_id=? AND action='import' AND target='doc'", (ORG3,))
check({x["doc_id"] for x in lg} >= {nd.get("Fertig"), nd.get("Entwurf")} and all(x["user_id"] == ALICE for x in lg),
      f"the office log says the documents were imported, by alice {[dict(x) for x in lg]}")
IMP3 = (j.get("result") or {}).get("import_id")


# ---------------------------------------------------------------- 2.459.0 (#3849): the pictures came along
def pics(lid):
    return dbx("SELECT icon, header_file, header_style FROM lists WHERE id=?", (lid,))[0]


def icon_of(oid):
    return one("SELECT icon FROM orgs WHERE id=?", (oid,))


def stored(pattern):
    return glob.glob(os.path.join(DATA, "attachments", pattern))


def got(s, url, magic):
    r = s.get(B + url)
    return r.status_code == 200 and r.content[:len(magic)] == magic


PNGM, JPGM = b"\x89PNG", b"\xff\xd8\xff"
p3, ic3 = pics(NL), icon_of(ORG3)
check(ic3.startswith("u:") and got(A, f"/api/org-icon/{ORG3}/{ic3[2:]}.png", PNGM), f"#3849: the organisation's symbol is back and served {ic3}")
check(str(p3["icon"]).startswith("u:") and p3["icon"] != OLD_ICON and got(A, f"/api/list-icon/{NL}/{p3['icon'][2:]}.png", PNGM),
      f"#3849: the list icon is back under a new token and served {p3['icon']}")
check(p3["header_file"] and p3["header_file"] != OLD_HEAD and p3["header_style"] == "image"
      and got(A, f"/api/list-header/{NL}/{p3['header_file']}.jpg", JPGM), f"#3849: the header picture is back and served {dict(p3)}")
files3 = stored(f"listicons/o{ORG3}-*") + stored(f"listicons/l{NL}-*") + stored(f"listheads/l{NL}-*")
check(len(files3) == 3, f"#3849: three new files {files3}")
for f in files3:
    with open(f, "rb") as fh:
        head = fh.read(4)
    check(head[:3] not in (PNGM[:3], JPGM), f"#3849: sealed with the target's key {os.path.basename(f)}")

# ---------------------------------------------------------------- undo: only admins of the target now, nothing frozen since
check(A.put(B + f"/api/orgs/{ORG3}/members", json={"email": "bob@example.com", "role": "admin"}).ok, "bob becomes admin of the target")
check(Bo.put(B + f"/api/orgs/{ORG3}/members", json={"email": "alice@example.com", "role": "member"}).ok, "alice is no admin there any more")
before = counts(ORG3)
r = A.post(B + f"/api/imports/{IMP3}/undo")
check(r.status_code == 403, f"undo as a former admin: 403 ({r.status_code} {r.text[:160]})")
check(counts(ORG3) == before and before["lists"] and before["office_docs"], f"nothing removed {before} {counts(ORG3)}")
check(Bo.put(B + f"/api/orgs/{ORG3}/members", json={"email": "alice@example.com", "role": "admin"}).ok, "alice is admin again")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG3}"})
check(ok(A.post(B + f"{D}/{nd.get('Entwurf')}/finalize"), "finalise the imported draft in the target").get("locked"), "the draft is finalised")
r = A.post(B + f"/api/imports/{IMP3}/undo")
check(r.status_code == 409, f"undo after a document of it was finalised here: 409 ({r.status_code} {r.text[:160]})")
check(counts(ORG3) == before, f"nothing removed {before} {counts(ORG3)}")

# ---------------------------------------------------------------- the normal undo by the admin (another target)
j = run(A, opened(A, OX, RK), ORG4, people={EH("bob@example.com"): {"share": True}})
check(one("SELECT COUNT(*) FROM office_docs WHERE org_id=? AND locked_at IS NOT NULL", (ORG4,)) == 1, "the invoice finalised in the file came along")
# 2.666.0 (#4074 3): a time entry of the import billed since on an invoice that stays is part of its basis: the undo keeps it
L4 = one("SELECT id FROM lists WHERE org_id=? AND name='Alpha Projekt'", (ORG4,))
TE4 = [x[0] for x in dbx("SELECT id FROM time_entries WHERE list_id=? ORDER BY id", (L4,))]
check(len(TE4) == 2, f"both time entries came along {TE4}")
dbx("UPDATE time_entries SET billed_doc_id=(SELECT id FROM office_docs WHERE org_id=? AND locked_at IS NOT NULL), billed_at=? WHERE id=?",
    (ORG4, NOW, TE4[0]))
r = A.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok, f"undo by the admin {r.status_code} {r.text[:160]}")
check([x[0] for x in dbx("SELECT id FROM time_entries WHERE id IN (?,?) ORDER BY id", tuple(TE4))] == TE4[:1],
      f"2.666.0 (#4074 3): the billed time entry stays, the other one goes {dbx('SELECT id, billed_doc_id FROM time_entries WHERE list_id=?', (L4,))}")
# 2.593.0 (#4864): ... but the invoice that came finalised, with its client
FIN4 = [x[0] for x in dbx("SELECT id FROM office_docs WHERE org_id=? AND locked_at IS NOT NULL", (ORG4,))]
check(counts(ORG4) == {"lists": 0, "office_docs": 1, "clients": 1, "hub_absences": 0, "time_sheets": 0} and len(FIN4) == 1,
      f"the undo removed everything but the finalised invoice and its client {counts(ORG4)}")
L4 = one("SELECT id FROM lists WHERE org_id=? AND name='Alpha Projekt'", (ORG4,))
p4 = pics(L4)
check(icon_of(ORG4) == "" and not p4["icon"] and p4["header_file"] == "" and p4["header_style"] == "", f"#3849: the undo clears the pictures {icon_of(ORG4)!r} {dict(p4)}")
check(not stored(f"listicons/o{ORG4}-*") + stored(f"listicons/l{L4}-*") + stored(f"listheads/l{L4}-*"), "#3849: ... and removes their files")
check([x[0] for x in dbx("SELECT doc_id FROM office_doc_log WHERE org_id=? AND action='import'", (ORG4,))] == FIN4,
      "... and its 'imported' log entries (2.593.0 #4864: but that of the finalised invoice)")

# ---------------------------------------------------------------- a freelancer imports it privately (unchanged)
FID, Fr = freelancer(B, A)
j = run(Fr, opened(Fr, OX, RK), "private")
FL = one("SELECT id FROM lists WHERE owner_id=? AND name='Alpha Projekt'", (FID,))
check(FL, "freelancer: the project came along")
check(one("SELECT COUNT(*) FROM tchat_msgs m JOIN tchat_rooms r ON r.id=m.room_id WHERE r.list_id=? AND m.user_id IS NOT NULL AND m.user_id<>?",
          (FL, FID)) == 0, "freelancer: no chat message under another account")
check(one("SELECT COUNT(*) FROM time_entries WHERE list_id=?", (FL,)) == 0, "freelancer: no time entries of others")
check(not dbx("SELECT 1 FROM org_members WHERE user_id=?", (FID,)), "freelancer: still in no organisation")
pf = pics(FL)
check(str(pf["icon"]).startswith("u:") and got(Fr, f"/api/list-icon/{FL}/{pf['icon'][2:]}.png", PNGM)
      and got(Fr, f"/api/list-header/{FL}/{pf['header_file']}.jpg", JPGM), f"#3849 freelancer: the list keeps its pictures {dict(pf)}")
check(any("private workspace: Symbol" in str(x.get("text")) for x in (j.get("result") or {}).get("warnings", [])),
      f"#3849 freelancer: the result names the symbol that stayed behind {(j.get('result') or {}).get('warnings')}")
r = Fr.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok and r.json().get("trash") and not dbx("SELECT 1 FROM lists WHERE id=? AND deleted_at IS NULL", (FL,)),
      f"freelancer: own undo works (the list in the trash, 2.272.0 C) {r.status_code} {r.text[:160]}")

check(not stored(f"listicons/l{FL}-*") and not stored(f"listheads/l{FL}-*"), "#3849 freelancer: the undo removes the pictures")


# ---------------------------------------------------------------- 2.459.0 (#3849): a target that has a symbol keeps it, a newer picture stays
def new_org(name):
    r = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": ALICE})
    assert r.status_code == 201, r.text
    return r.json()["id"]


ORG5 = new_org("Epsilon Eigen")
dbx("UPDATE orgs SET icon=? WHERE id=?", ("star", ORG5))
j = run(A, opened(A, OX, RK), ORG5)
check(icon_of(ORG5) == "star", f"#3849: an existing symbol is not overwritten {icon_of(ORG5)}")
check(any("keeps its symbol" in str(x.get("text")) for x in (j.get("result") or {}).get("warnings", [])), "#3849: ... and the result says so")
L5 = one("SELECT id FROM lists WHERE org_id=? AND name='Alpha Projekt'", (ORG5,))
check(str(pics(L5)["icon"]).startswith("u:"), "#3849: the list keeps its picture there")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG5}"})
ok(A.post(B + f"/api/lists/{L5}/icon", files={"file": ("n.png", png((1, 200, 1)), "image/png")}), "a new list icon after the import")
NEW5 = pics(L5)["icon"]
r = A.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok, f"undo {r.status_code} {r.text[:160]}")
check(icon_of(ORG5) == "star", "#3849: the undo leaves the existing symbol alone")
check(pics(L5)["icon"] == NEW5 and len(stored(f"listicons/l{L5}-*")) == 1, "#3849: the undo leaves a picture set since the import")

# ---------------------------------------------------------------- 2.459.0 (#3849): a doctored archive
TOOL = os.path.join(N, "..", "tools", "kalmido_export_decrypt.py")
ARC, ZIP = os.path.join(DATA, "p3849.arc"), os.path.join(DATA, "p3849.zip")
with open(ARC, "wb") as f:
    f.write(OX)
r = subprocess.run([sys.executable, TOOL, ARC, "-o", ZIP], input=RK + "\n", capture_output=True, text=True, timeout=300)
assert r.returncode == 0, r.stdout + r.stderr


def doctor(put, drop=()):
    """The opened archive, entries put / dropped, the manifest rebuilt: a plain ZIP any person can upload."""
    with zipfile.ZipFile(ZIP) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts.update(put)
    man = json.loads(parts.pop("manifest.json"))
    for n in drop:
        parts.pop(n, None)
    man["files"] = {n: {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for n, b in parts.items()}
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(man))
        for n, b in parts.items():
            z.writestr(n, b)
    return bio.getvalue()


def plain(s, data):
    iid = upload(s, data)
    return iid, wait(s, iid)


ORG6 = new_org("Zeta Leer")
with zipfile.ZipFile(ZIP) as z:
    rows = json.loads(z.read("lists.json"))
for x in rows:
    if x.get("id") == LO:
        x.update(header_file="../../../etc/passwd", header_style="image", icon="u:aaaaaaaaaaaa")
good = png((9, 9, 9))
data = doctor({"lists.json": json.dumps(rows).encode(),
               "files/pictures/organisation.png": b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>",
               f"files/pictures/list-{LO}-header.jpg": b"no picture at all",
               f"files/pictures/list-{NL}-icon.png": good,  # a list of the target (import 1), not of this file
               "files/pictures/list-999999999-icon.png": good, "files/pictures/list-0-icon.png": good,
               f"files/pictures/list-0{LO}-header.jpg": good, f"files/pictures/list-{LO}x-header.jpg": good,
               f"files/pictures/sub/list-{LO}-header.jpg": good, "files/pictures/passwd": good}, drop=(f"files/pictures/list-{LO}-icon.png",))
before3 = pics(NL)["icon"]
n_files = len(stored("listicons/*")) + len(stored("listheads/*"))
iid, st = plain(A, data)
check(st.get("state") == "preview", f"#3849: the doctored archive opens {st.get('state')} {st.get('error')}")
j = run(A, iid, ORG6)
L6 = one("SELECT id FROM lists WHERE org_id=? AND name='Alpha Projekt'", (ORG6,))
p6 = pics(L6) if L6 else {}
check(L6 and not p6["icon"] and p6["header_file"] == "" and p6["header_style"] == "", f"#3849: nothing of the file's tokens or a dead picture stays {dict(p6) if L6 else None}")
check(icon_of(ORG6) == "", f"#3849: something that is no picture does not become the symbol {icon_of(ORG6)}")
check(pics(NL)["icon"] == before3, "#3849: a list id of the target in a file name changes nothing there")
check(len(stored("listicons/*")) + len(stored("listheads/*")) == n_files, "#3849: not one file written")
check(any("could not be imported" in str(x.get("text")) for x in (j.get("result") or {}).get("warnings", [])), "#3849: the result names what was refused")
ok(A.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo"), "undo of the doctored import")
iid, st = plain(A, doctor({"files/pictures/../evil.png": good}))
check(st.get("state") == "invalid", f"#3849: a path trick in a name is refused as a whole {st.get('state')}")

# ---------------------------------------------------------------- 2.547.0 (#4295): a doctored office part, undo in a locked month
# the Org archive is a plain ZIP anyone can upload: ids in its office part that point at rows of another organisation (ORG3, the
# first import) are never taken over; a month locked in the target after the import keeps the import (undo 409, nothing removed)
F_CL = one("SELECT id FROM clients WHERE org_id=? ORDER BY id LIMIT 1", (ORG3,))
F_DOC = one("SELECT id FROM office_docs WHERE org_id=? ORDER BY id LIMIT 1", (ORG3,))
F_LIST = NL
with zipfile.ZipFile(ZIP) as z:
    names = set(z.namelist())
    docs = json.loads(z.read("office/documents.json"))
    items = json.loads(z.read("office/document_items.json")) if "office/document_items.json" in names else []
    pays = json.loads(z.read("office/payments.json")) if "office/payments.json" in names else []
    f_cl = {x.get("id") for x in json.loads(z.read("clients.json"))}
    f_li = {x.get("id") for x in json.loads(z.read("lists.json"))}
f_doc = {x.get("id") for x in docs}  # per kind: an id is mapped only within its own kind
check(F_CL and F_DOC and F_CL not in f_cl and F_DOC not in f_doc and F_LIST not in f_li,
      f"#4295 setup: foreign ids that are not in the file {F_CL} {F_DOC} {F_LIST} / {f_cl} {f_doc} {f_li}")
draft = next((x for x in docs if x.get("project_title") == "Entwurf"), None)
check(draft is not None, "#4295 setup: the draft is in the file")
for x in docs:
    x.update(client_id=F_CL, list_id=F_LIST, contract_id=F_DOC, cancels_id=F_DOC, replaces_id=F_DOC, ref_doc_ids=json.dumps([F_DOC]))
if draft is not None:
    draft["date"] = "2026-02-10"  # a finished month that the target locks after the import
for x in items:
    x.update(service_id=F_DOC, list_id=F_LIST)
pays.append({"id": 987654321, "doc_id": F_DOC, "amount": "99.00", "date": "2026-10-01", "method": "transfer"})
F_PAYS = one("SELECT COUNT(*) FROM office_payments WHERE doc_id=?", (F_DOC,))
put = {"office/documents.json": json.dumps(docs).encode(), "office/payments.json": json.dumps(pays).encode()}
if items:
    put["office/document_items.json"] = json.dumps(items).encode()
ORG7 = new_org("Eta Leer")
iid, st = plain(A, doctor(put))
check(st.get("state") == "preview", f"#4295: the doctored office part opens {st.get('state')} {st.get('error')}")
j = run(A, iid, ORG7)
IMP7 = (j.get("result") or {}).get("import_id")
d7 = [dict(x) for x in dbx("SELECT id, client_id, list_id, contract_id, cancels_id, replaces_id, ref_doc_ids, date FROM office_docs "
                           "WHERE org_id=?", (ORG7,))]
own_cl = {x["id"] for x in dbx("SELECT id FROM clients WHERE org_id=?", (ORG7,))}
own_docs = {x["id"] for x in d7}
check(len(d7) == len(docs), f"#4295: the documents of the file came along {len(d7)} of {len(docs)}")
check(all(x["client_id"] is None or x["client_id"] in own_cl for x in d7) and not [x for x in d7 if x["client_id"] == F_CL],
      f"#4295: a client id of another organisation becomes None {d7}")
check(all(x["list_id"] is None and x["contract_id"] is None and x["cancels_id"] is None and x["replaces_id"] is None for x in d7),
      f"#4295: list / contract / cancelled / replaced document of another organisation: None {d7}")
check(all(not set(json.loads(x["ref_doc_ids"] or "[]")) - own_docs for x in d7), f"#4295: no reference to a document of another organisation {d7}")
if items:
    it7 = dbx(f"SELECT service_id, list_id FROM office_doc_items WHERE doc_id IN ({','.join(str(int(i)) for i in own_docs) or '0'})")
    check(it7 and all(x["service_id"] is None and x["list_id"] is None for x in it7), f"#4295: positions keep no foreign service / list {[dict(x) for x in it7]}")
check(one("SELECT COUNT(*) FROM office_payments WHERE doc_id=?", (F_DOC,)) == F_PAYS
      and not dbx("SELECT 1 FROM office_payments WHERE org_id=? AND amount='99.00'", (ORG7,)),
      "#4295: a payment for a document of another organisation is not taken over")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG7}"})
r = A.post(B + f"{O}/periods/lock", json={"through": "2026-02", "confirm": "02/2026"})
check(r.ok and "2026-02" in (r.json().get("locked") or []), f"#4295 setup: February 2026 locked in the target {r.status_code} {r.text[:160]}")
before7 = counts(ORG7)
r = A.post(B + f"/api/imports/{IMP7}/undo")
check(r.status_code == 409, f"#4295: undo with a document in a month locked since: 409 ({r.status_code} {r.text[:160]})")
check(counts(ORG7) == before7 and before7["office_docs"], f"#4295: nothing removed {before7} {counts(ORG7)}")

if FAILS:  # the container log once
    ct = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
    print(subprocess.run(["docker", "logs", "--tail", "60", ct], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True).stdout[-6000:], flush=True)
print(f"p2237_d_orgimport: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
