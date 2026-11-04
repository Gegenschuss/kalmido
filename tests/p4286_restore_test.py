#!/usr/bin/env python3
# kalmido-suite:
# freelancer-matrix: own
"""2.510.0 (#4286): the emergency way of a backup, four round trips that check the CONTENT afterwards (invented data; frida is a
person without an organisation, her private files and tasks go the same way).
 1. Encrypted format 3 with a file that comes back from pieces (larger than one chunk of the shared store):
    - on the same server: restored from the list, every task, comment, office document and every file byte as at the backup
    - on a new server with the same server key: the bare format-3 file without its store is refused and says what is missing;
      the file assembled with the command of SELF-HOSTING.md (and the download) comes in, content as at the backup
 2. A backup of release 2.101.0 (tests/fixtures/upgrade, packed as that release wrote it) on a server of today: the migrations
    run, the schema is complete, the old content is there, a write works, a second start applies nothing
 3. From server A to a new server B with sealed files (SELF-HOSTING.md "restore on another server"):
    - another server key: check warns, restore refused, B unchanged, the upload stays for another try
    - KALMIDO_SECRET_KEY_CHANGED=1: restored with a warning, the sealed file stays closed (never garbage as a file), the server answers
    - the old key back in place: everything opens with its bytes
 4. init_db fails after pg_restore (a real defect in the backup, no stand-in: a unique index init_db cannot build):
    - the way back works: clear message, the state of before with its files, no leftovers, the next restore goes through
    - the way back fails too: message with the safety backup, /api/health says the server is not healthy, nothing runs on the
      half database, a start on the defect stops with the reason, a restart completes the database
    - a hard stop between pg_restore and init_db: the next start finishes the job, the folders of before are named
usage: p4286_restore_test.py <datadir>"""
import base64
import glob
import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, CT, DATA, PASSWORD, check, sess, su_get, until  # noqa: E402
from upgrade_views import data_checks, docs, schema, schema_gaps  # noqa: E402

BK = os.path.join(DATA, "backups")
ST = os.path.join(BK, ".store")
H = {"X-Requested-With": "kalmido"}
PASSPHRASE = "the emergency passphrase"
K1, K2 = (base64.b64encode(os.urandom(32)).decode() for _ in range(2))
FIX = os.path.join(N, "fixtures", "upgrade", "2.101.0")
MAGIC = b"KENC1\n"  # a file sealed with a space's key (core/orgcrypt.py)
BIG = os.urandom(2600 * 1024)    # three chunks of the store (bkstore.CHUNK = 1 MiB)
FBIG = os.urandom(90 * 1024)     # shared as well (from 64 KiB on)
SMALL = b"a small note\n" * 40   # stays in the zip
kt.docker_logs_on_first_fail()


def start(key=None, changed="1", keep=False, wait="150"):
    """A server through start.sh: without keep a NEW one (empty data folder and database, as after a lost server)."""
    extra = ["-e KALMIDO_BACKUP_TICK=1", "-e KALMIDO_BACKUP_MAX_MB=40", "-e KALMIDO_ADMIN_ALERTS=1", "-e TASKS_MAX_FILE_MB=10"] + ([f"-e KALMIDO_SECRET_KEY={key}"] if key else [])
    e = dict(os.environ, EXTRA=" ".join(extra), KALMIDO_SECRET_KEY_CHANGED=changed, KALMIDO_NO_SECRET_KEY="" if key else "1", START_WAIT_S=wait)
    e.pop("KEEP", None)
    if keep:
        e["KEEP"] = "1"
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def new_admin(user="root"):
    """The first account of a new server, who is not in the backup."""
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": user, "display_name": "First Admin", "password": PASSWORD}).ok
    s = sess(user)
    s.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
    s.patch(B + "/api/admin/backups", json={"on": False})
    return s


def state(s):
    return s.get(B + "/api/admin/backups").json()


def backup_now(s):
    before = {x["name"] for x in state(s)["items"]}
    r = s.post(B + "/api/admin/backups")
    assert r.status_code == 202, r.text
    new = until(lambda: (lambda j: not j["running"] and [x for x in j["items"] if x["name"] not in before])(state(s)), 90)
    assert new, state(s)
    return new[0]


def upload(s, data):
    r = s.post(B + "/api/admin/backups/upload", data=data, headers={"Content-Type": "application/octet-stream"})
    assert r.ok, r.text
    return r.json()["upload"]


def restore(s, **b):
    return s.post(B + "/api/admin/backups/restore", json={"password": PASSWORD, "confirm": "RESTORE", **b})


def verify(s, name, **b):
    return s.post(B + f"/api/admin/backups/{name}/verify", json=b)


def logs():
    r = subprocess.run(["docker", "logs", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return r.stdout


def psql(*args, data=None):
    with open(os.path.join(DATA, ".kalmido-db"), encoding="utf-8") as f:
        dbc, dbn = f.read().split()
    r = subprocess.run(["docker", "exec", "-i", dbc, "psql", "-U", "kalmido", "-v", "ON_ERROR_STOP=1", "-Atq", "-d", dbn if data is None else data, *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout.strip()


def leftovers():
    """Folders of a restore: next to the data folders and in the backup folder."""
    return sorted(os.path.basename(p) for pat in ("attachments.restore-*", "attachments.pre-restore-*", "office.restore-*", "office.pre-restore-*",
                                                  os.path.join("backups", ".restore-*")) for p in glob.glob(os.path.join(DATA, pat)))


def health():
    return requests.get(B + "/api/health", timeout=20)


# ------------------------------------------------------------------ the data and how it is read back
class Seed:
    pass


def seed(A):
    """Alice's organisation (a project with sealed files, a client and a quotation) and frida's own workspace."""
    S = Seed()
    S.me = A.get(B + "/api/state").json()["me"]["id"]
    S.org = A.post(B + "/api/admin/orgs", json={"name": "Nordstern", "admin_id": S.me}).json()["id"]
    assert A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done", "workspace": f"org:{S.org}"}).ok
    S.fid, Fr = freelancer(B, A)
    S.list = A.post(B + "/api/lists", json={"name": "Nordstern Projekt", "org_id": S.org, "kind": "project"}).json()["id"]
    S.task = A.post(B + "/api/tasks", json={"title": "Film schneiden", "list_id": S.list, "due": "2027-03-04"}).json()["id"]
    assert A.post(B + f"/api/tasks/{S.task}/comments", json={"body": "Erste Fassung bis Freitag"}).ok
    r = A.post(B + f"/api/tasks/{S.task}/attachments", files={"file": ("schnitt.bin", BIG, "application/octet-stream")})
    assert r.ok, r.text
    S.big = r.json()["attachments"][0]
    assert A.post(B + f"/api/tasks/{S.task}/attachments", files={"file": ("note.txt", SMALL, "text/plain")}).ok
    cl = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "city": "Köln", "country": "DE", "org_id": S.org}).json()["id"]
    q = A.post(B + "/api/office/docs", json={"kind": "offer", "project_title": "Film", "client_id": cl}).json()["id"]
    assert A.put(B + f"/api/office/docs/{q}/items", json={"items": [{"title": "Drehtag", "qty": 2, "rate": 900}]}).ok
    fl = Fr.post(B + "/api/lists", json={"name": "Frida Kunden", "kind": "project"}).json()["id"]
    S.ftask = Fr.post(B + "/api/tasks", json={"title": "Website-Texte", "list_id": fl}).json()["id"]
    assert Fr.post(B + f"/api/tasks/{S.ftask}/comments", json={"body": "Entwurf liegt bei"}).ok
    r = Fr.post(B + f"/api/tasks/{S.ftask}/attachments", files={"file": ("angebot.pdf", FBIG, "application/pdf")})
    assert r.ok, r.text
    S.fbig = r.json()["attachments"][0]
    fc = Fr.post(B + "/api/clients", json={"name": "Kleinkunde GbR", "city": "Berlin", "country": "DE"}).json()["id"]
    fq = Fr.post(B + "/api/office/docs", json={"kind": "offer", "project_title": "Texte", "client_id": fc}).json()["id"]
    assert Fr.put(B + f"/api/office/docs/{fq}/items", json={"items": [{"title": "Text", "qty": 4, "rate": 120}]}).ok
    return S, Fr


def snap(users):
    """What people see, through the API: lists, tasks, comments, clients, office documents and the bytes of every file."""
    out = {}
    for u, s in users.items():
        st = s.get(B + "/api/state").json()
        lists = {x["id"]: x["name"] for x in st["lists"]}
        tasks = []
        for t in st["tasks"]:
            files = []
            for a in t.get("attachments") or []:
                g = s.get(B + f"/api/attachments/{a['id']}")
                files.append([a["name"], g.status_code, hashlib.sha256(g.content).hexdigest()])
            com = sorted(c["body"] for c in s.get(B + f"/api/tasks/{t['id']}/timeline").json()["comments"])
            tasks.append([lists.get(t["list_id"], "?"), t["title"], t.get("due") or "", t.get("status") or 0, sorted(files), com])
        out[u] = {"lists": sorted(lists.values()), "tasks": sorted(tasks), "docs": docs(s),
                  "clients": sorted(c["name"] for c in s.get(B + "/api/clients").json()["clients"])}
    return out


def people():
    return {"alice": sess("alice"), "frida": sess("frida")}


def same(got, exp, what):
    if not check(got == exp, what):
        print("   expected:", json.dumps(exp, ensure_ascii=False)[:1800])
        print("   got:     ", json.dumps(got, ensure_ascii=False)[:1800])


def stored(att):
    """The file of an attachment row in the data folder."""
    rows = kt.dbx("SELECT path FROM attachments WHERE id=?", (att["id"],))
    return os.path.join(DATA, "attachments", rows[0][0])


def after_write(s, tid):
    """A restored server takes new work and writes a new backup that checks fine."""
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": "nach dem Einspielen"})
    check(r.ok, f"a comment after the restore {r.status_code} {r.text[:160]}")
    x = backup_now(s)
    v = verify(s, x["name"])
    check(v.ok, f"a new backup after the restore checks fine {v.status_code} {v.text[:200]}")


# ================================================================== 1. encrypted format 3
start(K1)
A = new_admin("alice")
S, Fr = seed(A)
check(open(stored(S.big), "rb").read(6) == MAGIC and open(stored(S.fbig), "rb").read(6) == MAGIC,
      "setup: the org file and frida's file lie sealed in the data folder")
check(A.patch(B + "/api/admin/backups", json={"encrypt": True, "passphrase": PASSPHRASE}).ok, "setup: encryption on")
E1 = backup_now(A)
p1 = os.path.join(BK, E1["name"])
check(E1["name"].endswith(".zip.enc") and E1.get("shared_files") == 2 and E1["size"] < len(BIG),
      f"1: an encrypted format-3 backup: the two large files are not in its file {E1}")
blobs = [p for p in glob.glob(os.path.join(ST, "k-*", "??", "*"))]
check(len(blobs) == 2 and max(os.path.getsize(p) for p in blobs) > 2 * 1024 * 1024, f"1: the large file lies in the encrypted store, in several pieces {[os.path.getsize(p) for p in blobs]}")
RAW = open(p1, "rb").read()
DOWN = su_get(A, B + f"/api/admin/backups/{E1['name']}/download").content
PF = os.path.join(DATA, "passphrase.txt")
with open(PF, "w") as f:
    f.write(PASSPHRASE)
ass = subprocess.run(["docker", "exec", CT, "python3", "-I", "/app/kalmido/admin/bkstore.py", "assemble", f"/data/backups/{E1['name']}", "/data/backups/.store",
                      "/data/complete.zip.enc", "--passphrase-file", "/data/passphrase.txt"], capture_output=True, text=True, timeout=300)
check(ass.returncode == 0, f"1: the command of SELF-HOSTING.md assembles a complete file {ass.returncode} {ass.stderr[-300:]}")
COMPLETE = open(os.path.join(DATA, "complete.zip.enc"), "rb").read()
check(len(COMPLETE) > len(BIG), f"1: the assembled file holds the large file {len(COMPLETE)}")
SEEN = snap({"alice": A, "frida": Fr})
check(any(f[2] == hashlib.sha256(BIG).hexdigest() and f[1] == 200 for t in SEEN["alice"]["tasks"] for f in t[4]), "setup: the snapshot read the large file")
check(SEEN["frida"]["clients"] == ["Kleinkunde GbR"] and SEEN["alice"]["clients"] == ["Beispielkunde AG"] and SEEN["frida"]["docs"], f"setup: the snapshot read clients and documents {SEEN['frida']}")

# what happens after the backup and must be gone again
A.delete(B + f"/api/attachments/{S.big['id']}")
Fr.delete(B + f"/api/attachments/{S.fbig['id']}")
A.patch(B + f"/api/tasks/{S.task}", json={"title": "anders"})
A.post(B + "/api/tasks", json={"title": "nach der Sicherung", "list_id": S.list})
r = restore(A, name=E1["name"], passphrase="not the passphrase at all")
check(r.status_code == 400 and r.json().get("code") == "passphrase", f"1: a wrong passphrase is refused {r.status_code} {r.text[:160]}")
check(any(t["title"] == "anders" for t in A.get(B + "/api/state").json()["tasks"]), "1: ... nothing changed")
r = restore(A, name=E1["name"])
check(r.ok and r.json().get("safety"), f"1: restore of the encrypted format-3 backup {r.status_code} {r.text[:200]}")
U = people()
same(snap(U), SEEN, "1: tasks, comments, clients, documents and every file's bytes as at the backup")
g = U["alice"].get(B + f"/api/attachments/{S.big['id']}")
check(g.ok and g.content == BIG, f"1: the file from three pieces has its bytes again {g.status_code} {len(g.content)}")
g = U["frida"].get(B + f"/api/attachments/{S.fbig['id']}")
check(g.ok and g.content == FBIG, f"1: frida's file has its bytes again {g.status_code}")
check(not leftovers(), f"1: no folder of the restore is left {leftovers()}")
after_write(U["alice"], S.task)
check(state(U["alice"])["items"][0]["name"].endswith(".zip.enc"), "1: the encryption setting holds after the restore")

# a lost server: a new one with the same key and nothing else
start(K1)
R = new_admin()
up = upload(R, RAW)
v = verify(R, up, passphrase=PASSPHRASE)
check(v.status_code == 400 and v.json().get("code") == "shared_missing" and "2 " in v.json().get("error", ""),
      f"1 new server: the bare format-3 file names its two missing files {v.status_code} {v.text[:220]}")
r = restore(R, upload=up, passphrase=PASSPHRASE)
check(r.status_code == 400 and r.json().get("code") == "shared_missing", f"1 new server: ... and is refused {r.status_code} {r.text[:160]}")
check(R.get(B + "/api/state").ok and not leftovers(), f"1 new server: nothing changed {leftovers()}")
up = upload(R, COMPLETE)
r = restore(R, upload=up)
check(r.status_code == 400 and r.json().get("code") == "need_passphrase", f"1 new server: no passphrase: asked for {r.status_code} {r.text[:160]}")
v = verify(R, up, passphrase=PASSPHRASE)
check(v.ok and v.json().get("key_warning") == "" and v.json().get("attachment_files") == 3, f"1 new server: the assembled file checks fine {v.status_code} {v.text[:220]}")
r = restore(R, upload=up, passphrase=PASSPHRASE)
check(r.ok and r.json().get("key_warning") == "", f"1 new server: the assembled file is restored {r.status_code} {r.text[:220]}")
check(r.ok and r.json().get("relogin") is True, f"1 new server: the first admin is not in the backup: sign in again {r.text[:200]}")
U = people()
same(snap(U), SEEN, "1 new server: the assembled file: content and file bytes as at the backup")
check(not state(U["alice"]).get("encrypt"), "1 new server: its own backup settings stay (no encryption here)")
U["alice"].patch(B + f"/api/tasks/{S.task}", json={"title": "anders"})
r = restore(U["alice"], upload=upload(U["alice"], DOWN), passphrase=PASSPHRASE)
check(r.ok, f"1 new server: the download restored as well {r.status_code} {r.text[:200]}")
U = people()
same(snap(U), SEEN, "1 new server: the download: content and file bytes as at the backup")
after_write(U["alice"], S.task)

# ================================================================== 3. from server A to a new server B with sealed files
start(K2, changed="")
R = new_admin()
assert R.post(B + "/api/lists", json={"name": "Bleibt hier"}).ok
before = len(state(R)["items"])
up = upload(R, COMPLETE)
v = verify(R, up, passphrase=PASSPHRASE)
check(v.ok and "another server key" in v.json().get("key_warning", ""), f"3: the check warns about the other key {v.status_code} {v.text[:220]}")
r = restore(R, upload=up, passphrase=PASSPHRASE)
check(r.status_code == 400 and r.json().get("code") == "server_key" and "Nothing was changed" in r.json().get("error", ""),
      f"3: another key: refused with the way out {r.status_code} {r.text[:220]}")
st = R.get(B + "/api/state")
check(st.ok and any(x["name"] == "Bleibt hier" for x in st.json()["lists"]), "3: B and its session are unchanged")
check(len(state(R)["items"]) == before and not leftovers(), f"3: refused before the safety backup, no leftovers {leftovers()}")
check(os.path.isfile(os.path.join(BK, ".uploads", up)), "3: the upload stays for another try")

start(K2, changed="1", keep=True)
R = sess("root")
r = restore(R, upload=upload(R, COMPLETE), passphrase=PASSPHRASE)
check(r.ok and "another server key" in r.json().get("key_warning", ""), f"3: KALMIDO_SECRET_KEY_CHANGED=1: restored with the warning {r.status_code} {r.text[:220]}")
check(health().ok, "3: the server answers without the key")
U = people()
for who, att, plain in (("alice", S.big, BIG), ("frida", S.fbig, FBIG)):
    g = U[who].get(B + f"/api/attachments/{att['id']}")
    check(g.status_code != 200 and plain[:2000] not in g.content and not g.content.startswith(MAGIC), f"3: {who}'s sealed file stays closed, no bytes come out {g.status_code} {g.text[:160]}")
    check(g.headers.get("content-type", "").startswith("application/json") and g.json().get("code") == "orgcrypt" and "KALMIDO_SECRET_KEY" in g.json().get("error", ""),
          f"3: {who}'s sealed file: the answer names the server key {g.status_code} {g.text[:160]}")
    st = U[who].get(B + "/api/state")
    check(st.ok, f"3: {who} signs in and reads the state {st.status_code} {st.text[:160]}")
    check(st.ok and not any(MAGIC.decode() in str(t.get("title")) for t in st.json().get("tasks", [])), f"3: {who}: no sealed value shows as a title")
check(os.path.isfile(stored(S.big)) and open(stored(S.big), "rb").read(6) == MAGIC, "3: the sealed file came along untouched")

start(K1, changed="1", keep=True)
U = people()
same(snap(U), SEEN, "3: the old key back in place: everything opens with its bytes")
g = U["alice"].get(B + f"/api/attachments/{S.big['id']}")
check(g.ok and g.content == BIG, f"3: the large sealed file opens again {g.status_code}")

# ================================================================== 2. a backup of release 2.101.0
with open(FIX + ".json", encoding="utf-8") as f:
    E = json.load(f)
OLD_FILE = ("1/a783ff7397d8-briefing.txt", b"Briefing Imagefilm\n" * 10)   # tests/upgrade_seed.py wrote this file


def old_backup():
    """A format-2 archive as bk_dump / bk_create of 2.101.0 wrote it (pg_dump -Fc -Z 6, the same manifest), from the dump of that
    release's database (tests/fixtures/upgrade); its database goes through a database of its own to come out as -Fc."""
    with open(os.path.join(DATA, ".kalmido-db"), encoding="utf-8") as f:
        dbc, dbn = f.read().split()
    aux = dbn + "old"
    psql("-c", f"DROP DATABASE IF EXISTS {aux} WITH (FORCE)", "-c", f"CREATE DATABASE {aux}", data="kalmido")
    with gzip.open(FIX + ".sql.gz", "rb") as f:
        r = subprocess.run(["docker", "exec", "-i", dbc, "psql", "-U", "kalmido", "-v", "ON_ERROR_STOP=1", "-q", "-d", aux], input=f.read(), capture_output=True)
    assert r.returncode == 0, r.stderr.decode()[-1500:]
    r = subprocess.run(["docker", "exec", dbc, "pg_dump", "-U", "kalmido", "-Fc", "-Z", "6", "--enable-row-security", "-d", aux], capture_output=True)
    assert r.returncode == 0, r.stderr.decode()[-1500:]
    dump = r.stdout
    counts = {k: int(psql("-c", f"SELECT COUNT(*) FROM {k}", data=aux)) for k in ("users", "lists", "tasks", "attachments")}
    psql("-c", f"DROP DATABASE {aux} WITH (FORCE)", data="kalmido")
    name, data = "attachments/" + OLD_FILE[0], OLD_FILE[1]
    files = [["kalmido.dump", len(dump), hashlib.sha256(dump).hexdigest()], [name, len(data), hashlib.sha256(data).hexdigest()]]
    man = {"format": "kalmido-backup", "format_version": 2, "app_version": E["version"], "schema_version": 2, "created_at": "2026-10-23T06:10:00+00:00",
           "kind": "manual", "counts": counts, "db_bytes": len(dump), "attachment_files": 1, "attachment_bytes": len(data), "skipped_files": 0, "files": files}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("kalmido.dump", dump)
        z.writestr(name, data)
        z.writestr("manifest.json", json.dumps(man))
    return buf.getvalue()


start()
R = new_admin()
REF = schema()
check(len(REF["cols"]) > 500 and REF["policies"], "2: the schema of a new server read")
OLD = old_backup()
up = upload(R, OLD)
v = verify(R, up)
check(v.ok and v.json().get("app_version") == E["version"] and v.json().get("attachment_files") == 1 and "another server key" in v.json().get("key_warning", ""),
      f"2: the old backup checks fine, the warning says its tokens may need entering again {v.status_code} {v.text[:300]}")
r = restore(R, upload=up)
assert check(r.ok, f"2: the backup of {E['version']} is restored {r.status_code} {r.text[:300]}"), kt.done("p4286_restore")
tag = "2: from " + E["version"]
log = logs()
check("step(s) applied" in log, f"{tag}: the migrations ran")
meta = dict(kt.dbx("SELECT key, value FROM kalmido_meta"))
VERSION = open(os.path.join(N, "..", "VERSION"), encoding="utf-8").read().strip()
check(meta.get("app_version") == VERSION, f"{tag}: kalmido_meta.app_version = {VERSION} ({meta.get('app_version')})")
gaps, _ = schema_gaps(REF, schema())
check(not gaps, f"{tag}: the schema holds everything of a new server ({len(gaps)} gaps): {gaps[:20]}")
users = data_checks(E, tag)
g = users["alice"].get(B + f"/api/attachments/{kt.dbx('SELECT id FROM attachments WHERE path=?', (OLD_FILE[0],))[0][0]}")
check(g.ok and g.content == OLD_FILE[1], f"{tag}: the old file has its bytes {g.status_code} {g.content[:40]!r}")
ids = E["ids"]
r = users["alice"].post(B + "/api/tasks", json={"list_id": ids["team"], "title": "Nach dem Einspielen", "due": "2027-06-01"})
check(r.ok and users["bob"].get(B + f"/api/tasks/{r.json().get('id')}").ok, f"{tag}: a new task in the old project, bob sees it {r.status_code}")
check(users["frida"].patch(B + f"/api/tasks/{ids['frida_task']}", json={"title": "Website-Texte (neu)"}).ok, f"{tag}: frida edits her task")
after_write(users["alice"], ids["t1"])
snap2 = schema()
start(keep=True)
check("step(s) applied" not in logs(), f"{tag}: a second start applies no migration step")
check(schema() == snap2, f"{tag}: the second start leaves the schema as it is")
titles = {t["title"] for t in sess("alice").get(B + "/api/state").json()["tasks"]}
check("Nach dem Einspielen" in titles and "Imagefilm schneiden" in titles, f"{tag}: old and new tasks after the second start")

# ================================================================== 4. init_db fails after pg_restore
start(K1)
A = new_admin("alice")
S, Fr = seed(A)
GOOD = backup_now(A)["name"]
GOOD_SEEN = snap({"alice": A, "frida": Fr})
REF = schema()


def defect():
    """A row pair the unique index cannot hold, and without the index: pg_restore takes it, init_db cannot build the index."""
    psql("-c", f"DROP INDEX list_tags_name; INSERT INTO list_tags(list_id, name, created_at) VALUES ({S.list}, 'dup', '2026-01-01'), ({S.list}, 'DUP', '2026-01-01')")


def heal():
    psql("-c", "DELETE FROM list_tags WHERE lower(name)='dup'; CREATE UNIQUE INDEX list_tags_name ON list_tags(list_id, lower(name))")


defect()
BAD = backup_now(A)["name"]
heal()
check(verify(A, BAD).ok, "4: the check cannot see this defect (only the real restore meets it)")
assert A.post(B + "/api/tasks", json={"title": "vor dem Versuch", "list_id": S.list}).ok
before = len(state(A)["items"])
BEFORE = snap({"alice": A, "frida": sess("frida")})

t0 = time.time()
r = restore(A, name=BAD)
j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
check(r.status_code == 400 and j.get("code") == "restore" and "nothing was changed" in j.get("error", ""),
      f"4 way back works: a clear message {r.status_code} {r.text[:240]}")
check("restore failed:" in logs() and "list_tags_name" in logs(), "4 way back works: the log names what init_db met (pg_restore had gone through)")
check(health().ok, "4 way back works: the server is healthy")
A2 = sess("alice")
same(snap({"alice": A2, "frida": sess("frida")}), BEFORE, "4 way back works: the state of before, with its files")
gaps, _ = schema_gaps(REF, schema())
check(not gaps, f"4 way back works: the schema is complete ({len(gaps)} gaps): {gaps[:20]}")
check(not leftovers(), f"4 way back works: no folder of the restore is left {leftovers()}")
st = state(A2)
check(not st["running"] and len(st["items"]) == before + 1 and any(x["kind"] == "safety" for x in st["items"]), f"4 way back works: nothing runs any more, the safety backup is there {st['running']}")
r = restore(A2, name=GOOD)
check(r.ok, f"4: the next restore goes through {r.status_code} {r.text[:240]}")
same(snap(people()), GOOD_SEEN, "4: ... with the content of its backup")

# ---- the way back fails as well: the database of before carries the same defect
A = sess("alice")
defect()
r = restore(A, name=BAD)
j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
safety = next((w for w in (j.get("error") or "").split() if w.startswith("kalmido-backup-")), "")
check(r.status_code == 400 and j.get("code") == "rollback" and "kalmido-backup-" in j.get("error", "") and "nothing was changed" not in j.get("error", ""),
      f"4 way back fails: the message names the safety backup, never 'nothing was changed' {r.status_code} {r.text[:240]}")
h = health()
check(h.status_code == 503 and h.json().get("ok") is False, f"4 way back fails: /api/health does not call this half a server healthy {h.status_code} {h.text[:200]}")
print("   info: policies / triggers on the half server:", kt.dbx("SELECT COUNT(*) FROM pg_policies")[0][0], "of", len(REF["policies"]), "/",
      kt.dbx("SELECT COUNT(DISTINCT trigger_name) FROM information_schema.triggers WHERE trigger_schema='public'")[0][0], flush=True)
for what, rr in (("the state", A.get(B + "/api/state")), ("a sign-in", sess().post(B + "/api/auth/login", json={"username": "alice", "password": PASSWORD})),
                 ("another restore", restore(A, name=GOOD))):
    check(rr.status_code == 503 and "restart" in rr.json().get("error", "") and "kalmido-backup-" not in rr.json().get("error", ""),
          f"4 way back fails: {what}: closed, says what to do, the name of the safety backup only to the one who restored {rr.status_code} {rr.text[:240]}")
try:  # the defect is still in the database: the start cannot complete it and must not come up as half a server
    start(K1, keep=True, wait="25")
    check(False, "4 way back fails: a start on the defect does not come up")
except AssertionError:
    check("list_tags_name" in logs(), "4 way back fails: a start on the defect stops and its log names the reason")
psql("-c", "DELETE FROM list_tags WHERE lower(name)='dup'")
start(K1, keep=True)
check(health().ok, "4 way back fails: the restart without the defect completes the database, healthy again")
gaps, _ = schema_gaps(REF, schema())
check(not gaps, f"4 way back fails: the schema is complete again ({len(gaps)} gaps): {gaps[:20]}")
same(snap(people()), GOOD_SEEN, "4 way back fails: the state of before, with its files")
A = sess("alice")
check(any(x["name"] == safety for x in state(A)["items"]), f"4 way back fails: the named safety backup is in the list {safety}")
r = restore(A, name=GOOD)
check(r.ok, f"4 way back fails: the next restore goes through {r.status_code} {r.text[:240]}")
same(snap(people()), GOOD_SEEN, "4 way back fails: ... with the content of its backup")

# ---- a hard stop between pg_restore and init_db
A = sess("alice")
assert A.post(B + "/api/tasks", json={"title": "vor dem harten Halt", "list_id": S.list}).ok
STOP = """
import os, sys
from kalmido.admin import backup as bk
bk.init_db = lambda **k: os._exit(9)   # the process ends where init_db would start
bk.bk_restore(os.path.join(bk.BK_DIR, sys.argv[1]), "", "alice", "session")
"""
r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", STOP, GOOD], capture_output=True, text=True, timeout=300)
check(r.returncode == 9, f"4 hard stop: the process ended between pg_restore and init_db {r.returncode} {r.stderr[-400:]}")
work = [p for p in glob.glob(os.path.join(BK, ".restore-*")) if glob.glob(os.path.join(p, "*.dump"))]
check(work, "4 hard stop: the work folder of the restore lies in the backup folder with its plain dump")
start(K1, keep=True)
check("folders left from a restore" in logs(), "4 hard stop: the log of the next start names the folders of before")
A = sess("alice")
same(snap({"alice": A, "frida": sess("frida")}), GOOD_SEEN, "4 hard stop: the next start finishes the job: the backup's content with its files")
gaps, _ = schema_gaps(REF, schema())
check(not gaps, f"4 hard stop: the schema is complete ({len(gaps)} gaps): {gaps[:20]}")
left = state(A).get("leftovers") or []
check(len(left) == 2 and all(".pre-restore-" in x for x in left), f"4 hard stop: Backups in the settings names the folders of before {left}")
check(not [x for x in leftovers() if x.startswith(".restore-")], f"4 hard stop: the start removes the work folder with its plain dump {leftovers()}")
r = restore(A, name=GOOD)
check(r.ok, f"4 hard stop: the next restore goes through {r.status_code} {r.text[:240]}")
check(not [x for x in leftovers() if x.startswith(("attachments.", "office."))], f"4 hard stop: ... and clears the folders of before {leftovers()}")
same(snap(people()), GOOD_SEEN, "4 hard stop: ... with the content of its backup")

# ---- review of 2.510: the keys _pg_restore takes away: a key the backup does not know (added since), a hard stop before pg_restore
NEWFK = "ALTER TABLE list_tags ADD CONSTRAINT p4286_new_fk FOREIGN KEY (list_id) REFERENCES lists(id)"
hasfk = lambda: bool(kt.dbx("SELECT 1 FROM pg_constraint WHERE conname='p4286_new_fk'"))
NOTE = os.path.join(BK, ".dropped-fks.json")
psql("-c", NEWFK)
A = sess("alice")
r = restore(A, name=GOOD)
check(r.ok and hasfk() and not os.path.exists(NOTE), f"4 keys: a restore through: the key the backup does not know is there again, no list left {r.status_code} {hasfk()}")
STOP = """
import os, subprocess, sys
from kalmido.admin import backup as bk
real = subprocess.run
bk.subprocess.run = lambda a, *k, **kw: os._exit(9) if "pg_restore" in a[0] else real(a, *k, **kw)
bk.bk_restore(os.path.join(bk.BK_DIR, sys.argv[1]), "", "alice", "session")
"""
r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", STOP, GOOD], capture_output=True, text=True, timeout=300)
check(r.returncode == 9 and not hasfk() and os.path.exists(NOTE), f"4 keys: a hard stop just before pg_restore: the key is gone, the list knows it {r.returncode} {hasfk()} {r.stderr[-300:]}")
start(K1, keep=True)
check(hasfk() and not os.path.exists(NOTE), f"4 keys: the next start brings it back {hasfk()}")
psql("-c", "ALTER TABLE list_tags DROP CONSTRAINT p4286_new_fk")

# ---- review of 2.510: a helper imports the package beside a running restore or check: it leaves their work folders alone
MK = """
import os, time
from kalmido.admin.backup import BK_DIR
for n in (".restore-p4286", ".verify-young", ".verify-old"):
    os.makedirs(os.path.join(BK_DIR, n), exist_ok=True)
os.utime(os.path.join(BK_DIR, ".verify-old"), (time.time() - 172800, time.time() - 172800))
"""
subprocess.run(["docker", "exec", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", MK], check=True, timeout=120)
r = subprocess.run(["docker", "exec", CT, "python", "-c", "import app"], capture_output=True, text=True, timeout=120)
check(r.returncode == 0 and {".restore-p4286", ".verify-young", ".verify-old"} <= set(os.listdir(BK)), f"4 start clean: a helper removes no work folder {sorted(os.listdir(BK))[:12]} {r.stderr[-200:]}")
r = subprocess.run(["docker", "exec", "-e", "TASKS_WATCHDOG=0", "-e", "KALMIDO_ROLE=web", CT, "python", "-c", "from kalmido.admin import backup; backup.bk_start_clean()"], capture_output=True, text=True, timeout=120)
left = set(os.listdir(BK))
check(r.returncode == 0 and ".verify-young" in left and ".verify-old" not in left and ".restore-p4286" not in left,
      f"4 start clean: with several processes a young check stays, an old one and a restore's folder go {sorted(left)[:12]} {r.stderr[-200:]}")
start(K1, keep=True)
check(".verify-young" not in set(os.listdir(BK)), "4 start clean: a server alone removes every work folder")

sys.exit(kt.done("p4286_restore"))
