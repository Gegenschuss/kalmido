#!/usr/bin/env python3
"""2.148.1 API tests, part C: encryption tools, backup folders, organisation deletion, approval records, account import /
export, push fallback, sign-in log. One container (start.sh) with KALMIDO_SECRET_KEY; invented names only (example.com).
freelancer-matrix: own
 - #2481: the field passes of the encryption tool cover every protected table (compared with the central list); status counts
   an encrypted logbook value, decrypt-all turns it plain ("still encrypted: 0"), encrypt-all seals it again, a renewal
   of the key finishes and the value stays readable
 - #2482: team chat, table, list header and bookmark files are in the backup and come back with a restore; a file of a
   folder the archive does not know keeps the attachment folder of before (never deleted unseen)
 - #2487: before an organisation is deleted its own files are never decrypted on the disk; the deletion still works
 - #2493: video approval records keep their row when the review goes (ON DELETE SET NULL, the start-up step repairs an
   older key); the decision in the office log is encrypted and has no address / device; cancelled bookings that were never
   confirmed go after 30 days, others stay
 - #2492: an import takes over a file marked as browser-encrypted without the format's header as a normal file (scanned,
   marked unchecked, the type from the content); comments of other people come over by name only; an export with lists of
   an organisation is noted in its list history; more than the allowed parallel imports get 429
 - #2494: the push fallback to the public ntfy server carries a neutral text only; GET /api/v1/export needs "account" for
   a personal token; the account export holds private files (list), private knowledge pages, agent chats, own direct
   messages, absences and timesheets and names what is missing; a failed sign-in is logged without the typed name
 - a person without an organisation: account export with the new parts, import, v1 export, backup of her files
usage: p21481_c_api_test.py <datadir>      (P21481C_NOSTART=1: a running server with the settings below, no start.sh)"""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile

import requests
import dbx as dbxm
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"
FAILS, OKS = [], [0]
NOSTART = os.environ.get("P21481C_NOSTART") == "1"


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


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def cli(*args):
    r = subprocess.run(["docker", "exec", "-i", "-e", "KALMIDO_ORGCRYPT_ROT_SETTLE=0", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args],
                       capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout, r.stderr


def py(code):
    """A few lines of Python inside the container (the server's modules, its server key)."""
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout, r.stderr


def jout(out):
    try:
        return json.loads(out[out.index("{"):out.rindex("}") + 1])
    except ValueError:
        return {}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def wait_bk(n_before, t=60):
    for _ in range(t * 4):
        j = A.get(B + "/api/admin/backups").json()
        if not j["running"] and (len(j["items"]) > n_before or j["last_error"]):
            return j
        time.sleep(0.25)
    return A.get(B + "/api/admin/backups").json()


def export_of(s, secs=120):
    r = s.post(B + "/api/account/export")
    assert r.status_code == 202, r.text
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + "/api/account/export").json()
        if j.get("state") != "running":
            break
        time.sleep(0.25)
    assert j.get("state") == "done", j
    r = s.get(B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    return r.content


def upload(s, data, name="kalmido-account.zip"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        if not r.ok:
            return iid, r
        off += len(part)
    return iid, None


def wait_imp(s, iid, secs=180):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def mkzip(tables, files=None, user_id=1000):
    """A small account export (invented data)."""
    entries = {f"data/{t}.json": json.dumps(rows).encode() for t, rows in tables.items()}
    entries.update(files or {})
    flist = [{"path": p, "size": len(b), "sha256": sha(b)} for p, b in entries.items()]
    m = {"format": "kalmido-account", "v": 1, "kalmido_version": "test", "created_at": "2026-10-20T06:00:00Z",
         "source": {"url": "https://example.com", "hosted": True}, "user": {"id": user_id, "name": "Test Person", "email": "test@example.com"},
         "tables": {}, "files": flist, "client_encrypted": {}, "export_id": os.urandom(16).hex()}
    mb = json.dumps(m).encode()
    cs = f"{sha(mb)}  manifest.json\n" + "".join(f"{f['sha256']}  {f['path']}\n" for f in flist)
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", mb)
        z.writestr("checksum.sha256", cs.encode())
        for p, b in entries.items():
            z.writestr(p, b)
    return bio.getvalue()


def EH(email):
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


# ---------------------------------------------------------------- set-up
if not NOSTART:
    extra = ["-e KALMIDO_INSTANCE_MODE=workspaces", "-e KALMIDO_ORGCRYPT_DELAY=0", "-e KALMIDO_SECRET_KEY=" + KEY,
             "-e KALMIDO_BACKUPS=1", "-e KALMIDO_BACKUP_TICK=1", "-e KALMIDO_CLAMD=127.0.0.1:9", "-e KALMIDO_CLAMD_STRICT=0",
             "-e KALMIDO_ACCOUNT_IMPORT_PARALLEL=1"]
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True,
                       env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(extra)))
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"username": "bruno", "display_name": "Bruno Member", "password": "password123", "email": "bruno@example.com"})
assert r.ok, r.text
BRUNO = r.json()["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bruno@example.com", "role": "member"}).ok
FEAT = "cal,comments,collab,office,clients,time,wiki,files,contacts"
Bo = sess("bruno")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
_, out, _ = py("from kalmido.core.config import ATT_DIR; print(ATT_DIR)")
ATT = out.strip().splitlines()[-1] if out.strip() else "/data/attachments"

# ================================================================== #2481 the field passes cover every protected table
code = """
import json, app
from kalmido.admin import orgcrypt_cli as cl
from kalmido.core import orgcrypt as oc
from kalmido.core.pg import system_ctx
want = {(t, col) for t, cols in oc.FIELDS.items() if not t.startswith(cl.FIELD_SETTLED) for col in cols} | set(oc.JSON_KEYS)
got = {(t, col) for t, _i, col, _k in cl.FIELD_JOBS}
bad = []
c = app.connect()
with system_ctx(c):
    for t, idc, col, kind in cl.FIELD_JOBS:
        try:
            c.execute(f"SELECT {idc}, {col} FROM {t} WHERE org_id=0 LIMIT 0").fetchall()
        except Exception as e:
            bad.append(f"{t}.{col}: {type(e).__name__}")
            c.rollback()
print(json.dumps({"same": want == got, "missing": sorted(map(list, want - got)), "extra": sorted(map(list, got - want)), "bad": bad,
                  "n": len(got)}))
"""
rc, out, err_ = py(code)
j = jout(out)
check(rc == 0 and j.get("same") and not j.get("bad") and j.get("n", 0) > 30,
      f"#2481: the field passes = the protected fields, every column readable {j} {err_[-600:]}")

r = A.post(B + O + "/vehicles", json={"name": "Van", "plate": "B-KC 2148", "kind": "company"})
VID = r.json().get("id") if r.ok else None
check(r.status_code == 201 and VID, f"#2481: a logbook vehicle {r.status_code} {r.text[:200]}")
check(str(one("SELECT plate FROM office_vehicles WHERE id=?", (VID,))).startswith("kenc1:"), "#2481: its plate is encrypted at rest")
rc, out, err_ = cli("status")
st = {o["org"]: o for o in jout(out).get("orgs", [])}
check(rc == 0 and st.get(ORG, {}).get("fields", {}).get("enc", 0) >= 1, f"#2481: status counts the logbook value {st.get(ORG)} {err_[-300:]}")
rc, out, err_ = cli("decrypt-all")
check(rc == 0 and "still encrypted: 0" in out, f"#2481: decrypt-all {rc} {out[-300:]} {err_[-300:]}")
check(one("SELECT plate FROM office_vehicles WHERE id=?", (VID,)) == "B-KC 2148", "#2481: decrypt-all turned the logbook value plain")
rc, out, err_ = cli("status")
st = {o["org"]: o for o in jout(out).get("orgs", [])}
check(st.get(ORG, {}).get("fields", {}).get("enc") == 0 and st.get(ORG, {}).get("fields", {}).get("plain", 0) >= 1,
      f"#2481: status after decrypt-all: nothing encrypted, the value plain {st.get(ORG)}")
rc, out, err_ = cli("encrypt-all")
check(rc == 0 and str(one("SELECT plate FROM office_vehicles WHERE id=?", (VID,))).startswith("kenc1:"),
      f"#2481: encrypt-all seals a value written while the encryption was off {rc} {out[-200:]} {err_[-300:]}")
rc, out, err_ = cli("rotate", "--org", str(ORG))
check(rc == 0 and one("SELECT wrapped_rot FROM org_keys WHERE org_id=?", (ORG,)) is None, f"#2481: key renewal finished {rc} {out[-200:]} {err_[-400:]}")
vs = A.get(B + O + "/vehicles").json().get("vehicles", [])
check(any(v.get("plate") == "B-KC 2148" for v in vs), f"#2481: the plate stays readable after the renewal {vs[:2]}")

# ================================================================== #2482 backup + restore of every attachment folder
FILES = {"tchat/7/ab12-chat.txt": b"team chat file\n", "sheets/5/cd34-cell.txt": b"table cell file\n",
         "listheads/l3-tok.jpg": b"\xff\xd8header\n", "bookmarks/4-ef56.png": b"\x89PNGbookmark\n"}
UNKNOWN = "zzunknown/1/keep.txt"
code = "import os, sys, json\nATT = sys.argv[1]\nfor rel, data in json.loads(sys.argv[2]).items():\n" \
       "    p = os.path.join(ATT, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'wb').write(bytes.fromhex(data))\n"
put = {k: v.hex() for k, v in FILES.items()}
r = subprocess.run(["docker", "exec", CT, "python", "-c", code, ATT, json.dumps(put)], capture_output=True, text=True)
check(r.returncode == 0, f"#2482: test files written {r.stderr[-200:]}")
n0 = len(A.get(B + "/api/admin/backups").json()["items"])
check(A.post(B + "/api/admin/backups").status_code == 202, "#2482: back up now")
j = wait_bk(n0)
name = next((x["name"] for x in j["items"] if x["kind"] == "manual"), "")
code = "import zipfile, sys, json, os\nz = zipfile.ZipFile(os.path.join(sys.argv[1], sys.argv[2]))\n" \
       "m = json.loads(z.read('manifest.json'))\nprint(json.dumps({'names': z.namelist(), 'skipped': m.get('skipped_files')}))"
_, out, _ = py("from kalmido.admin.backup import BK_DIR; print(BK_DIR)")
BKD = out.strip().splitlines()[-1] if out.strip() else "/data/backups"
r = subprocess.run(["docker", "exec", CT, "python", "-c", code, BKD, name], capture_output=True, text=True)
zj = jout(r.stdout)
check(all("attachments/" + k in zj.get("names", []) for k in FILES) and zj.get("skipped") == 0,
      f"#2482: team chat, table, list header and bookmark files in the archive {zj.get('skipped')} {[n for n in zj.get('names', []) if n.startswith('attachments/')][:10]}")
# a file of a folder the archive does not know, and the known ones removed: the restore brings back the known ones
code = "import os, sys, json, shutil\nATT = sys.argv[1]\nfor rel in json.loads(sys.argv[2]): os.remove(os.path.join(ATT, rel))\n" \
       "p = os.path.join(ATT, sys.argv[3]); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').write('keep me')\n"
subprocess.run(["docker", "exec", CT, "python", "-c", code, ATT, json.dumps(list(FILES)), UNKNOWN], capture_output=True, text=True)
r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "name": name})
check(r.ok and r.json().get("ok"), f"#2482: restore {r.status_code} {r.text[:300]}")
A = sess("alice")
code = "import os, sys, json\nATT = sys.argv[1]\nprint(json.dumps({rel: open(os.path.join(ATT, rel), 'rb').read().hex() if os.path.exists(os.path.join(ATT, rel)) else None " \
       "for rel in json.loads(sys.argv[2])}))\nbase = os.path.dirname(ATT.rstrip('/'))\n" \
       "print(json.dumps([n for n in os.listdir(base) if n.startswith(os.path.basename(ATT.rstrip('/')) + '.pre-restore-')]))"
r = subprocess.run(["docker", "exec", CT, "python", "-c", code, ATT, json.dumps(list(FILES))], capture_output=True, text=True)
lines = r.stdout.strip().splitlines()
back = json.loads(lines[0]) if lines else {}
kept = json.loads(lines[1]) if len(lines) > 1 else []
check(all(back.get(k) == v.hex() for k, v in FILES.items()), f"#2482: the files are back after the restore {back}")
check(len(kept) == 1, f"#2482: the folder of before stays while it holds a file the archive does not cover {kept}")
code = "import os, sys, shutil\nbase = os.path.dirname(sys.argv[1].rstrip('/'))\nfor n in os.listdir(base):\n" \
       "    if '.pre-restore-' in n: shutil.rmtree(os.path.join(base, n))\n"
subprocess.run(["docker", "exec", CT, "python", "-c", code, ATT], capture_output=True, text=True)
for s in (A,):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo = sess("bruno")

# ================================================================== #2487 organisation deletion: no plain file on the disk
ORG3 = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ALICE}).json()["id"]
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
r = A.post(B + "/api/wiki/pages", json={"space": f"org:{ORG3}", "path": "Plan", "body": "page of Gamma"})
PG = r.json().get("id") if r.ok else None
r = A.post(B + f"/api/wiki/pages/{PG}/files", files={"file": ("gamma.pdf", PDF, "application/pdf")})
check(r.ok, f"#2487: a file of the organisation's knowledge page {r.status_code} {r.text[:200]}")
WP = one("SELECT path FROM wiki_files WHERE org_id=? ORDER BY id DESC LIMIT 1", (ORG3,))
code = f"""
import os, app
from kalmido.core.config import ATT_DIR
from kalmido.core import orgcrypt as oc
from kalmido.core.pg import system_ctx
from kalmido.admin.orgcrypt_cli import before_org_delete
p = os.path.join(ATT_DIR, {WP!r})
before = open(p, 'rb').read()[:len(oc.MAGIC)] == oc.MAGIC
c = app.connect()
with system_ctx(c):
    res = before_org_delete(c, {ORG3})
c.rollback()
after = open(p, 'rb').read()[:len(oc.MAGIC)] == oc.MAGIC
print(before, after, res)
"""
rc, out, err_ = py(code)
check(rc == 0 and out.split()[:2] == ["True", "True"], f"#2487: the organisation's own file stays sealed before the deletion {out[-200:]} {err_[-400:]}")
r = A.delete(B + f"/api/admin/orgs/{ORG3}")
check(r.ok and not one("SELECT 1 FROM orgs WHERE id=?", (ORG3,)), f"#2487: the organisation is deleted {r.status_code} {r.text[:200]}")

# ================================================================== #2493 approval records, the office log, old bookings
rule = one("SELECT con.confdeltype FROM pg_constraint con JOIN pg_class cl ON cl.oid=con.conrelid JOIN pg_attribute a "
           "ON a.attrelid=con.conrelid AND a.attnum=con.conkey[1] WHERE con.contype='f' AND cl.relname='office_signoffs' AND a.attname='video_id'")
check(rule == "n", f"#2493: video approval records stay when the review goes (SET NULL) {rule}")
cn = one("SELECT con.conname FROM pg_constraint con JOIN pg_class cl ON cl.oid=con.conrelid JOIN pg_attribute a ON a.attrelid=con.conrelid "
         "AND a.attnum=con.conkey[1] WHERE con.contype='f' AND cl.relname='office_signoffs' AND a.attname='video_id'")
dbx(f'ALTER TABLE office_signoffs DROP CONSTRAINT "{cn}"')
dbx("ALTER TABLE office_signoffs ADD CONSTRAINT office_signoffs_video_id_fkey FOREIGN KEY (video_id) REFERENCES video_reviews(id) ON DELETE CASCADE")
rc, out, err_ = py("import app\nfrom kalmido.office.signoff import sig_fk_migrate\nc = app.connect()\nsig_fk_migrate(c)\nsig_fk_migrate(c)\nc.commit()\nprint('ok')")
rule = one("SELECT con.confdeltype FROM pg_constraint con JOIN pg_class cl ON cl.oid=con.conrelid JOIN pg_attribute a "
           "ON a.attrelid=con.conrelid AND a.attnum=con.conkey[1] WHERE con.contype='f' AND cl.relname='office_signoffs' AND a.attname='video_id'")
check(rc == 0 and rule == "n", f"#2493: the start-up step repairs an older key (and runs twice) {rule} {err_[-300:]}")
code = f"""
import json, app
from kalmido.core.orgcrypt import oc_log_detail
from kalmido.core.pg import system_ctx
c = app.connect()
with system_ctx(c):
    d = oc_log_detail(c, {ORG}, json.dumps({{"signoff": 1, "state": "accepted", "name": "Max Kunde", "sig_proto": 1}}))
c.commit()
print(d[:6])
"""
rc, out, err_ = py(code)
check(rc == 0 and out.strip().endswith("kenc1:"), f"#2493: the decision in the office log is encrypted {out[-100:]} {err_[-300:]}")
old, recent = "2026-08-01T10:00:00Z", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3 * 86400))
ids_ = {}
for k, st_, conf, canc in (("dead", "cancelled", None, old), ("conf", "cancelled", old, old), ("fresh", "cancelled", None, recent),
                           ("open", "confirmed", old, None)):
    dbx('INSERT INTO appt_bookings(user_id, start, "end", name, email, status, created_at, confirmed_at, cancelled_at) VALUES(?,?,?,?,?,?,?,?,?)',
        (ALICE, "2026-08-10T09:00:00Z", "2026-08-10T09:30:00Z", "Guest Example", "guest@example.com", st_, old, conf, canc))
    ids_[k] = one("SELECT MAX(id) FROM appt_bookings")
rc, out, err_ = py(f"import app\nfrom kalmido.calendars.apptbook import apb_expire\nfrom kalmido.core.pg import system_ctx\nc = app.connect()\n"
                   f"with system_ctx(c):\n    apb_expire(c, {ALICE})\nc.commit()\nprint('ok')")
left = {r[0] for r in dbx("SELECT id FROM appt_bookings WHERE user_id=?", (ALICE,))}
check(rc == 0 and ids_["dead"] not in left and ids_["conf"] in left and ids_["fresh"] in left and ids_["open"] in left,
      f"#2493: only cancelled, never confirmed bookings older than 30 days go {ids_} {left} {err_[-300:]}")

# ================================================================== #2492 account import + export
ts = "2026-10-01T08:00:00Z"
crafted = mkzip({
    "lists": [{"id": 1, "name": "Import Test", "created_at": ts}],
    "tasks": [{"id": 1, "list_id": 1, "title": "Import task", "created_at": ts, "updated_at": ts}],
    "comments": [{"id": 1, "task_id": 1, "user_id": 80, "body": "Comment of another person", "created_at": ts},
                 {"id": 2, "task_id": 1, "user_id": 1000, "body": "My own comment", "created_at": ts}],
    "people": [{"user_id": 80, "name": "Bruno from the file", "email_hash": EH("bruno@example.com"), "lists": {"1": "edit"}}],
    "attachments": [{"id": 1, "task_id": 1, "name": "notes.txt", "mime": "image/png", "enc": 1, "enc_by": 1000,
                     "file": "files/attachments/1-notes.txt", "created_at": ts}]},
    files={"files/attachments/1-notes.txt": b"plain text, not encrypted\n" * 10})
A.patch(B + "/api/settings", json={"workspace": "private"})
iid, bad = upload(A, crafted)
j = wait_imp(A, iid)
check(j.get("state") == "preview", f"#2492: the crafted file checks fine {j.get('state')} {j.get('error')}")
r = A.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {EH("bruno@example.com"): {"share": True}}})
j = wait_imp(A, iid) if r.status_code == 202 else {"state": r.status_code, "error": r.text[:200]}
check(j.get("state") == "done", f"#2492: import done {j.get('state')} {j.get('error')}")
fc = dbx("SELECT user_id, ext_name FROM comments WHERE body='Comment of another person'")
check(fc and fc[0]["user_id"] is None and fc[0]["ext_name"] == "Bruno from the file", f"#2492: another person's comment by name only {[tuple(x) for x in fc]}")
mc = dbx("SELECT user_id FROM comments WHERE body='My own comment'")
check(mc and mc[0]["user_id"] == ALICE, "#2492: my own comment stays mine")
at = dbx("SELECT id, enc, mime FROM attachments WHERE name='notes.txt' ORDER BY id DESC LIMIT 1")
check(at and at[0]["enc"] == 0 and at[0]["mime"] != "image/png", f"#2492: a file without the format's header is a normal file, its type from the content {[tuple(x) for x in at]}")
check(at and dbx("SELECT 1 FROM upload_scan WHERE kind='att' AND ref_id=? AND state='unchecked'", (at[0]["id"],)),
      "#2492: the scanner could not check it: marked unchecked for the later scan")
# an export with a list of an organisation is noted in its list history
LO = A.post(B + "/api/lists", json={"name": "Org list export", "org_id": ORG}).json()["id"]
EXP = export_of(A)
check(dbx("SELECT 1 FROM org_list_log WHERE org_id=? AND list_id=? AND action='export' AND by_id=?", (ORG, LO, ALICE)),
      "#2492: the export of an organisation's list is in its list history")
# parallel imports: the one slot of this server is taken -> 429
code = "import time, app\nfrom kalmido.core.config import DATABASE_URL\nfrom kalmido.core.pg import connect_direct\nc = connect_direct(DATABASE_URL)\n" \
       "c.execute('SELECT pg_advisory_lock(21481, 0)').fetchone(); c.commit(); print('held', flush=True); time.sleep(25)\n"
holder = subprocess.Popen(["docker", "exec", "-i", CT, "python", "-c", code], stdout=subprocess.PIPE, text=True)
holder.stdout.readline()
iid2, r429 = upload(Bo, crafted)
check(r429 is not None and r429.status_code == 429, f"#2492: a further import while the slots are taken: 429 {r429.status_code if r429 is not None else 'none'}")
holder.wait(timeout=60)
off = len(crafted) - min(len(crafted), 1 << 20)
r = Bo.put(B + f"/api/account/import/{iid2}?offset={off}", data=crafted[off:], headers={"Content-Type": "application/octet-stream"})
j = wait_imp(Bo, iid2) if r.ok else {"state": r.status_code}
check(j.get("state") == "preview", f"#2492: once a slot is free the same upload goes on {j.get('state')} {j.get('error')}")
Bo.delete(B + f"/api/account/import/{iid2}")

# ================================================================== #2494 push fallback, v1 export, the account export, sign-in log
code = f"""
import json, app
from kalmido.notify import push
sent = []
push.ntfy = lambda title, msg, prio="4", click=None, topic=None, actions=None, admin=False: sent.append([title, msg, click, actions]) or True
s = {{"push_channel": "webpush", "ntfy_topic": "p21481c-topic", "lang": "en"}}
push.NTFY_URL, push.NTFY_TOKEN = "https://ntfy.sh", ""
push.notify({BRUNO}, "Secret client Meyer", "Health note body", click="https://kalmido.example/#task/77", s=s)
push.NTFY_URL = "https://ntfy.example.com"
push.notify({BRUNO}, "Own server title", "Own server body", click="https://kalmido.example/#task/77", s=s)
push.NTFY_URL = "https://ntfy.sh"
push.notify({BRUNO}, "Chosen ntfy title", "Chosen body", click="https://kalmido.example/#task/77", s={{**s, "push_channel": "ntfy"}})
print(json.dumps(sent))
"""
rc, out, err_ = py(code)
try:
    sent = json.loads(out.strip().splitlines()[-1])
except (ValueError, IndexError):
    sent = []
check(rc == 0 and len(sent) == 3, f"#2494: three pushes went to ntfy {out[-300:]} {err_[-400:]}")
if len(sent) == 3:
    check("Secret" not in json.dumps(sent[0]) and "Health" not in json.dumps(sent[0]) and "#task" not in str(sent[0][2]) and not sent[0][3],
          f"#2494: the fallback to the public ntfy.sh carries a neutral text only {sent[0]}")
    check(sent[1][0] == "Own server title" and sent[2][0] == "Chosen ntfy title", f"#2494: own ntfy server / ntfy chosen: as before {sent[1:]}")


def tok(s, scopes):
    r = s.post(B + "/api/me/tokens", json={"name": "t" + str(time.monotonic_ns())[-6:], "scopes": scopes})
    assert r.status_code == 201, r.text
    return r.json()["token"]


V = B + "/api/v1"
t_exp = tok(A, ["read", "export"])
t_acc = tok(A, ["read", "export", "account"])
r = requests.get(V + "/export", headers={"Authorization": "Bearer " + t_exp})
check(r.status_code == 403 and (r.json().get("error") or {}).get("required_scope") == "account", f"#2494: v1 export without account: 403 {r.status_code} {r.text[:200]}")
r = requests.get(V + "/export", headers={"Authorization": "Bearer " + t_acc}, timeout=120)
check(r.ok and any(x["name"] == "Import Test" for x in r.json().get("lists", [])), f"#2494: v1 export with export + account {r.status_code}")

with zipfile.ZipFile(io.BytesIO(EXP)) as z:
    man = json.loads(z.read("manifest.json"))
    names = z.namelist()
check(all(f"data/{t}.json" in names for t in ("private_files", "wiki_pages", "agent_chats", "direct_messages", "absences", "timesheets")),
      f"#2494: the account export holds the new personal parts {[n for n in names if n.startswith('data/')][-12:]}")
check(any("private files" in x for x in man.get("not_included", [])) and any("direct messages" in x for x in man.get("not_included", [])),
      f"#2494: the manifest names what is missing {man.get('not_included')}")

before = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
nb = len(before.stdout + before.stderr)
check(requests.post(B + "/api/auth/login", json={"username": "MySecretPassword99", "password": "x"}, headers=H).status_code == 401, "a failed sign-in: 401")
time.sleep(0.5)
logs = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
tail = (logs.stdout + logs.stderr)[max(0, nb - 2000):]
line = [x for x in tail.splitlines() if "login failed for" in x]
check(line and "MySecretPassword99" not in tail and "user#" + hashlib.sha256(b"mysecretpassword99").hexdigest()[:8] in line[-1]
      and re.search(r"from \S+(\.x|/48)$", line[-1].strip()), f"#2494: a failed sign-in is logged with a hash of the name and a shortened address {line[-1:]}")

# ================================================================== a person without an organisation
# freelancer-matrix: own
FID, Fr = freelancer(B, A)
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Mein Plan", "body": "private page text"})
check(r.ok, f"freelancer: a private knowledge page {r.status_code} {r.text[:150]}")
FE = export_of(Fr)
with zipfile.ZipFile(io.BytesIO(FE)) as z:
    wp = json.loads(z.read("data/wiki_pages.json")) if "data/wiki_pages.json" in z.namelist() else []
check(any(p.get("body") == "private page text" for p in wp), f"freelancer: the account export holds her private page, readable {wp[:1]}")
fz = mkzip({"lists": [{"id": 1, "name": "Freelancer import", "created_at": ts}],
            "tasks": [{"id": 1, "list_id": 1, "title": "F task", "created_at": ts, "updated_at": ts}]})
iid, bad = upload(Fr, fz)
j = wait_imp(Fr, iid)
r = Fr.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}}) if j.get("state") == "preview" else None
j = wait_imp(Fr, iid) if r is not None and r.status_code == 202 else j
check(j.get("state") == "done" and dbx("SELECT 1 FROM lists WHERE owner_id=? AND name='Freelancer import'", (FID,)),
      f"freelancer: the account import works {j.get('state')} {j.get('error')}")
ft = tok(Fr, ["read", "export", "account"])
r = requests.get(V + "/export", headers={"Authorization": "Bearer " + ft}, timeout=120)
check(r.ok, f"freelancer: v1 export with export + account {r.status_code}")
FL = Fr.get(B + "/api/state").json()["lists"][0]["id"] if Fr.get(B + "/api/state").json().get("lists") else None
FT = Fr.post(B + "/api/tasks", json={"title": "F file", "list_id": FL}).json().get("id") if FL else None
r = Fr.post(B + f"/api/tasks/{FT}/attachments", files={"file": ("f.txt", b"freelancer file\n", "text/plain")}) if FT else None
fpath = one("SELECT path FROM attachments WHERE task_id=?", (FT,)) if FT else None
n0 = len(A.get(B + "/api/admin/backups").json()["items"])
A.post(B + "/api/admin/backups")
j = wait_bk(n0)
r = subprocess.run(["docker", "exec", CT, "python", "-c", "import zipfile, sys, os, json\nz = zipfile.ZipFile(os.path.join(sys.argv[1], sys.argv[2]))\n"
                    "print(json.dumps(z.namelist()))", BKD, next((x["name"] for x in j["items"] if x["kind"] == "manual"), "-")], capture_output=True, text=True)
check(fpath and ("attachments/" + fpath) in (r.stdout or ""), f"freelancer: her task file is in the backup {fpath}")

print(f"p21481_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
