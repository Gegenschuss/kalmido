#!/usr/bin/env python3
"""2.137.0 part C (#2344): the organisation import of the team areas, and the round trip of a whole organisation.
Invented names only.
 - an organisation with chat, absences, bookings, vacation accounts, filed e-mails, newsletter, customer reports, forms,
   playbooks, project notes, notepads, rules, histories, time entries and timesheets, notes encrypted in the browser, people
   on tasks, reactions, calendar / address book shares, sprints, a task in a further list (+ office, file store, knowledge
   page and table of parts A / B) is exported and imported into an EMPTY organisation (bob ticked, dora not):
   rows of bob come along, dora's are left out with a warning; forms and customer reports get new links (the address
   keeps its keyed hash), the newsletter connection comes without access data, a rule assigning dora is paused,
   harmless settings of the organisation come along; undo removes everything again
 - into the private space: only the importing person's own rows, no settings of the organisation
 - a person without organisation (freelancer) imports it privately: project notes, forms, chat come along, no rows of others
 - ROUND TRIP: export -> import into an empty organisation -> export again -> both archives compared per entry (row count,
   contents without ids / time stamps / organisation and person columns) and files (SHA-256). Differences are listed;
   the entries of this part must be equal (every entry since parts A and B are merged; P2137C_STRICT=0: only this part)
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2137C_NOSTART=1 = the server already runs like that).
usage: p2137_c_api_test.py <datadir>"""
# freelancer-matrix: own
# tenant-matrix: own
import base64
import collections
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile

import requests

import dbx as dbxm
from freelancer_fixture import FEATURES, freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.206.0 (#2762): shared helpers (tests/kt.py)
FEAT = FEATURES + ",sheets"


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


def T(sql, args=()):
    """The rows as tuples."""
    return [tuple(r[i] for i in range(len(r.keys()))) for r in dbx(sql, args)]


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
    return iid, j.get("preview") or {}


def run(s, iid, target, people=None):
    # 2.269.0 (#3046): "again" = the person saw the preview's warning (a second import of one export is 409 without it)
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": people or {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    return wait(s, iid)


def export(s, oid):
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


def warnings(j):
    return " | ".join(x.get("text", "") for x in (j.get("result") or {}).get("warnings", []))


# ---------------------------------------------------------------- the round trip: open + normalise an archive
_spec = importlib.util.spec_from_file_location("kx", os.path.join(N, "..", "tools", "kalmido_export_decrypt.py"))
KX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(KX)
# values that differ by nature between two servers / organisations: ids and references, time stamps, people, the space,
# links and keys made anew, ids inside JSON texts
SKIP_KEYS = re.compile(r"^(id|.*_id|.*_by|.*_at|org_id|owner_id|user_id|a|b|ws|uid|href|tt_id|path|sort|email_hash|token|"
                       r"trig_val|act_val|rule|files|data|review|res_label|personal_of|list_name|icon|name_key|log|"
                       r"reply_to|last_at|synced_at|updated|created|changed|added|at|day_key|enc_by|kenc|fetched)$")
SKIP_IN = {"newsletter/connection.json": ("auto", "error"),  # on purpose: no automatic sync until connected again
           "hub/mailbox.json": ("error",),  # 2.144.5 B (#2410): the mailbox asks for its passwords again
           "comments.json": ("ext_name",)}  # 2.148.1 (#2492): comments of others come by name only (ext_name), never as their account
DEPENDS = {"hub/bookings.json": "office/equipment.json"}  # bookings of equipment come with part A (office)
SKIP_ENTRIES = {"manifest.json", "organisation.json", "members.json"}


def open_archive(ox, rk):
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "a.kalmido-export"), os.path.join(d, "a.zip")
        with open(src, "wb") as f:
            f.write(ox)
        KX.decrypt(src, dst, KX.parse_key(rk))
        with open(dst, "rb") as f:
            return zipfile.ZipFile(io.BytesIO(f.read()))


def norm_rows(rows, skip=()):
    out = collections.Counter()
    for r in rows:
        if isinstance(r, dict) and r.get("action") == "recovery_key" and r.get("target") == "org":
            continue  # 2.137.0 (#2344, with 2.138.0 #1972): the target's own recovery key, made by its first export
        if isinstance(r, dict):
            out[json.dumps({k: v for k, v in r.items() if not SKIP_KEYS.match(k) and k not in skip}, sort_keys=True, ensure_ascii=False, default=str)] += 1
    return out


def norm_archive(zf):
    """{entry: Counter of normalised rows} and {file folder: Counter of SHA-256}."""
    rows, files = {}, collections.defaultdict(collections.Counter)
    for n in zf.namelist():
        if n in SKIP_ENTRIES:
            continue
        raw = zf.read(n)
        if n.endswith(".json") and not n.startswith("files/"):
            rows[n] = norm_rows(json.loads(raw.decode("utf-8")), SKIP_IN.get(n, ()))
        else:
            files[n.rsplit("/", 1)[0]][hashlib.sha256(raw).hexdigest()] += 1
    return rows, files


def norm_archive_count(zf, entry):
    try:
        return len(json.loads(zf.read(entry).decode("utf-8")))
    except KeyError:
        return 0


def compare(z1, z2):
    """-> [(entry, text)] of every difference."""
    r1, f1 = norm_archive(z1)
    r2, f2 = norm_archive(z2)
    diffs = []
    for n in sorted(set(r1) | set(r2)):
        a, b = r1.get(n, collections.Counter()), r2.get(n, collections.Counter())
        if sum(a.values()) != sum(b.values()):
            diffs.append((n, f"rows {sum(a.values())} -> {sum(b.values())}"))
        elif a != b:
            lost = list((a - b).elements())[:1]
            new = list((b - a).elements())[:1]
            try:  # the keys that differ, so a red run says what changed
                x, y = json.loads(lost[0]), json.loads(new[0])
                keys = sorted(k for k in set(x) | set(y) if x.get(k) != y.get(k))
                diffs.append((n, "contents differ: " + "; ".join(f"{k}: {str(x.get(k))[:80]!r} -> {str(y.get(k))[:80]!r}" for k in keys)))
            except (ValueError, TypeError, IndexError, AttributeError):
                diffs.append((n, f"contents differ: before {lost[0][:300] if lost else ''} | after {new[0][:300] if new else ''}"))
    for d in sorted(set(f1) | set(f2)):
        if f1.get(d) != f2.get(d):
            diffs.append((d + "/", f"files {sum(f1.get(d, {}).values())} -> {sum(f2.get(d, {}).values())} (or other contents)"))
    return diffs


# the entries of this part (admin/oi_team.py) + what the base import does (lists, tasks, calendars, address books)
MINE = ("chat/", "hub/", "newsletter/", "portal/", "lists/forms.json", "lists/form_entries.json", "lists/playbooks.json",
        "lists/notes.json", "lists/notepads.json", "lists/rules.json", "lists/history.json", "lists/sprints.json",
        "lists/admin_log.json", "time_entries.json", "time_sheets.json", "tasks/encrypted_notes.json", "tasks/locked_notes.json",
        "tasks/people.json", "tasks/history.json", "tasks/links.json", "comments/reactions.json", "calendars/members.json",
        "books/members.json")

# ---------------------------------------------------------------- server, people, organisations
if not os.environ.get("P2137C_NOSTART"):
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
ids = {}
for u, n in (("bob", "Bob Mitglied"), ("dora", "Dora Mitglied")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, DORA = ids["bob"], ids["dora"]
Bo, Do = sess("bob"), sess("dora")
for s in (A, Bo, Do):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha Team", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
for u in ("bob", "dora"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Gamma Leer", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG3 = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
NOW = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

# ---------------------------------------------------------------- the organisation's data
LO = ok(A.post(B + "/api/lists", json={"name": "Alpha Projekt", "org_id": ORG}), "org list")["id"]
LO2 = ok(A.post(B + "/api/lists", json={"name": "Alpha Zweitliste", "org_id": ORG}), "second org list")["id"]
for u in (BOB, DORA):
    ok(A.put(B + f"/api/lists/{LO}/members", json={"user_id": u, "role": "edit"}), "share the list")
ok(A.patch(B + f"/api/lists/{LO}", json={"kind": "project", "time_tracking": True}), "a project with time tracking")
SEC = ok(A.post(B + "/api/sections", json={"list_id": LO, "name": "Doing"}), "a section")["id"]
TO = ok(A.post(B + "/api/tasks", json={"title": "Dreh vorbereiten", "list_id": LO}), "task")["id"]
ok(A.patch(B + f"/api/tasks/{TO}", json={"people": [BOB]}), "bob comes along to the task")
CID = ok(Bo.post(B + f"/api/tasks/{TO}/comments", json={"body": "Licht ist bestellt"}), "bob comments").get("id")
ok(A.post(B + f"/api/comments/{CID}/reactions", json={"emoji": "up", "on": True}), "alice reacts")
# chat: the list's channel
rooms = [x for x in A.get(B + "/api/team").json().get("rooms", []) if x.get("kind") == "list" and x.get("list_id") == LO]
check(rooms, "the list has its channel")
RID = rooms[0]["id"] if rooms else 0
M1 = ok(A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Start um neun"}), "alice writes").get("id")
ok(Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Passt", "reply_to": M1}), "bob answers")
ok(Do.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Ich komme später"}), "dora writes")
M1 = M1 or one("SELECT MIN(id) FROM tchat_msgs WHERE room_id=?", (RID,))
dbx("INSERT INTO tchat_rx(message_id,user_id,emoji,created_at) VALUES(?,?,?,?)", (M1, BOB, "up", NOW))
# notes, notepads, playbook, form, rules
ok(A.post(B + f"/api/lists/{LO}/notes", json={"title": "Kick-off", "body": "Ziele des Projekts", "pinned": True}), "a project note")
ok(A.post(B + f"/api/lists/{LO}/notepads", json={"title": "Entscheidungen", "body": "- Drehtag fix"}), "a notepad")
ok(A.put(B + f"/api/lists/{LO}/playbook", json={"text": "Kunden binnen eines Tages antworten."}), "a playbook")
FORM = ok(A.post(B + f"/api/lists/{LO}/forms", json={"title": "Meldung", "access": "public", "portal": True}), "a portal form")
ok(A.patch(B + f"/api/lists/{LO}", json={"tickets": True}), "tickets on")
ok(A.post(B + f"/api/lists/{LO}/rules", json={"name": "Bob übernimmt", "trigger": {"kind": "section", "section_id": SEC},
                                              "action": {"kind": "assign", "user_id": BOB}}), "a rule assigning bob")
ok(A.post(B + f"/api/lists/{LO}/rules", json={"name": "Dora übernimmt", "trigger": {"kind": "done"},
                                              "action": {"kind": "assign", "user_id": DORA}}), "a rule assigning dora")
# a customer report through the public form (anonymous, with the address)
tokf = (FORM.get("url") or "/x").rsplit("/", 1)[1]
anon = requests.Session()
page = anon.get(B + "/f/" + tokf)
m = re.search(r'name="stamp" value="([^"]+)"', page.text)
time.sleep(3.2)
p = anon.post(B + "/f/" + tokf, data={"subject": "Ton rauscht", "text": "Im zweiten Clip.", "name": "Erika Kunde",
                                      "email": "erika@example.com", "stamp": m.group(1) if m else ""}, headers={"Sec-Fetch-Site": "same-origin"})
check(p.ok, f"a customer report is sent {p.status_code}")
TK = dbx("SELECT id, task_id, email_hash FROM portal_tickets WHERE list_id=?", (LO,))
check(len(TK) == 1, "the customer report exists")
EHASH = TK[0]["email_hash"] if TK else ""
if TK and not dbx("SELECT 1 FROM form_entries WHERE task_id=?", (TK[0]["task_id"],)):
    dbx("INSERT INTO form_entries(task_id,form_id,sender,email,answers,created_at) VALUES(?,?,?,?,?,?)",
        (TK[0]["task_id"], FORM.get("id"), "Erika Kunde", "erika@example.com", '{"q1": "Clip 2"}', NOW))
# time entries + a timesheet
for s, who in ((A, "alice"), (Bo, "bob"), (Do, "dora")):
    ok(s.post(B + "/api/time/entries", json={"list_id": LO, "start": "2026-10-12T09:00", "minutes": 30, "note": f"Schnitt {who}"}),
       f"time entry of {who}")
dbx("INSERT INTO time_sheets(org_id,user_id,month,state,note,log,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
    (ORG, BOB, "2026-09", "closed", "", "[]", NOW, NOW))
dbx("INSERT INTO time_sheets(org_id,user_id,month,state,note,log,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
    (ORG, DORA, "2026-09", "closed", "", "[]", NOW, NOW))
# notes encrypted in the browser (ciphertexts as the browser stores them)
CT = json.dumps({"v": 1, "iv": base64.b64encode(b"0" * 12).decode(), "ct": base64.b64encode(b"x" * 24).decode()})
dbx("INSERT INTO task_enc_notes(task_id,user_id,body,updated_at) VALUES(?,?,?,?)", (TO, BOB, CT, NOW))
dbx("INSERT INTO task_enc_notes(task_id,user_id,body,updated_at) VALUES(?,?,?,?)", (TO, DORA, CT, NOW))
TL = ok(A.post(B + "/api/tasks", json={"title": "Gesperrte Notiz", "list_id": LO2}), "task with a locked note")["id"]
dbx("INSERT INTO task_note_locks(task_id,user_id,body,updated_at) VALUES(?,?,?,?)", (TL, ALICE, CT, NOW))
# sprint + a task placed in a further list
SP = dbx("INSERT INTO sprints(list_id,num,name,start,end_day,state,created_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
         (LO, 1, "Sprint 1", "2026-10-12", "2026-10-23", "active", NOW))[0][0]
dbx("UPDATE tasks SET sprint_id=? WHERE id=?", (SP, TO))
dbx("INSERT INTO task_links(task_id,list_id,sort,org_id,created_at) VALUES(?,?,?,?,?)", (TO, LO2, 1, ORG, NOW))
# absences, vacation accounts, bookings
for u in (BOB, DORA):
    ok(A.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2026-11-23", "end_date": "2026-11-24", "org": ORG,
                                             "user_id": u, "note": "Herbsturlaub"}), "an absence")
    ok(A.put(B + "/api/team/leave/quota", json={"user_id": u, "year": 2026, "days": 28, "carry": 2, "org": ORG}), "a vacation account")
CAM = ok(A.post(B + "/api/office/equipment", json={"name": "Lichtkoffer", "daily_rate": 80}), "equipment").get("id")
ok(A.post(B + "/api/team/dispo/bookings", json={"title": "Dreh", "start": "2026-11-17", "status": "option", "org": ORG, "list_id": LO,
                                               "resources": [{"kind": "user", "id": BOB}, {"kind": "user", "id": DORA},
                                                             {"kind": "equipment", "id": CAM}]}), "bookings")
# calendar + address book shared with bob
CAL = ok(A.post(B + "/api/evcals", json={"name": "Alpha Studio", "org_id": ORG}), "org calendar").get("id")
ok(A.put(B + f"/api/evcals/{CAL}/members", json={"user_id": BOB, "role": "edit"}), "calendar shared with bob")
BK = ok(A.post(B + "/api/books", json={"name": "Alpha Kunden", "org_id": ORG}), "org address book").get("id")
ok(A.put(B + f"/api/books/{BK}/members", json={"user_id": BOB, "role": "view"}), "address book shared with bob")
# office, file store, knowledge page, table (parts A / B: in the round trip)
CL = ok(A.post(B + "/api/clients", json={"name": "Muster Film GmbH", "org_id": ORG}), "a client").get("id")
ok(A.post(B + "/api/office/docs", json={"kind": "offer", "client_id": CL, "project_title": "Imagefilm",
                                       "items": [{"kind": "service", "title": "Drehtag", "qty": 1, "unit": "day", "rate": 800}]}), "an offer")
FD = ok(A.post(B + "/api/files/folders", json={"name": "Kunden", "space": f"org:{ORG}"}), "a folder").get("id")
ok(A.post(B + "/api/files/upload", data={"parent_id": FD}, files=[("file", ("brief.txt", b"Briefing " + os.urandom(6).hex().encode(), "text/plain"))]),
   "a file in the store")
ok(A.post(B + "/api/wiki/pages", json={"space": f"org:{ORG}", "path": "Ablauf", "body": "# Ablauf\nErst planen."}), "a knowledge page")
SH = ok(A.post(B + "/api/sheets", json={"title": "Budget", "space": f"org:{ORG}"}), "a table")
if SH.get("id"):
    t = A.get(B + f"/api/sheets/{SH['id']}").json()
    rid0, cid0 = ((t.get("rows") or [{}])[0].get("id"), (t.get("columns") or [{}])[0].get("id"))
    ok(A.put(B + f"/api/sheets/{SH['id']}/cells", json={"cells": [{"row_id": rid0, "col_id": cid0, "raw": "Kamera"}]}), "a cell")
# filed e-mail + newsletter (no outside service here: rows as the app stores them)
dbx("""INSERT INTO hub_mails(org_id,owner_id,client_id,list_id,ws,message_id,from_addr,from_name,to_addrs,subject,body,created_at)
       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (ORG, ALICE, CL, LO, f"o{ORG}", "<m1@example.com>", "kunde@example.com", "Kunde",
                                            "alice@example.com", "Rohschnitt", "Sieht gut aus.", NOW))
dbx("""INSERT INTO hub_mails(org_id,owner_id,ws,message_id,from_addr,subject,body,created_at) VALUES(?,?,?,?,?,?,?,?)""",
    (ORG, DORA, f"o{ORG}", "<m2@example.com>", "privat@example.com", "Nur Dora", "Privat abgelegt.", NOW))
NC = dbx("""INSERT INTO nl_conns(org_id,ws,kind,url,secret,hint,mode,auto,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) RETURNING id""",
         (ORG, f"o{ORG}", "listmonk", "https://news.example.com", "sealed-secret", "abcd", "consented", 1, NOW, NOW))[0][0]
NS = dbx("""INSERT INTO nl_segments(conn_id,org_id,name,rule,remote_id,remote_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id""",
         (NC, ORG, "Kunden", json.dumps({"books": [BK]}), "7", "Kunden", NOW, NOW))[0][0]
dbx("INSERT INTO nl_members(seg_id,org_id,email,remote_ref,state,synced_at) VALUES(?,?,?,?,?,?)", (NS, ORG, "leser@example.com", "11", "ok", NOW))
dbx("INSERT INTO nl_runs(conn_id,org_id,kind,state,started_at,counts) VALUES(?,?,?,?,?,?)", (NC, ORG, "manual", "done", NOW, '{"added": 1}'))
# harmless settings of the organisation
dbx("UPDATE orgs SET color=?, hub_leave_approval=1 WHERE id=?", ("#336699", ORG))
# 2.137.1 (#2399): ids inside the history data (bob ticked, dora not; an id of a row that does not come along)
dbx("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
    (TO, BOB, "ml_add", json.dumps({"list_id": LO2, "section_id": SEC, "user_id": BOB, "gone_id": 987654321}), NOW))
dbx("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)", (TO, BOB, "assign", json.dumps({"to": DORA, "from": BOB}), NOW))
dbx("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
    (TO, BOB, "subtask", json.dumps({"id": 987654321, "title": "Weg"}), NOW))
dbx("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
    (TO, BOB, "tidy", json.dumps({"by": DORA, "via": "webhook", "hook": 987654321}), NOW))  # review: person + webhook of the old server
dbx("INSERT INTO list_activity(list_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
    (LO, BOB, "owner", json.dumps({"from": DORA, "to": BOB, "from_name": "Dora", "to_name": "Bob"}), NOW))

# ---------------------------------------------------------------- export, import into the empty organisation
OX1, RK1 = export(A, ORG)
iid, pv = opened(A, OX1, RK1)
taken = {x.get("what") for x in pv.get("taken_areas", [])}
check({"Team chat", "Absences and bookings", "Forms", "Time entries", "Newsletter", "Customer reports"} <= taken,
      f"the preview names the team areas as taken over {sorted(taken)}")
notk = " ".join(str(x) for x in pv.get("not_taken", []))
check("Team chat" not in notk and "Forms" not in notk and "Time entries" not in notk, f"... and not as left out {notk[:200]}")
j = run(A, iid, ORG3, people={EH("bob@example.com"): {"share": True}})
check(j.get("state") == "done", f"import into the empty organisation done {j.get('state')} {j.get('error')}")
W = warnings(j)
NL = one("SELECT id FROM lists WHERE org_id=? AND name='Alpha Projekt'", (ORG3,))
NT = one("SELECT id FROM tasks WHERE list_id=? AND title='Dreh vorbereiten'", (NL,))
check(NL and NT, "list and task are in the new organisation")
# chat
NR = one("SELECT id FROM tchat_rooms WHERE kind='list' AND list_id=?", (NL,))
msgs = dbx("SELECT id, user_id, body, reply_to FROM tchat_msgs WHERE room_id=? ORDER BY id", (NR,))
check(len(msgs) == 3, f"the three messages came along {len(msgs)}")
by = {x["body"]: dict(x) for x in msgs}
check(by.get("Start um neun", {}).get("user_id") == ALICE and by.get("Passt", {}).get("user_id") == BOB, "authors: alice + bob (ticked)")
check(by.get("Ich komme später", {}).get("user_id") is None, "dora (not ticked): the message stays without author")
check(by.get("Passt", {}).get("reply_to") == by.get("Start um neun", {}).get("id"), "the answer points at the new message")
check(T("SELECT user_id FROM tchat_rx WHERE message_id=?", (by.get("Start um neun", {}).get("id"),)) == [(BOB,)], "the chat reaction came along")
# persons' rows: bob yes, dora no
check(one("SELECT COUNT(*) FROM hub_absences WHERE org_id=? AND user_id=?", (ORG3, BOB)) == 1, "bob's absence came along")
check(one("SELECT COUNT(*) FROM hub_absences WHERE org_id=? AND user_id=?", (ORG3, DORA)) == 0, "dora's absence not")
check(one("SELECT COUNT(*) FROM hub_leave_quota WHERE org_id=? AND user_id=? AND days=28", (ORG3, BOB)) == 1, "bob's vacation account")
check(one("SELECT COUNT(*) FROM time_entries WHERE list_id=?", (NL,)) == 2, "time entries of alice + bob, not dora's")
check(one("SELECT COUNT(*) FROM time_sheets WHERE org_id=?", (ORG3,)) == 0 or
      one("SELECT COUNT(*) FROM time_sheets WHERE org_id=? AND user_id=?", (ORG3, DORA)) == 0, "dora's timesheet not")
check("not chosen were not taken over" in W, f"the warning names the left-out rows {W[:300]}")
check(one("SELECT COUNT(*) FROM task_enc_notes WHERE task_id=?", (NT,)) == 1 and
      one("SELECT body FROM task_enc_notes WHERE task_id=? AND user_id=?", (NT, BOB)) == CT, "bob's encrypted note, unchanged")
check(one("SELECT user_id FROM task_people WHERE task_id=?", (NT,)) == BOB, "bob comes along to the new task")
NC2 = one("SELECT id FROM comments WHERE task_id=?", (NT,))
check(one("SELECT user_id FROM comment_reactions WHERE comment_id=?", (NC2,)) == ALICE, "the comment reaction came along")
bks = T("SELECT resource_kind, resource_id FROM hub_bookings WHERE org_id=?", (ORG3,))
check(("user", BOB) in bks and ("user", DORA) not in bks, f"bookings: bob yes, dora no {bks}")  # the equipment: with part A
# shares
NCAL = one("SELECT id FROM ev_cals WHERE org_id=? AND name='Alpha Studio'", (ORG3,))
check(T("SELECT user_id, role FROM ev_cal_members WHERE cal_id=?", (NCAL,)) == [(BOB, "edit")], "calendar share with bob")
NBK = one("SELECT id FROM books WHERE org_id=? AND name='Alpha Kunden'", (ORG3,))
check(T("SELECT user_id FROM book_members WHERE book_id=?", (NBK,)) == [(BOB,)], "address book share with bob")
# forms, customer reports: new links, the address keeps its keyed hash
NF = dbx("SELECT id, token_hash FROM forms WHERE list_id=?", (NL,))
check(len(NF) == 1 and NF[0]["token_hash"] != one("SELECT token_hash FROM forms WHERE list_id=?", (LO,)), "the form has a new link")
NTK = dbx("SELECT email_hash, token_hash, form_id FROM portal_tickets WHERE list_id=?", (NL,))
check(len(NTK) == 1 and NTK[0]["email_hash"] == EHASH and NTK[0]["form_id"] == (NF[0]["id"] if NF else -1),
      "the customer report: same reporter, the new form")
check(one("SELECT COUNT(*) FROM form_entries WHERE form_id=?", (NF[0]["id"] if NF else 0,)) == 1, "the form entry came along")
# rules: bob's maps, dora's is paused
rl = {x["name"]: dict(x) for x in dbx("SELECT name, active, paused_reason, act_val, trig_val FROM list_rules WHERE list_id=?", (NL,))}
NSEC = one("SELECT id FROM sections WHERE list_id=? AND name='Doing'", (NL,))
check(rl.get("Bob übernimmt", {}).get("active") == 1 and json.loads(rl["Bob übernimmt"]["act_val"]).get("user_id") == BOB
      and rl["Bob übernimmt"]["trig_val"] == str(NSEC), f"bob's rule maps column + person {rl.get('Bob übernimmt')}")
check(rl.get("Dora übernimmt", {}).get("active") == 0 and rl["Dora übernimmt"]["paused_reason"] == "assignee", "dora's rule is paused")
# newsletter: no access data, no automatic sync
nc = dbx("SELECT id, secret, auto, error, ws FROM nl_conns WHERE org_id=?", (ORG3,))
check(len(nc) == 1 and nc[0]["secret"] == "" and nc[0]["auto"] == 0 and nc[0]["error"] and nc[0]["ws"] == f"o{ORG3}",
      "the newsletter connection: to be connected again")
seg = dbx("SELECT id, rule FROM nl_segments WHERE org_id=?", (ORG3,))
check(len(seg) == 1 and json.loads(seg[0]["rule"]).get("books") == [NBK], "the segment points at the new address book")
check(one("SELECT COUNT(*) FROM nl_members WHERE seg_id=?", (seg[0]["id"] if seg else 0,)) == 1, "segment members came along")
# filed e-mails: the one with client + project yes (new workspace), dora's private one not
hm = dbx("SELECT ws, owner_id, client_id, list_id FROM hub_mails WHERE org_id=?", (ORG3,))
check(len(hm) == 1 and hm[0]["ws"] == f"o{ORG3}" and hm[0]["list_id"] == NL and hm[0]["owner_id"] == ALICE, f"filed e-mails {hm}")
check(one("SELECT COUNT(*) FROM hub_words w JOIN hub_mails m ON m.id=w.mail_id WHERE m.org_id=?", (ORG3,)) > 0, "the mail search index is rebuilt")
# sprint + task in a further list
NSP = one("SELECT id FROM sprints WHERE list_id=?", (NL,))
check(NSP and one("SELECT sprint_id FROM tasks WHERE id=?", (NT,)) == NSP, "the sprint and the task's sprint")
NL2 = one("SELECT id FROM lists WHERE org_id=? AND name='Alpha Zweitliste'", (ORG3,))
check(T("SELECT list_id, org_id FROM task_links WHERE task_id=?", (NT,)) == [(NL2, ORG3)], "the task is in the second list again")
# notes, notepads, playbook, histories
check(one("SELECT COUNT(*) FROM notes WHERE list_id=? AND title='Kick-off'", (NL,)) == 1, "project note")
check(one("SELECT COUNT(*) FROM list_notepads WHERE list_id=?", (NL,)) == 1, "notepad")
check(one("SELECT body FROM playbooks WHERE list_id=? ORDER BY version DESC LIMIT 1", (NL,)) == "Kunden binnen eines Tages antworten.", "playbook")
check(one("SELECT COUNT(*) FROM activity WHERE task_id=?", (NT,)) >= 1, "task history came along")
# 2.137.1 (#2399): the ids inside the history point at the new rows, unknown old ids are gone
ha = [(k, json.loads(d) if isinstance(d, str) else d) for k, d in T("SELECT kind, data FROM activity WHERE task_id=? ORDER BY id", (NT,))]
check(("ml_add", {"list_id": NL2, "section_id": NSEC, "user_id": BOB}) in ha, f"history: list, column and person mapped, the unknown id dropped {ha}")
check(("assign", {"to": -1, "from": BOB}) in ha, f"history: an assignee not ticked shows as a deleted user {ha}")
check(("subtask", {"title": "Weg"}) in ha, f"history: a task that did not come along is dropped {ha}")
check(("tidy", {"via": "webhook"}) in ha, f"history: a person not ticked and the old webhook are dropped {ha}")
hl = [json.loads(d) if isinstance(d, str) else d for (d,) in T("SELECT data FROM list_activity WHERE list_id=? AND kind='owner'", (NL,))]
check(hl == [{"to": BOB, "from_name": "Dora", "to_name": "Bob"}], f"list history: dora dropped, bob mapped {hl}")
# the organisation's settings (empty target)
check(T("SELECT color, hub_leave_approval FROM orgs WHERE id=?", (ORG3,)) == [("#336699", 1)], "harmless settings came along")
# another organisation's rows are not touched
check(one("SELECT COUNT(*) FROM tchat_msgs WHERE room_id=?", (RID,)) == 3, "the source organisation's chat stays as it was")
check(Do.get(B + f"/api/team/rooms/{NR}/messages").status_code in (403, 404), "dora (not in the new organisation) cannot read its chat")

# ---------------------------------------------------------------- undo of this import
r = A.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok, f"undo {r.text[:160]}")
for t in ("hub_absences", "hub_bookings", "hub_leave_quota", "hub_mails", "nl_conns", "nl_segments", "time_sheets"):
    check(one(f"SELECT COUNT(*) FROM {t} WHERE org_id=?", (ORG3,)) == 0, f"undo removed {t}")
check(not dbx("SELECT 1 FROM lists WHERE org_id=? AND deleted_at IS NULL", (ORG3,)), "undo put the lists into the trash (with chat, forms, notes ...; 2.272.0, #3027)")
check(one("SELECT COUNT(*) FROM hub_absences WHERE org_id=?", (ORG,)) == 2, "the source organisation's rows stay")

# ---------------------------------------------------------------- the round trip: everyone ticked
# (one server: the tasks of an import that is still there are not imported twice, a timesheet is one per person and month --
# so the first import is undone above and the source's timesheets are removed like on a move to another server)
dbx("DELETE FROM time_sheets WHERE org_id=?", (ORG,))
r = A.post(B + "/api/admin/orgs", json={"name": "Delta Leer", "admin_id": ALICE})
ORG4 = r.json().get("id") if r.status_code == 201 else 0
iid4, _pv = opened(A, OX1, RK1)
j = run(A, iid4, ORG4, people={EH("bob@example.com"): {"share": True}, EH("dora@example.com"): {"share": True}})
check(j.get("state") == "done", f"import with everyone ticked done {j.get('error')}")
OX4, RK4 = export(A, ORG4)
strict = os.environ.get("P2137C_STRICT", "1") != "0"  # 2.137.0: parts A and B are merged -> every entry counts
Z1, Z4 = open_archive(OX1, RK1), open_archive(OX4, RK4)
diffs = compare(Z1, Z4)
bad, other = [], []
for n, t in diffs:
    dep = DEPENDS.get(n)
    later = dep and norm_archive_count(Z1, dep) and not norm_archive_count(Z4, dep)  # its rows point at a part not merged yet
    (bad if n.startswith(MINE) and not later or strict else other).append(f"{n}: {t}")
check(not bad, "round trip: every entry equal after export -> import -> export: " + "; ".join(bad)[:1500])
for x in other:  # parts A / B (not counted until P2137C_STRICT=1)
    print("FAIL? not counted (other part): ROUNDTRIP " + x[:400], flush=True)
print(f"round trip: {len(diffs)} differences, {len(bad)} counted", flush=True)
r = A.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok and not dbx("SELECT 1 FROM lists WHERE org_id=? AND deleted_at IS NULL", (ORG4,)), f"undo of the round trip import (lists into the trash, #3027) {r.text[:160]}")

# ---------------------------------------------------------------- into the private space: only alice's own rows
iid, _pv = opened(A, OX1, RK1)
j = run(A, iid, "private", people={EH("bob@example.com"): {"share": True}})
check(j.get("state") == "done", f"private import done {j.get('error')}")
PL = one("SELECT id FROM lists WHERE owner_id=? AND org_id IS NULL AND name='Alpha Projekt'", (ALICE,))
PB = one("SELECT id FROM orgs WHERE personal_of=?", (ALICE,))
check(PL and one("SELECT COUNT(*) FROM notes WHERE list_id=?", (PL,)) == 1 and one("SELECT COUNT(*) FROM forms WHERE list_id=?", (PL,)) == 1,
      "private: project note + form on the private list")
check(T("SELECT user_id FROM time_entries WHERE list_id=?", (PL,)) == [(ALICE,)], "private: only alice's time entry")
check(one("SELECT COUNT(*) FROM hub_absences WHERE org_id=?", (PB,)) == 0 if PB else True, "private: nobody else's absence in alice's own office")
check(one("SELECT COUNT(*) FROM nl_conns WHERE owner_id=? AND org_id IS NULL", (ALICE,)) == 1, "private: the newsletter connection is alice's")
check(one("SELECT COUNT(*) FROM portal_tickets WHERE list_id=? AND org_id IS NULL AND owner_id=?", (PL, ALICE)) == 1, "private: the customer report")
check(T("SELECT color FROM orgs WHERE personal_of=?", (ALICE,)) in ([], [("",)]), "private: no organisation settings")
r = A.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok and not dbx("SELECT 1 FROM lists WHERE id=? AND deleted_at IS NULL", (PL,)), "private: undo (list into the trash, #3027)")

# ---------------------------------------------------------------- a freelancer imports it privately
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
iid, pv = opened(Fr, OX1, RK1)
j = run(Fr, iid, "private")
check(j.get("state") == "done", f"freelancer: import done {j.get('error')}")
FL = one("SELECT id FROM lists WHERE owner_id=? AND name='Alpha Projekt'", (FID,))
check(FL and one("SELECT COUNT(*) FROM notes WHERE list_id=?", (FL,)) == 1, "freelancer: the project note")
check(one("SELECT COUNT(*) FROM tchat_msgs m JOIN tchat_rooms r ON r.id=m.room_id WHERE r.list_id=? AND m.user_id IS NOT NULL", (FL,)) == 0,
      "freelancer: chat messages without other people as authors")
check(one("SELECT COUNT(*) FROM time_entries WHERE list_id=?", (FL,)) == 0, "freelancer: no time entries of others")
check(not dbx("SELECT 1 FROM org_members WHERE user_id=?", (FID,)), "freelancer: still in no organisation")

if FAILS:  # the container log once (was in the suite's own check(), 2.206.0 #2762)
    ct = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
    print(subprocess.run(["docker", "logs", "--tail", "60", ct], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True).stdout[-6000:], flush=True)
print(f"p2137_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
