#!/usr/bin/env python3
# kalmido-suite:
# freelancer-matrix: own
"""2.432.0 (#3584): backups keep larger files ONCE in a shared store (BK_DIR/.store, kalmido/admin/bkstore.py). Own container.
 - a backup with files from 64 KiB on is format 3: its zip holds the dump, the small files and the manifest ("shared" =
   name, size, SHA-256), the larger files lie once in .store (plain/<ab>/<sha256>), .store/refs/<backup> names them
 - a second backup adds nothing to the store (store_new_bytes 0, the zip stays small); the list shows the store line
 - download = ONE complete format-2 file (every file inside, bytes equal); uploaded again it is checked fine
 - check / restore of a format-3 backup read the store (the restored file has its bytes again); a damaged store file =
   "hash", a missing one = "shared_missing" (count), nothing changed
 - encrypted: the store files lie in k-<kid>/ under a name that is not their SHA-256 and do not hold the plain bytes; the
   download is a complete .zip.enc of the same passphrase (decrypted here independently); after a new passphrase a new
   kid; the old backup is checked with the old passphrase, its download says "old_passphrase"
 - deleting backups frees store files no backup needs any more; a backup without its reference file stops that clean-up
 - off-site (fake S3): the shared files go up once (kalmido-blob-<kid>-<name>), a second upload sends no file again; old
   ones go with the backups that needed them; the assembler (bkstore.py assemble) makes a complete file from the flat copy
 - a person without an organisation: her large file is one of the shared files (restored, downloaded)
usage: p2432_bkstore_test.py <datadir>        (P2432_NOSTART=1: the server already runs with the settings below)"""
import base64
import glob
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile

import requests
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, check, dbx, done, fresh, sess, su_get, until  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
BK = os.path.join(DATA, "backups")
ST = os.path.join(BK, ".store")
H = {"X-Requested-With": "kalmido"}
PW = "password123"
PASS1, PASS2 = "first backup passphrase", "second backup passphrase"
S3KEY, S3SECRET = "AKFAKETESTKEY01", "s3-secret-for-the-test-9f2c"
OFF = B + "/api/admin/backups/offsite"
MAGIC, BLOB = b"KALMIDO-BACKUP-ENC\x00", b"KALMIDO-BLOB-ENC\x00"

fresh({"KALMIDO_BACKUP_TICK": "1", "KALMIDO_BACKUP_MAX_MB": "20", "KALMIDO_OFFSITE_RETRY_S": "1", "KALMIDO_OFFSITE_TIMEOUT": "10"},
      prefix="P2432", data=DATA)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": PW}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, Fr = freelancer(B, A)
A.patch(B + "/api/admin/backups", json={"on": False})

BIG = b"\x89PNG\r\n" + os.urandom(150 * 1024)   # above 64 KiB: shared
FBIG = b"%PDF-1.4\n" + os.urandom(90 * 1024)    # the freelancer's own (shared)
SMALL = b"a small note\n" * 40                   # stays in the zip
L = A.post(B + "/api/lists", json={"name": "Home"}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"title": "with files", "list_id": L}).json()["id"]
ATT_BIG = A.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("pic.png", BIG, "image/png")}).json()["attachments"][0]
A.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("note.txt", SMALL, "text/plain")})
FT = Fr.post(B + "/api/tasks", json={"title": "own task"}).json()["id"]
r = Fr.post(B + f"/api/tasks/{FT}/attachments", files={"file": ("offer.pdf", FBIG, "application/pdf")})
check(r.ok, f"setup: the freelancer's own file {r.status_code}")
F_ATT = r.json()["attachments"][0]
SHA = {hashlib.sha256(x).hexdigest(): x for x in (BIG, FBIG)}


def state():
    return A.get(B + "/api/admin/backups").json()


def backup_now():
    before = {x["name"] for x in state()["items"]}
    r = A.post(B + "/api/admin/backups")
    assert r.status_code == 202, r.text
    new = until(lambda: (lambda j: not j["running"] and [x for x in j["items"] if x["name"] not in before])(state()), 60)
    return new[0] if new else {}


def store_files(top=None):
    return sorted(p for p in glob.glob(os.path.join(ST, top or "*", "??", "*")) if os.path.isfile(p))


def dec(data, pw):
    """Independent reader of the encrypted backup format (README: backups) -> (header, plain bytes)."""
    n = struct.unpack(">I", data[len(MAGIC):len(MAGIC) + 4])[0]
    raw = data[len(MAGIC) + 4:len(MAGIC) + 4 + n]
    h = json.loads(raw)
    key = Scrypt(salt=base64.urlsafe_b64decode(h["salt"] + "=" * (-len(h["salt"]) % 4)), length=32,
                 n=h["n"], r=h["r"], p=h["p"]).derive(pw.encode())
    aes, hh, pos, i, out = AESGCM(key), hashlib.sha256(MAGIC + raw).digest(), len(MAGIC) + 4 + n, 0, b""
    while True:
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        ct = data[pos + 4:pos + 4 + ln]
        pos += 4 + ln
        for last in (0, 1):
            try:
                out += aes.decrypt(struct.pack(">IQ", 0, i), ct, hh + struct.pack(">QB", i, last))
                break
            except InvalidTag:
                continue
        else:
            raise ValueError("chunk")
        if last:
            assert pos == len(data)
            return h, out
        i += 1


def members(zbytes):
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        return json.loads(z.read("manifest.json")), {i.filename: z.read(i) for i in z.infolist() if i.filename != "manifest.json"}


def restore(**b):
    return A.post(B + "/api/admin/backups/restore", json={"password": PW, "confirm": "RESTORE", **b})


def upload(data):
    return A.post(B + "/api/admin/backups/upload", data=data, headers={"Content-Type": "application/octet-stream"})


# ============================================================== format 3, plain
x1 = backup_now()
p1 = os.path.join(BK, x1.get("name", "-"))
check(x1.get("name", "").endswith(".zip") and os.path.isfile(p1), f"a backup was written {x1.get('name')}")
man, mem = members(open(p1, "rb").read())
shared = {f[2]: f for f in man.get("shared", [])}
check(man.get("format_version") == 3 and set(shared) == set(SHA) and man.get("store") == "plain",
      f"format 3: both large files are shared, plain store {man.get('format_version')} {len(shared)} {man.get('store')}")
check(not any(v in (BIG, FBIG) for v in mem.values()) and SMALL in mem.values() and "kalmido.dump" in mem,
      f"the zip holds the dump and the small file, not the large ones {sorted(mem)}")
check(all(open(os.path.join(ST, "plain", s[:2], s), "rb").read() == SHA[s] for s in SHA), "each large file lies once in .store/plain/<ab>/<sha256>")
refs = open(os.path.join(ST, "refs", x1["name"])).read().split()
check(sorted(refs) == sorted(f"plain/{s[:2]}/{s}" for s in SHA), f"the reference file names exactly the two store files {refs}")
check(x1["shared_files"] == 2 and x1["store_new_bytes"] == len(BIG) + len(FBIG) and x1["attachment_files"] == 3,
      f"the list: 2 shared, their bytes new, 3 files in all {x1}")
check(x1["size"] < len(mem["kalmido.dump"]) + 64 * 1024, f"the backup file itself is the dump and the small files ({x1['size']} bytes)")
x2 = backup_now()
j = state()
check(x2["store_new_bytes"] == 0 and len(store_files()) == 2 and j["store_files"] == 2 and j["store_bytes"] == len(BIG) + len(FBIG),
      f"a second backup adds nothing to the store {x2.get('store_new_bytes')} {j.get('store_files')} {j.get('store_bytes')}")
check(j["total_bytes"] == sum(x["size"] for x in j["items"]) + j["store_bytes"], "the total counts the store once")

# ============================================================== download = a complete format-2 file
r = su_get(A, B + f"/api/admin/backups/{x1['name']}/download")
check(r.ok and r.headers.get("Cache-Control") == "no-store" and x1["name"] in r.headers.get("Content-Disposition", ""),
      f"download of a format-3 backup {r.status_code}")
dman, dmem = members(r.content)
check(dman.get("format_version") == 2 and "shared" not in dman and "store" not in dman
      and sorted(f[0] for f in dman["files"]) == sorted(dmem), f"the download is format 2 with every file listed {dman.get('format_version')}")
check(BIG in dmem.values() and FBIG in dmem.values() and SMALL in dmem.values()
      and all(hashlib.sha256(dmem[f[0]]).hexdigest() == f[2] and len(dmem[f[0]]) == f[1] for f in dman["files"]),
      "the download holds the large files with their bytes, every checksum fits")
up = upload(r.content)
check(up.ok and up.json().get("attachment_files") == 3, f"the downloaded file is taken as an upload {up.status_code} {up.text[:200]}")
v = A.post(B + f"/api/admin/backups/{up.json().get('upload', 'x')}/verify", json={})
check(v.ok and v.json().get("ok"), f"... and checked fine {v.status_code} {v.text[:200]}")
raw_up = upload(open(p1, "rb").read()).json().get("upload", "x")  # the raw format-3 zip (needs the store of this server)

# ============================================================== check / restore from the store
v = A.post(B + f"/api/admin/backups/{x1['name']}/verify", json={})
check(v.ok and v.json().get("attachment_files") == 3, f"check of a format-3 backup reads the store {v.status_code} {v.text[:200]}")
v = A.post(B + f"/api/admin/backups/{raw_up}/verify", json={})
check(v.ok, f"an uploaded format-3 zip is checked with this server's store {v.status_code} {v.text[:160]}")
sp = os.path.join(ST, "plain", hashlib.sha256(BIG).hexdigest()[:2], hashlib.sha256(BIG).hexdigest())
good = open(sp, "rb").read()
open(sp, "wb").write(good[:-1] + bytes([good[-1] ^ 1]))
v = A.post(B + f"/api/admin/backups/{x1['name']}/verify", json={})
check(v.status_code == 400 and v.json().get("code") == "hash", f"a damaged store file = hash {v.status_code} {v.text[:160]}")
os.remove(sp)
v = A.post(B + f"/api/admin/backups/{x1['name']}/verify", json={})
check(v.status_code == 400 and v.json().get("code") == "shared_missing" and "1 " in v.json().get("error", ""),
      f"a missing store file = shared_missing with the count {v.status_code} {v.text[:200]}")
r = restore(name=x1["name"])
check(r.status_code == 400 and r.json().get("code") == "shared_missing", f"... and the restore refuses it {r.status_code} {r.text[:160]}")
open(sp, "wb").write(good)
A.delete(B + f"/api/attachments/{ATT_BIG['id']}")
Fr.delete(B + f"/api/attachments/{F_ATT['id']}")
r = restore(name=x1["name"])
check(r.ok, f"restore of the format-3 backup {r.status_code} {r.text[:200]}")
A = sess("alice")
Fr = sess("frida")
g1 = A.get(B + f"/api/attachments/{ATT_BIG['id']}")
g2 = Fr.get(B + f"/api/attachments/{F_ATT['id']}")
check(g1.ok and g1.content == BIG, f"the large file is back with its bytes {g1.status_code}")
check(g2.ok and g2.content == FBIG, f"freelancer: her own large file is back {g2.status_code}")

# ============================================================== encrypted
check(A.patch(B + "/api/admin/backups", json={"encrypt": True, "passphrase": PASS1}).ok, "encryption on")
e1 = backup_now()
pe = os.path.join(BK, e1.get("name", "-"))
kdirs = [d for d in glob.glob(os.path.join(ST, "k-*")) if os.path.isdir(d)]
efiles = store_files("k-*")
check(e1.get("name", "").endswith(".zip.enc") and len(kdirs) == 1 and os.path.isfile(os.path.join(kdirs[0], "key.json")) and len(efiles) == 2,
      f"encrypted: one key folder with key.json, two store files {e1.get('name')} {len(kdirs)} {len(efiles)}")
check(not any(os.path.basename(f) in SHA for f in efiles), "the encrypted store files are not named by their SHA-256")
check(all(open(f, "rb").read().startswith(BLOB) and BIG[1000:1400] not in open(f, "rb").read() and FBIG[1000:1400] not in open(f, "rb").read()
          for f in efiles), "the encrypted store files hold no plain bytes")
h, plain = dec(open(pe, "rb").read(), PASS1)
eman, emem = members(plain)
check(eman.get("format_version") == 3 and eman["store"]["kid"] == os.path.basename(kdirs[0])[2:] and h["meta"]["format_version"] == 3,
      f"the encrypted backup is format 3 with its store key {eman.get('store')}")
r = su_get(A, B + f"/api/admin/backups/{e1['name']}/download")
check(r.ok and r.content.startswith(MAGIC), f"download of the encrypted backup {r.status_code}")
dh, dplain = dec(r.content, PASS1)
dman, dmem = members(dplain)
check(dman.get("format_version") == 2 and dh["meta"]["format_version"] == 2 and BIG in dmem.values() and FBIG in dmem.values(),
      "the download is a complete encrypted file (format 2) of the same passphrase")
v = A.post(B + f"/api/admin/backups/{e1['name']}/verify", json={})
check(v.ok, f"check of the encrypted format-3 backup {v.status_code} {v.text[:160]}")
check(A.patch(B + "/api/admin/backups", json={"passphrase": PASS2}).ok, "a new passphrase")
e2 = backup_now()
check(len([d for d in glob.glob(os.path.join(ST, "k-*")) if os.path.isdir(d)]) == 2 and len(store_files("k-*")) == 4,
      "a new passphrase = a new store key (its own two files)")
v = A.post(B + f"/api/admin/backups/{e1['name']}/verify", json={"passphrase": PASS1})
check(v.ok, f"the older backup is checked with the older passphrase {v.status_code} {v.text[:160]}")
r = su_get(A, B + f"/api/admin/backups/{e1['name']}/download")
check(r.status_code == 400 and r.json().get("code") == "old_passphrase", f"its download asks for the older passphrase {r.status_code} {r.text[:160]}")

# ============================================================== clean-up
stray = os.path.join(ST, "plain", "ab", "ab" + "0" * 62)
os.makedirs(os.path.dirname(stray), exist_ok=True)
open(stray, "wb").write(b"no backup needs this")
os.rename(os.path.join(ST, "refs", e2["name"]), os.path.join(DATA, "refs.keep"))
A.delete(B + f"/api/admin/backups/{x2['name']}")
check(os.path.isfile(stray), "a backup without its reference file stops the clean-up (nothing goes)")
os.rename(os.path.join(DATA, "refs.keep"), os.path.join(ST, "refs", e2["name"]))
A.delete(B + f"/api/admin/backups/{x1['name']}")
j = state()
check(not os.path.isfile(stray) and not os.path.exists(os.path.join(ST, "refs", x1["name"])),
      "with the reference file back the clean-up runs: the stray file and the deleted backup's reference file go")
check(len(store_files("plain")) == 2, "the plain store files stay: the safety backup of the restore above still needs them")
for x in [x for x in j["items"] if x["kind"] == "safety"]:
    A.delete(B + f"/api/admin/backups/{x['name']}")
check(not store_files("plain") and len(store_files("k-*")) == 4,
      f"no plain backup left: their store files go, the encrypted ones stay {len(store_files('plain'))} {len(store_files('k-*'))}")
v = A.post(B + f"/api/admin/backups/{raw_up}/verify", json={})
check(v.status_code == 400 and v.json().get("code") == "shared_missing", f"the uploaded format-3 zip now misses its files {v.status_code} {v.text[:160]}")

# ============================================================== off-site (fake S3): only new files go up
REM = os.path.join(DATA, "fake-remote")
shutil.copy(os.path.join(N, "fake_offsite.py"), os.path.join(DATA, "fake_offsite.py"))
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_offsite.py", "s3", "8093", S3KEY, S3SECRET])
until(lambda: os.path.isdir(os.path.join(REM, "s3")), 10)
r = A.patch(OFF, json={"password": PW, "type": "s3", "s3": {"endpoint": "http://127.0.0.1:8093", "region": "eu-central-1", "bucket": "kbk",
                                                            "prefix": "/srv1/", "key": S3KEY, "secret": S3SECRET}})
check(r.ok, f"setup: S3 target {r.status_code} {r.text[:160]}")
check(A.patch(OFF, json={"password": PW, "on": True, "keep": 2}).ok, "setup: off-site on, keep 2")
REMD = os.path.join(REM, "s3", "kbk", "srv1")


def blobs():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(REMD, "kalmido-blob-*")))


def puts():
    try:
        return [json.loads(x) for x in open(os.path.join(REM, "s3.log")) if x.strip() and '"PUT"' in x and "kalmido-blob-" in x]
    except OSError:
        return []


o1 = backup_now()
check(until(lambda: A.get(OFF).json().get("last_name") == o1.get("name"), 60), f"the backup went up {A.get(OFF).json()}")
mine = [b for b in blobs() if b.startswith("kalmido-blob-")]
check(len(mine) == 2 and os.path.isfile(os.path.join(REMD, o1["name"])), f"the backup and its two shared files are on the target {blobs()}")
local = {os.path.basename(f): open(f, "rb").read() for f in store_files("k-*")}
check(all(open(os.path.join(REMD, b), "rb").read() == local.get(b.split("-", 3)[3]) for b in mine), "they have the bytes of the store files")
n_put = len(puts())
o2 = backup_now()
check(until(lambda: A.get(OFF).json().get("last_name") == o2.get("name"), 60), "the next backup went up")
check(len(puts()) == n_put, f"no shared file was sent again {len(puts())} vs {n_put}")
# the assembler: a complete file out of the flat off-site copy
pwf = os.path.join(DATA, "pass.txt")
open(pwf, "w").write(PASS2)
out = "/data/assembled.zip.enc"
r = subprocess.run(["docker", "exec", CT, "python", "-I", "/app/kalmido/admin/bkstore.py", "assemble", f"/data/fake-remote/s3/kbk/srv1/{o2['name']}",
                    "/data/fake-remote/s3/kbk/srv1", out, "--passphrase-file", "/data/pass.txt"], capture_output=True, text=True, timeout=120)
check(r.returncode == 0, f"assembler from the off-site copy {r.returncode} {r.stdout[-200:]} {r.stderr[-300:]}")
if r.returncode == 0:
    ah, ap = dec(open(os.path.join(DATA, "assembled.zip.enc"), "rb").read(), PASS2)
    aman, amem = members(ap)
    check(aman.get("format_version") == 2 and BIG in amem.values() and FBIG in amem.values(), "the assembled file is complete (format 2)")
    up = upload(open(os.path.join(DATA, "assembled.zip.enc"), "rb").read())
    v = A.post(B + f"/api/admin/backups/{up.json().get('upload', 'x')}/verify", json={"passphrase": PASS2})
    check(v.ok, f"... and taken as an upload and checked fine {v.status_code} {v.text[:160]}")
# a new large file + two more backups: the oldest backup leaves the target, its files stay while a kept one needs them
T2 = A.post(B + "/api/tasks", json={"title": "later", "list_id": L}).json()["id"]
NEW = os.urandom(100 * 1024)
A.post(B + f"/api/tasks/{T2}/attachments", files={"file": ("later.bin", NEW, "application/octet-stream")})
o3 = backup_now()
check(until(lambda: A.get(OFF).json().get("last_name") == o3.get("name"), 60), "a backup with a new file went up")
check(len(blobs()) == 3 and len(puts()) == n_put + 1, f"only the new file was sent {len(blobs())} {len(puts()) - n_put}")
kept = dbx("SELECT value FROM settings WHERE key='bko_remote'", data=DATA)
check(kept and json.loads(kept[0][0]) == sorted([o2["name"], o3["name"]], reverse=True), f"the kept names on the target are remembered (bko_remote) {kept}")
kid3 = members(dec(open(os.path.join(BK, o3["name"]), "rb").read(), PASS2)[1])[0]["store"]["kid"]
check(all(b.startswith(f"kalmido-blob-{kid3}-") for b in blobs()), f"the files on the target carry the store key's id {kid3}")
sys.exit(done("p2432_bkstore"))
