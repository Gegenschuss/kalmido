#!/usr/bin/env python3
"""2.239.0 API tests, part D (#2874 part 2, #2866 schema): office records outlive what they point to, the clean-up runs leave
them alone, an organisation's feeds / section templates outlive their creator's account. Own container (start.sh, mode
workspaces). Invented accounts only (example.com); the person without an organisation (freelancer fixture, private clients,
projects and receipts) does every step that exists for her.
 - a client with a signed data protection sheet is archived instead of deleted (purge 409, the trash run keeps it); one with
   an open sheet is deleted as before, the sheet goes along
 - a project deleted for good: its booked receipt keeps the project's name (rc_receipts.list_name), an unbooked one not
 - a closed logbook month: its vehicle cannot be deleted under it (foreign key without cascade, set once at the start)
 - the deletion of an organisation's only admin: its feed and section template go to a member, a private template goes
 - the hosted retention bypass of user_purge only for the admin's deletion (gated), not for the other callers
 - log clean-up: the file log of a receipt stays, the one of a plain file goes; versions of an unbooked receipt stay
 - orphan sweep with KALMIDO_ORPHAN_DAYS=0: a file younger than an hour stays, an older one goes
 - a reply to a data protection sheet: its text at the sheet, not in the office log
freelancer-matrix: office
usage: p2239_d_aufbewahrung_test.py <datadir>      (P2239D_NOSTART=1: a running server on KALMIDO_TEST_PORT)
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs,files,feeds"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # an UPDATE without rows to read
            return []
    finally:
        c.close()


def box(code, env=()):
    """Runs python code inside the app container (system context, a fresh process)."""
    body = "\n".join("    " + x for x in code.split("\n"))
    cmd = ["docker", "exec"]
    for e in env:
        cmd += ["-e", e]
    out = subprocess.run(cmd + [CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\n"
                                "c = connect()\nwith system_ctx(c):\n" + body + "\nc.commit()\nc.close()"], capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def ago(hours=0, days=0):
    return (datetime.now(timezone.utc) - timedelta(hours=hours, days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def doc(s, ws, name):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": "119.00", "date": ago(days=5)[:10]}).ok
    return nid


if os.environ.get("P2239D_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FID, Fr = freelancer(B, A, features=FEAT)
Fr.get(B + "/api/office/docs?kind=invoice")  # the personal office exists from its first use
PO = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
WS = f"u{FID}"
NOW = ago()

# ================================================================== a client with a signed data protection sheet
C1 = Fr.post(B + "/api/clients", json={"name": "Signiert Test"}).json()["id"]
sql("INSERT INTO office_privacy_sheets(org_id, client_id, kind, status, signed_at, created_by, created_at, updated_at) "
    "VALUES(?,?,'dpa','signed',?,?,?,?)", (PO, C1, NOW, FID, NOW, NOW))
r = Fr.delete(B + f"/api/clients/{C1}")
check(r.ok and sql("SELECT archived, deleted_at FROM clients WHERE id=?", (C1,)) == [(1, None)],
      f"client: a signed sheet keeps the client: archived, not in the trash {r.text[:160]}")
check(Fr.delete(B + f"/api/clients/{C1}/purge").status_code == 404, "client: ... so no final delete")
# signed after the client went to the trash: the final delete and the trash run keep it
C4 = Fr.post(B + "/api/clients", json={"name": "Spaet Test"}).json()["id"]
assert Fr.delete(B + f"/api/clients/{C4}").ok
sql("INSERT INTO office_privacy_sheets(org_id, client_id, kind, status, signed_at, created_by, created_at, updated_at) "
    "VALUES(?,?,'dpa','signed',?,?,?,?)", (PO, C4, NOW, FID, NOW, NOW))
r = Fr.delete(B + f"/api/clients/{C4}/purge")
check(r.status_code == 409 and sql("SELECT archived, deleted_at FROM clients WHERE id=?", (C4,)) == [(1, None)],
      f"client: purge of one signed since -> 409, archived instead {r.status_code} {r.text[:160]}")
check(sql("SELECT COUNT(*) FROM office_privacy_sheets WHERE client_id=?", (C1,))[0][0] == 1
      and sql("SELECT COUNT(*) FROM office_privacy_sheets WHERE client_id=?", (C4,))[0][0] == 1, "client: ... the signed sheets stay")
C3 = Fr.post(B + "/api/clients", json={"name": "Lauf Test"}).json()["id"]
assert Fr.delete(B + f"/api/clients/{C3}").ok
sql("INSERT INTO office_privacy_sheets(org_id, client_id, kind, status, created_by, created_at, updated_at, signed_node_id) "
    "VALUES(?,?,'consent','sent',?,?,?,1)", (PO, C3, FID, NOW, NOW))
sql("UPDATE clients SET deleted_at=? WHERE id=?", (ago(days=40), C3))
out = box("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))", ("KALMIDO_PURGE_TRASH=1",))
check(sql("SELECT COUNT(*) FROM clients WHERE id=?", (C3,))[0][0] == 1, f"client: the trash run keeps one with a signed file {out[-200:]}")
# freelancer: an open sheet does not hold the client (deleted as before, the sheet goes along)
C2 = Fr.post(B + "/api/clients", json={"name": "Offen Test"}).json()["id"]
sql("INSERT INTO office_privacy_sheets(org_id, client_id, created_by, created_at, updated_at) VALUES(?,?,?,?,?)", (PO, C2, FID, NOW, NOW))
assert Fr.delete(B + f"/api/clients/{C2}").ok
check(Fr.delete(B + f"/api/clients/{C2}/purge").ok and not sql("SELECT 1 FROM clients WHERE id=?", (C2,)), "client: with an open sheet deleted for good")
check(sql("SELECT COUNT(*) FROM office_privacy_sheets WHERE client_id=?", (C2,))[0][0] == 0, "client: ... the open sheet goes along")

# ================================================================== a project deleted for good: booked receipts keep its name
LID = Fr.post(B + "/api/lists", json={"name": "Projekt Nord", "kind": "project"}).json()["id"]
R1, R2 = doc(Fr, WS, "gebucht.pdf"), doc(Fr, WS, "offen.pdf")
r = Fr.put(B + f"/api/docs/{R1}/receipt", json={"project_id": LID, "category": "Material", "vat_pct": "19", "keep": True})
check(r.ok, f"project: (setup) a booked receipt of the project {r.status_code} {r.text[:160]}")
r = Fr.put(B + f"/api/docs/{R2}/receipt", json={"project_id": LID, "category": "Material", "keep": True})
check(r.ok, f"project: (setup) an unbooked receipt of the project {r.status_code} {r.text[:160]}")
L2 = Fr.post(B + "/api/lists", json={"name": "Projekt Sued", "kind": "project"}).json()["id"]
R3 = doc(Fr, WS, "sued.pdf")
check(Fr.put(B + f"/api/docs/{R3}/receipt", json={"project_id": L2, "vat_pct": "7", "keep": True}).ok, "project: (setup) a second booked receipt")
# both ways a project row is deleted for good (the trash's final delete, an undo of a new project)
out = box(f"from kalmido.lists.lists import list_purge\nfrom kalmido.lists.projects import list_row_purge\n"
          f"print('gone', list_purge(c, {LID}, None)[0] is None or True, list_row_purge(c, {L2}, []))")
check("gone True 1" in out and not sql("SELECT 1 FROM lists WHERE id IN (?, ?)", (LID, L2)), f"project: (setup) deleted for good {out[-300:]}")
check(sql("SELECT list_id, list_name FROM rc_receipts WHERE node_id=?", (R3,)) == [(None, "Projekt Sued")], "project: ... also through list_row_purge")
check(sql("SELECT list_id, list_name FROM rc_receipts WHERE node_id=?", (R1,)) == [(None, "Projekt Nord")], "project: the booked receipt keeps the name")
check(sql("SELECT list_id, list_name FROM rc_receipts WHERE node_id=?", (R2,)) == [(None, None)], "project: the unbooked one does not")

# ================================================================== a closed logbook month outlives its vehicle
out = box("r = c.execute(\"SELECT con.confdeltype FROM pg_constraint con JOIN pg_class t ON t.oid=con.conrelid JOIN pg_attribute a ON "
          "a.attrelid=t.oid AND a.attnum=ANY(con.conkey) WHERE con.contype='f' AND t.relname='office_drive_closed' AND a.attname='vehicle_id'\").fetchall()\n"
          "from kalmido.admin.dataretention import drt_fk_once\nprint('fk', [x[0] for x in r], drt_fk_once(c))")
check("fk ['a'] 0" in out, f"logbook: the vehicle key has no cascade, the start step is idempotent {out[-200:]}")
VID = sql("INSERT INTO office_vehicles(org_id, name, created_at, updated_at) VALUES(?,?,?,?) RETURNING id", (PO, "Testwagen", NOW, NOW))[0][0]
sql("INSERT INTO office_drive_closed(org_id, vehicle_id, month, closed_at) VALUES(?,?,?,?)", (PO, VID, "2026-01", NOW))
try:
    sql("DELETE FROM office_vehicles WHERE id=?", (VID,))
    gone = False
except Exception:  # noqa: BLE001 -- the foreign key refuses
    gone = True
check(gone and sql("SELECT COUNT(*) FROM office_drive_closed WHERE vehicle_id=?", (VID,))[0][0] == 1, "logbook: the closed month stays, the vehicle cannot go")

# ================================================================== an organisation's only admin is deleted
ids = {}
for u in ("bob", "carl", "gina"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
OG = sql("INSERT INTO orgs(name, created_at) VALUES(?,?) RETURNING id", ("Team Test", NOW))[0][0]
ALICE = sql("SELECT id FROM users WHERE username='alice'")[0][0]
# the instance admin shares the organisation (else the members are the organisation admins' to manage), as a member
for u, role in (("bob", "admin"), ("gina", "guest"), ("carl", "member")):
    sql("INSERT INTO org_members(org_id, user_id, role) VALUES(?,?,?)", (OG, ids[u], role))
sql("INSERT INTO org_members(org_id, user_id, role) VALUES(?,?,'member')", (OG, ALICE))
F1 = sql("INSERT INTO rss_feeds(user_id, org_id, url, created_at) VALUES(?,?,?,?) RETURNING id", (ids["bob"], OG, "https://example.com/team.xml", NOW))[0][0]
F2 = sql("INSERT INTO rss_feeds(user_id, url, created_at) VALUES(?,?,?) RETURNING id", (ids["bob"], "https://example.com/own.xml", NOW))[0][0]
T1 = sql("INSERT INTO section_templates(user_id, org_id, name, created_at, updated_at) VALUES(?,?,?,?,?) RETURNING id", (ids["bob"], OG, "Team", NOW, NOW))[0][0]
T2 = sql("INSERT INTO section_templates(user_id, name, created_at, updated_at) VALUES(?,?,?,?) RETURNING id", (ids["bob"], "Privat", NOW, NOW))[0][0]
r = A.delete(B + f"/api/users/{ids['bob']}")
check(r.ok, f"account: (setup) the only admin deleted {r.status_code} {r.text[:200]}")
check(sql("SELECT user_id FROM rss_feeds WHERE id=?", (F1,)) == [(ALICE,)], "account: the organisation's feed goes to a member (no admin left)")
check(sql("SELECT user_id FROM section_templates WHERE id=?", (T1,)) == [(ALICE,)], "account: the organisation's section template too")
check(not sql("SELECT 1 FROM rss_feeds WHERE id=?", (F2,)) and not sql("SELECT 1 FROM section_templates WHERE id=?", (T2,)),
      "account: the private feed and template go with the account")

# ================================================================== the hosted bypass only after the retention gate
out = box("import kalmido.admin.hosting as HO\nimport kalmido.accounts.users as U\nfrom kalmido.office.olock import OLK_BYPASS\n"
          "HO.hosted = lambda: True\nseen = []\nU._user_purge = lambda c, uid: seen.append(OLK_BYPASS.get()) or []\n"
          "U.user_purge(c, 0)\nU.user_purge(c, 0, gated=True)\nprint('bypass', seen, OLK_BYPASS.get())")
check("bypass [False, True] False" in out, f"account: hosted bypass only for the gated deletion {out[-300:]}")

# ================================================================== the clean-up runs leave office records alone
P1 = Fr.post(B + "/api/files/upload", files={"file": ("plain.txt", b"plain")}).json()["items"][0]["id"]
OLD = ago(days=900)
for nid in (R1, P1):
    sql("INSERT INTO fs_log(node_id, user_id, action, at) VALUES(?,?,?,?)", (nid, FID, "p2239d", OLD))
out = box("from kalmido.admin.dataretention import lgc_tick\nprint('logs', lgc_tick(c, True))", ("KALMIDO_PURGE_LOGS=1",))
check(sql("SELECT COUNT(*) FROM fs_log WHERE node_id=? AND action='p2239d'", (R1,))[0][0] == 1, f"logs: the receipt's file log stays {out[-200:]}")
check(sql("SELECT COUNT(*) FROM fs_log WHERE node_id=? AND action='p2239d'", (P1,))[0][0] == 0, "logs: a plain file's old log goes")
for nid in (R2, P1):
    for no in range(100, 122):
        sql("INSERT INTO fs_versions(node_id, no, path, size, mime, sha256, created_by, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (nid, no, f"fs/p2239d-{nid}-{no}", 1, "application/pdf", "", FID, NOW))
out = box(f"from kalmido.admin.dataretention import orf_prune_versions\nprint('prune', orf_prune_versions(c, {R2}, False)[0], orf_prune_versions(c, {P1}, False)[0] > 0)")
check("prune 0 True" in out, f"versions: an unbooked receipt keeps every version, a plain file loses the oldest {out[-300:]}")
sql("DELETE FROM fs_versions WHERE path LIKE 'fs/p2239d-%'")
mk = ("import os, time\nfrom kalmido.core.config import ATT_DIR\nd = os.path.join(ATT_DIR, '900777')\nos.makedirs(d, exist_ok=True)\n"
      "for n, age in (('fresh.bin', 60), ('old.bin', 7200)):\n    p = os.path.join(d, n)\n    open(p, 'wb').write(b'x')\n"
      "    t = time.time() - age\n    os.utime(p, (t, t))")
box(mk)
P = lambda name: os.path.join(DATA, "attachments", "900777", name)  # noqa: E731
out = box("from kalmido.admin.dataretention import orf_tick\nprint('orphans', orf_tick(c, True))", ("KALMIDO_PURGE_FILES=1", "KALMIDO_ORPHAN_DAYS=0"))
check(os.path.exists(P("fresh.bin")), f"orphans: with 0 days a file of a minute stays {out[-200:]}")
check(not os.path.exists(P("old.bin")), "orphans: ... one of two hours goes")

# ================================================================== a reply to a data protection sheet
S1 = sql("INSERT INTO office_privacy_sheets(org_id, kind, status, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?) RETURNING id",
         (PO, "dpa", "sent", FID, NOW, NOW))[0][0]
out = box("import email.message\nfrom kalmido.office.privacy import dsb_reply_note, dsb_replies\n"
          "m = email.message.EmailMessage()\nm['From'] = 'Kunde <kunde@example.com>'\n"
          f"r = c.execute('SELECT * FROM office_privacy_sheets WHERE id=?', ({S1},)).fetchone()\n"
          "dsb_reply_note(c, r, m, 'Re: AVV', 'Ich widerrufe hiermit.')\n"
          f"print('reply', dsb_replies(c, {PO}).get({S1}, {{}}).get('text'))")
check("reply Ich widerrufe hiermit." in out, f"reply: the text is shown with the sheet {out[-300:]}")
log = sql("SELECT detail FROM office_doc_log WHERE org_id=? AND action='privacy_reply' ORDER BY id DESC LIMIT 1", (PO,))
check(log and "widerrufe" not in log[0][0] and "kunde@example.com" not in log[0][0] and '"chars": 22' in log[0][0],
      f"reply: the office log notes only the event and the length {log}")
check(sql("SELECT review FROM office_privacy_sheets WHERE id=?", (S1,)) == [(2,)], "reply: the sheet asks for a check")

print(f"p2239_d_aufbewahrung: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
