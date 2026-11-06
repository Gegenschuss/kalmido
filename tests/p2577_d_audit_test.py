#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.577.0 D (#4708): the low findings of audit #2822, one block per finding. Own container (mode workspaces).
Invented names only (example.com).
freelancer-matrix: pim
 - (1) contacts deleted for good (bulk purge) only by the book's owner/admin: a person with 'edit' through a share may
   put contacts into the trash and take them out, but not delete them for good (403); the owner can
usage: p2577_d_audit_test.py <datadir>"""
import json
import os
import select
import subprocess
import sys
import threading

import kt
from kt import B, CT, check
from freelancer_fixture import FEATURES, freelancer, login

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2577D")

A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": kt.PASSWORD, "email": "bob@example.com"})
check(r.ok, f"setup: bob {r.status_code} {r.text[:120]}")
BOB = r.json()["id"]
Bo = login(B, "bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
FID, Fr = freelancer(B, A)


def box(code):
    """python code inside the app container (system context, a fresh process) -> its output."""
    out = subprocess.run(box_cmd(code), capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def box_cmd(code):
    body = "\n".join("    " + x for x in code.split("\n"))
    return ["docker", "exec", "-i", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\n"
            "c = connect()\nwith system_ctx(c):\n" + body + "\nc.commit()\nc.close()"]


def while_held(code, req):
    """code runs in the container in one transaction (it takes a lock and changes a row); while it holds it, req() is sent.
    The holder waits until a backend waits for a lock (-> 'waiter') or req() came back without waiting (-> 'nowait'), then
    commits. -> (waited, req's response)."""
    held = ("import select, sys\n" + code + "\nprint('held', flush=True)\n"
            "while True:\n"
            "    if c.execute(\"SELECT COUNT(*) FROM pg_locks WHERE NOT granted\").fetchone()[0]:\n"
            "        print('waiter', flush=True)\n        break\n"
            "    if select.select([sys.stdin], [], [], 0.05)[0]:\n"
            "        print('nowait', flush=True)\n        break")
    p = subprocess.Popen(box_cmd(held), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    line = ""
    while "held" not in line:  # the container's start notes come first: wait for the real state
        line = p.stdout.readline()
        if not line:
            return False, None
    res = {}

    def go():
        res["r"] = req()
        try:
            p.stdin.write("done\n")
            p.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass
    th = threading.Thread(target=go)
    th.start()
    rest = _rest(p)
    th.join(90)
    return "waiter" in rest, res.get("r")


def _rest(p):
    out = ""
    while True:
        line = p.stdout.readline()
        if not line:
            break
        out += line
        if "waiter" in line or "nowait" in line:
            break
    out += p.stdout.read() if p.wait(timeout=90) is not None else ""
    return out


def gone(cid):
    rows = kt.dbx("SELECT deleted_at FROM contacts WHERE id=?", (cid,))
    return not rows


# ================================================================== (1) purge only for the owner
r = Fr.post(B + "/api/books", json={"name": "Frida's contacts", "org_id": None})
check(r.status_code == 201, f"(1) setup: Frida's private book {r.status_code} {r.text[:120]}")
BK = r.json()["id"]
CIDS = []
for n in ("Anna Example", "Ben Example"):
    r = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": n, "emails": [{"value": n.split()[0].lower() + "@example.com"}]})
    check(r.status_code == 201, f"(1) setup: contact {n}")
    CIDS.append(r.json()["id"] if r.ok else 0)
r = Fr.put(B + f"/api/books/{BK}/members", json={"user_id": BOB, "role": "edit"})
check(r.ok, f"(1) setup: Frida shares the book with Bob (edit) {r.status_code} {r.text[:120]}")
r = Bo.post(B + "/api/contacts/bulk", json={"action": "delete", "ids": CIDS})
check(r.ok, f"(1) Bob (edit) puts both into the trash {r.status_code} {r.text[:120]}")
r = Bo.post(B + "/api/contacts/bulk", json={"action": "purge", "ids": CIDS})
check(r.status_code == 403 and not any(gone(x) for x in CIDS), f"(1) Bob (edit) cannot delete them for good: 403 {r.status_code}")
r = Bo.post(B + "/api/contacts/bulk", json={"action": "undelete", "ids": [CIDS[1]]})
check(r.ok, f"(1) Bob (edit) still takes one out of the trash {r.status_code}")
r = Fr.post(B + "/api/contacts/bulk", json={"action": "purge", "ids": [CIDS[0]]})
check(r.ok and gone(CIDS[0]), f"(1) the owner (person without an organisation) deletes for good {r.status_code} {r.text[:120]}")

# ================================================================== (2) write locks before the read
# a folder move of the wiki waits for a page's save lock and moves the page under the name saved meanwhile
pw = Fr.post(B + "/api/wiki/pages", json={"path": "Ordner/Alt", "body": "Text"}).json()["id"]
waited, r = while_held(f"from kalmido.core.pg import write_lock\nwrite_lock(c, 'wiki-{pw}')\n"
                       f"c.execute(\"UPDATE wiki_pages SET path='Ordner/Umbenannt' WHERE id=?\", ({pw},))",
                       lambda: Fr.post(B + "/api/wiki/move", json={"space": "private", "from": "Ordner", "to": "Neu"}))
path = (kt.dbx("SELECT path FROM wiki_pages WHERE id=?", (pw,)) or [[""]])[0][0]
check(waited and r is not None and r.ok, f"(2) the wiki folder move waited for the page's save lock {waited} {r.status_code if r is not None else '-'}")
check(path == "Neu/Umbenannt", f"(2) ... and moved the page with the name saved meanwhile (not the one read before): {path}")

# a group rename of the contacts re-reads each contact under its lock: a change saved meanwhile stays
r = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Gruppen Example", "groups": ["Kunden"]})
CG = r.json()["id"] if r.status_code == 201 else 0
waited, r = while_held(f"r = c.execute('SELECT id FROM contacts WHERE id=? FOR UPDATE', ({CG},)).fetchone()\n"
                       f"import json\nc.execute('UPDATE contacts SET groups=? WHERE id=?', (json.dumps(['Kunden', 'Presse']), {CG}))",
                       lambda: Fr.post(B + "/api/contacts/groups", json={"action": "rename", "name": "Kunden", "to": "Stammkunden"}))
g = json.loads((kt.dbx("SELECT groups FROM contacts WHERE id=?", (CG,)) or [["[]"]])[0][0] or "[]")
check(waited and r is not None and r.ok, f"(2) the group rename waited for the contact's lock {waited} {r.text[:120] if r is not None else '-'}")
check(sorted(g) == ["Presse", "Stammkunden"], f"(2) ... and kept the group added meanwhile: {g}")

# a new field of a project: the count, its place and the project's columns under the project's field lock
LID = Fr.post(B + "/api/lists", json={"name": "Felder 4708"}).json()["id"]
waited, r = while_held(f"from kalmido.core.pg import write_lock\nwrite_lock(c, 'list-fields-{LID}')",
                       lambda: Fr.post(B + f"/api/lists/{LID}/fields", json={"name": "Budget", "type": "number"}))
check(waited and r is not None and r.status_code in (200, 201), f"(2) a new field waits for the project's field lock {waited} {r.status_code if r is not None else '-'}")

# ================================================================== (3) file versions with expect_version
r = Fr.post(B + "/api/files/upload", files={"file": ("Bericht.txt", b"eins")})
FN = r.json()["items"][0]["id"] if r.status_code == 201 else 0


def cur_version():
    return (kt.dbx("SELECT cur_version FROM fs_nodes WHERE id=?", (FN,)) or [[0]])[0][0]


r = Fr.post(B + f"/api/files/nodes/{FN}/versions", files={"file": ("Bericht.txt", b"zwei")}, data={"expect_version": "1"})
check(r.status_code == 201 and cur_version() == 2, f"(3) a new version with the version read (1) is stored {r.status_code} {r.text[:120]}")
r = Fr.post(B + f"/api/files/nodes/{FN}/versions", files={"file": ("Bericht.txt", b"veraltet")}, data={"expect_version": "1"})
check(r.status_code == 409 and (r.json().get("current") or {}).get("version") == 2 and cur_version() == 2,
      f"(3) a new version on top of an older one read -> 409 with the file now, nothing stored {r.status_code} {r.text[:160]}")
r = Fr.post(B + "/api/files/upload", files={"file": ("Bericht.txt", b"gleicher Name")}, data={"expect_version": "1"})
check(r.status_code == 409 and cur_version() == 2, f"(3) an upload of the same name with an older version read -> 409 {r.status_code}")
r = Fr.post(B + f"/api/files/nodes/{FN}/versions/1/restore", json={"expect_version": 1})
check(r.status_code == 409 and cur_version() == 2, f"(3) a restore with an older version read -> 409 {r.status_code}")
r = Fr.post(B + f"/api/files/nodes/{FN}/versions", files={"file": ("Bericht.txt", b"x")}, data={"expect_version": "zwei"})
check(r.status_code == 400 and cur_version() == 2, f"(3) a version that is no number -> 400 {r.status_code}")
r = Fr.post(B + f"/api/files/nodes/{FN}/versions", files={"file": ("Bericht.txt", b"drei")})
check(r.status_code == 201 and cur_version() == 3, f"(3) without expect_version (old clients) as before {r.status_code}")
r = Fr.post(B + f"/api/files/nodes/{FN}/versions/1/restore", json={"expect_version": 3})
check(r.ok and cur_version() == 4, f"(3) a restore with the current version {r.status_code} {r.text[:120]}")

# ================================================================== (6) the event calendar link's secret as a hash
import requests  # noqa: E402 (only this block reads the feed without login)
from urllib.parse import urlparse  # noqa: E402

pub = requests.Session()
FCAL = Fr.post(B + "/api/evcals", json={"name": "Frida Kalender"}).json()["id"]
Fr.post(B + "/api/events", json={"cal_id": FCAL, "title": "Feedtermin", "start": "2026-11-20T10:00", "end": "2026-11-20T11:00"})
j = Fr.post(B + f"/api/evcals/{FCAL}/feed", json={"action": "create"}).json()
U = j.get("url") or ""
fid, sec = (urlparse(U).path.rsplit("/", 1)[-1][:-4].split(".", 1) + [""])[:2] if U else ("0", "")
row = (kt.dbx("SELECT secret, secret_hash FROM ev_cal_feeds WHERE id=?", (int(fid or 0),)) or [["?", None]])[0]
check(bool(sec) and row[0] == "" and row[1] and sec not in (row[1] or ""), f"(6) the link's secret is stored only as a hash: {row[0]!r}")
r = pub.get(B + urlparse(U).path) if U else None
check(r is not None and r.status_code == 200 and "Feedtermin" in r.text, f"(6) the link works with the hashed secret {r.status_code if r is not None else '-'}")
g = Fr.get(B + f"/api/evcals/{FCAL}/feed").json()
check(g.get("url") is None and g.get("active") is True and g.get("created_at"), f"(6) later the app sees 'active since', not the address: {g}")
check(pub.get(B + f"/ical/ev/{fid}.{'x' * len(sec)}.ics").status_code == 404, "(6) a wrong secret: 404")
# a link from before (plain secret in the row): the start turns it into a hash, the address keeps working (one-way step)
kt.dbx("UPDATE ev_cal_feeds SET secret=?, secret_hash=NULL WHERE id=?", ("altesGeheimnis4708abcdefghijklmnopqrstuv", int(fid or 0)))
out = box("from kalmido.core.tokenhash import tkh_migrate\nprint('migrated', tkh_migrate(c))")
row = (kt.dbx("SELECT secret, secret_hash FROM ev_cal_feeds WHERE id=?", (int(fid or 0),)) or [["?", None]])[0]
import hashlib  # noqa: E402
check(row[0] == "" and row[1] == hashlib.sha256(b"altesGeheimnis4708abcdefghijklmnopqrstuv").hexdigest(),
      f"(6) the start hashes a plain secret left from before {[x for x in out.splitlines() if 'migrated' in x or 'Error' in x]} {row[0]!r}")
r = pub.get(B + f"/ical/ev/{fid}.altesGeheimnis4708abcdefghijklmnopqrstuv.ics")
check(r.status_code == 200, f"(6) ... and the old address still works {r.status_code}")
U2 = Fr.post(B + f"/api/evcals/{FCAL}/feed", json={"action": "rotate"}).json().get("url") or ""
check(U2 and pub.get(B + urlparse(U2).path).status_code == 200 and r.status_code == 200
      and pub.get(B + f"/ical/ev/{fid}.altesGeheimnis4708abcdefghijklmnopqrstuv.ics").status_code == 404, "(6) rotate: a new address, the old one stops")

# ================================================================== (4) who changed it last: events, contacts, wiki versions
r = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Spur Example"})
CS = r.json()["id"] if r.status_code == 201 else 0
check(r.status_code == 201 and r.json().get("updated_by") == FID, f"(4) a new contact names who made it: updated_by {r.json().get('updated_by') if r.ok else r.text[:100]}")
r = Bo.patch(B + f"/api/contacts/{CS}", json={"note": "von Bob"})
check(r.ok and r.json().get("updated_by") == BOB and kt.dbx("SELECT updated_by FROM contacts WHERE id=?", (CS,))[0][0] == BOB,
      f"(4) Bob's change (edit share) names Bob {r.status_code} {r.text[:120]}")
r = Fr.post(B + "/api/contacts/bulk", json={"action": "set", "ids": [CS], "org": "Spur GmbH"})
check(r.ok and kt.dbx("SELECT updated_by FROM contacts WHERE id=?", (CS,))[0][0] == FID, f"(4) a bulk change names its writer {r.status_code} {r.text[:120]}")
r = Fr.post(B + "/api/events", json={"cal_id": FCAL, "title": "Spurtermin", "start": "2026-11-21T10:00", "end": "2026-11-21T11:00"})
EV = r.json()["id"] if r.status_code == 201 else 0
check(r.status_code == 201 and r.json().get("updated_by") == FID, f"(4) a new event names who made it {r.text[:120]}")
# the wiki history marks a version an agent account wrote
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "spurhelfer", "display_name": "Spur Helfer"}).json()
pv = Fr.post(B + "/api/wiki/pages", json={"path": "Spurseite", "body": "eins"}).json()["id"]
vs = Fr.get(B + f"/api/wiki/pages/{pv}/versions").json().get("versions") or []
check(vs and vs[0].get("agent") is False, f"(4) a person's version is not marked as an agent's {vs[:1]}")
kt.dbx("UPDATE wiki_versions SET created_by=? WHERE page_id=?", (ag.get("id"), pv))
vs = Fr.get(B + f"/api/wiki/pages/{pv}/versions").json().get("versions") or []
check(vs and vs[0].get("agent") is True, f"(4) a version an agent account wrote is marked as an agent's {vs[:1]}")

# ================================================================== (5) a letter's change in the office log (as documents)
Fr.patch(B + "/api/settings", json={"features": FEATURES + ",office,clients", "workspace": "private"})
r = Fr.post(B + "/api/office/letters", json={"subject": "Anfrage 4708", "body": "Erster Text"})
LT = (r.json().get("id") or (r.json().get("letter") or {}).get("id") or 0) if r.status_code in (200, 201) else 0
check(bool(LT), f"(5) setup: a letter in the personal office {r.status_code} {r.text[:120]}")
cur = Fr.get(B + f"/api/office/letters/{LT}").json()
r = Fr.patch(B + f"/api/office/letters/{LT}", json={"subject": "Anfrage 4708 B", "expect_updated_at": cur.get("updated_at") or (cur.get("letter") or {}).get("updated_at")})
check(r.ok, f"(5) the letter changes {r.status_code} {r.text[:120]}")
logs = kt.dbx("SELECT action, user_id FROM office_doc_log WHERE target='letter' AND action='update'")
check(len(logs) == 1 and logs[0][1] == FID, f"(5) the change is in the office log with its writer {logs}")
h = Fr.get(B + f"/api/office/letters/{LT}/history")
check(h.ok and "subject" in h.text, f"(5) ... and in the letter's history (#4711) {h.status_code}")

# ================================================================== (10) "Stop reminding" from a push sends the nag it saw (_prev)
out = box("from kalmido.notify.push import webpush_payload\nimport json\nprint('P', json.dumps(webpush_payload('T', 'M', 4, task=7, nag='')))")
pl = json.loads(next((x[2:] for x in out.splitlines() if x.startswith("P ")), "{}"))
check(pl.get("task") == 7 and pl.get("nag") == "", f"(10) a nag push carries the task's nag setting {pl}")
LN = Fr.post(B + "/api/lists", json={"name": "Erinnern 4708"}).json()["id"]
TN = Fr.post(B + "/api/tasks", json={"title": "Nervig", "list_id": LN, "nag": "15"}).json()["id"]
Fr.patch(B + f"/api/tasks/{TN}", json={"nag": "60"})  # changed on another device after the push went out
r = Fr.patch(B + f"/api/tasks/{TN}", json={"nag": "off", "_prev": {"nag": "15"}})
nag = kt.dbx("SELECT nag FROM tasks WHERE id=?", (TN,))[0][0]
check(r.ok and r.json().get("conflicts") and nag == "60", f"(10) the push's nag-off with an old _prev is a conflict (the service worker opens the app) {nag} {r.text[:120]}")
r = Fr.patch(B + f"/api/tasks/{TN}", json={"nag": "off", "_prev": {"nag": "60"}})
check(r.ok and not r.json().get("conflicts") and kt.dbx("SELECT nag FROM tasks WHERE id=?", (TN,))[0][0] == "off", f"(10) with the current _prev it stops {r.text[:120]}")

# @@NEXT@@

sys.exit(kt.done("p2577_d_audit"))
