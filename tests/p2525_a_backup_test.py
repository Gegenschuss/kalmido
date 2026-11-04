#!/usr/bin/env python3
# kalmido-suite:
# freelancer-matrix: admin  (the server's backups are the operator's administration; no organisation involved, no new route)
"""2.525.0 part A (#4303): backups. Own container.
 - (1) a manual backup ("Back up now") is kept like a safety backup: the last 3 manual ones stay, also when an automatic
   backup of the same day is newer; the 4th manual one (and older) is in the normal rotation and goes there
 - (2) check and restore of an own backup made with an earlier passphrase say "old_passphrase" (as the download does
   since #3613), a typed-in passphrase that does not fit stays "passphrase", a damaged file (broken off) too
 - (3) a download of a format-3 backup holds the readers' lock of the shared store: a delete (or the rotation) meanwhile
   removes none of its store files, the file comes complete; the clean-up runs next time; while a clean-up holds the lock
   the download says "busy" (409) on the POST and the GET; a client that goes away frees the lock
usage: p2525_a_backup_test.py <datadir>        (P2525A_NOSTART=1: the server already runs with the settings below)"""
import glob
import io
import json
import os
import struct
import subprocess
import sys
import zipfile
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from kt import B, CT, PASSWORD, check, done, fresh, sess, until  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
BK = os.path.join(DATA, "backups")
ST = os.path.join(BK, ".store")
H = {"X-Requested-With": "kalmido"}
PASS1, PASS2 = "first backup passphrase", "second backup passphrase"
MAGIC = b"KALMIDO-BACKUP-ENC\x00"
GATE = os.path.join(DATA, "dl-gate")           # the download waits before its first shared file until this exists
CLOCK = "/data/backups/.store/.read-lock"      # the readers' lock, seen from inside the container
HELD, RELEASE = os.path.join(DATA, "holder.held"), os.path.join(DATA, "holder.release")

fresh({"KALMIDO_TEST_BK_DL_GATE": "/data/dl-gate"}, prefix="P2525A", data=DATA)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": PASSWORD}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.patch(B + "/api/admin/backups", json={"on": False})


def state():
    return A.get(B + "/api/admin/backups").json()


def backup_now():
    before = {x["name"] for x in state()["items"]}
    r = A.post(B + "/api/admin/backups")
    assert r.status_code == 202, r.text
    new = until(lambda: (lambda j: not j["running"] and [x for x in j["items"] if x["name"] not in before])(state()), 60)
    return new[0] if new else {}


def restore(**b):
    return A.post(B + "/api/admin/backups/restore", json={"password": PASSWORD, "confirm": "RESTORE", **b})


def store_files(top="plain"):
    return sorted(p for p in glob.glob(os.path.join(ST, top, "??", "*")) if os.path.isfile(p))


def lock_free():
    """True when nobody holds the readers' lock (checked inside the container: the flock of the app's processes)."""
    code = ("import fcntl, os, sys\n"
            f"p = {CLOCK!r}\n"
            "if not os.path.exists(p): sys.exit(0)\n"
            "fd = os.open(p, os.O_RDONLY)\n"
            "try:\n    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "except BlockingIOError:\n    sys.exit(1)\n")
    return subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True).returncode == 0


def bkname(t, kind, enc=False):
    return f"kalmido-backup-{t.strftime('%Y%m%d-%H%M%S')}-{kind}.zip" + (".enc" if enc else "")


# ============================================================== (1) manual backups are kept like safety backups
x0 = backup_now()
check(x0.get("kind") == "manual", f"setup: a manual backup {x0}")
src = open(os.path.join(BK, x0["name"]), "rb").read()
now = testclock.now()
fake = {}
for d in (3, 4, 5, 6):
    day = now - timedelta(days=d)
    for kind, hh in (("auto", 3), ("manual", 10), ("auto", 15)):  # the automatic one of 15:00 is the newest of its day
        n = bkname(day.replace(hour=hh, minute=0, second=0, microsecond=0), kind)
        fake[(d, kind, hh)] = n
        open(os.path.join(BK, n), "wb").write(src)
x1 = backup_now()  # its rotation: manual ones now x1, x0, day 3 | day 4, 5, 6 only by the rotation
left = {x["name"] for x in state()["items"]}
check(fake[(3, "manual", 10)] in left, "the 3rd newest manual backup stays beside a newer automatic one of the same day")
check(fake[(4, "manual", 10)] not in left and fake[(5, "manual", 10)] not in left and fake[(6, "manual", 10)] not in left,
      f"the 4th newest manual backup and older ones are in the rotation (the day's newest is automatic): {sorted(left)}")
check(all(fake[(d, "auto", 15)] in left for d in (3, 4, 5, 6)) and not any(fake[(d, "auto", 3)] in left for d in (3, 4, 5, 6)),
      "the automatic rotation is unchanged (the newest of each day stays)")
check(x0["name"] in left and x1["name"] in left, "the two of today stay")
for n in fake.values():
    if os.path.exists(os.path.join(BK, n)):
        os.remove(os.path.join(BK, n))

# ============================================================== (2) check / restore of an earlier passphrase
BIG = b"\x89PNG\r\n" + os.urandom(200 * 1024)   # above 64 KiB: shared (format 3)
BIG2 = b"%PDF-1.4\n" + os.urandom(120 * 1024)
L = A.post(B + "/api/lists", json={"name": "Home"}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"title": "with files", "list_id": L}).json()["id"]
for fn, data, mt in (("pic.png", BIG, "image/png"), ("offer.pdf", BIG2, "application/pdf")):
    check(A.post(B + f"/api/tasks/{T1}/attachments", files={"file": (fn, data, mt)}).ok, f"setup: attachment {fn}")
check(A.patch(B + "/api/admin/backups", json={"encrypt": True, "passphrase": PASS1}).ok, "setup: encryption on")
e1 = backup_now()
check(e1.get("name", "").endswith(".zip.enc") and e1.get("shared_files") == 2, f"setup: an encrypted format-3 backup {e1}")
check(A.patch(B + "/api/admin/backups", json={"passphrase": PASS2}).ok, "setup: a new passphrase")
v = A.post(B + f"/api/admin/backups/{e1['name']}/verify", json={})
check(v.status_code == 400 and v.json().get("code") == "old_passphrase" and "earlier passphrase" in v.json().get("error", ""),
      f"check with the saved (newer) passphrase: old_passphrase {v.status_code} {v.text[:200]}")
v = A.post(B + f"/api/admin/backups/{e1['name']}/verify", json={"passphrase": "not this one"})
check(v.status_code == 400 and v.json().get("code") == "passphrase", f"check with a typed-in wrong passphrase: passphrase {v.status_code} {v.text[:160]}")
v = A.post(B + f"/api/admin/backups/{e1['name']}/verify", json={"passphrase": PASS1})
check(v.ok, f"check with the earlier passphrase works {v.status_code} {v.text[:160]}")
A.post(B + "/api/tasks", json={"title": "after the backup", "list_id": L})
r = restore(name=e1["name"])
check(r.status_code == 400 and r.json().get("code") == "old_passphrase", f"restore with the saved (newer) passphrase: old_passphrase {r.status_code} {r.text[:200]}")
r = restore(name=e1["name"], passphrase="not this one")
check(r.status_code == 400 and r.json().get("code") == "passphrase", f"restore with a typed-in wrong passphrase: passphrase {r.status_code} {r.text[:160]}")
check(any(t["title"] == "after the backup" for t in A.get(B + "/api/state").json()["tasks"]), "... nothing was restored")
e2 = backup_now()
raw = open(os.path.join(BK, e2["name"]), "rb").read()
hl = len(MAGIC) + 4 + struct.unpack(">I", raw[len(MAGIC):len(MAGIC) + 4])[0]
broken = bkname(testclock.now() - timedelta(days=1), "manual", enc=True)
open(os.path.join(BK, broken), "wb").write(raw[:hl])  # the header only: the file broke off before its first chunk
v = A.post(B + f"/api/admin/backups/{broken}/verify", json={})
check(v.status_code == 400 and v.json().get("code") == "passphrase", f"a broken-off file of the saved passphrase stays 'passphrase' (damaged) {v.status_code} {v.text[:160]}")
os.remove(os.path.join(BK, broken))
check(A.patch(B + "/api/admin/backups", json={"encrypt": False}).ok, "setup: encryption off")

# ============================================================== (3) a download and the clean-up of the store
x3 = backup_now()
check(x3.get("name", "").endswith(".zip") and x3.get("shared_files") == 2 and len(store_files()) == 2,
      f"setup: a plain format-3 backup, its two files in the store {x3} {len(store_files())}")
url = B + f"/api/admin/backups/{x3['name']}/download"

# a clean-up holds the lock: the download says busy (POST and GET), no broken file
ticket = A.post(url, json={"password": PASSWORD}).json().get("ticket", "")
for p in (HELD, RELEASE):
    if os.path.exists(p):
        os.remove(p)
holder = ("import fcntl, os, time\n"
          f"fd = os.open({CLOCK!r}, os.O_RDONLY)\n"
          "fcntl.flock(fd, fcntl.LOCK_EX)\n"
          "open('/data/holder.held', 'w').close()\n"
          "while not os.path.exists('/data/holder.release'):\n    time.sleep(0.05)\n")
subprocess.run(["docker", "exec", "-d", CT, "python", "-c", holder], check=True)
check(until(lambda: os.path.exists(HELD), 15), "setup: a clean-up holds the readers' lock")
r = A.post(url, json={"password": PASSWORD})
check(r.status_code == 409 and r.json().get("code") == "busy", f"while a clean-up runs the download says busy (POST) {r.status_code} {r.text[:160]}")
r = A.get(url, params={"t": ticket})
check(r.status_code == 409 and r.json().get("code") == "busy", f"... and on the GET with a ticket {r.status_code} {r.text[:160]}")
open(RELEASE, "w").close()
check(until(lock_free, 15), "setup: the clean-up let go")


def members(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return json.loads(z.read("manifest.json")), [z.read(i) for i in z.infolist() if i.filename != "manifest.json"]


# the backup is deleted while its download runs: its store files stay until the download is done
if os.path.exists(GATE):
    os.remove(GATE)
t = A.post(url, json={"password": PASSWORD}).json().get("ticket", "")
r = A.get(url, params={"t": t}, stream=True)
check(r.ok, f"the download starts {r.status_code}")
check(until(lambda: not lock_free(), 15), "the running download holds the readers' lock")
d = A.delete(B + f"/api/admin/backups/{x3['name']}")
check(d.ok and x3["name"] not in {x["name"] for x in d.json()["items"]}, f"the backup is deleted meanwhile {d.status_code}")
check(len(store_files()) == 2, f"its store files stay while it is downloaded {len(store_files())}")
open(GATE, "w").close()
try:
    body, broke = r.content, ""
except requests.exceptions.RequestException as e:
    body, broke = b"", type(e).__name__
try:
    dman, dmem = members(body)
except (zipfile.BadZipFile, KeyError, ValueError) as e:
    dman, dmem = {}, []
    broke = broke or type(e).__name__
check(not broke and dman.get("format_version") == 2 and BIG in dmem and BIG2 in dmem,
      f"the download comes complete, both shared files inside ({broke or len(body)})")
check(until(lock_free, 15), "after the download the lock is free")
d = A.delete(B + f"/api/admin/backups/{x1['name']}")  # the next clean-up
check(d.ok and until(lambda: not store_files(), 10), f"the next clean-up removes the store files no backup needs any more {len(store_files())}")

# a client that goes away while the download waits frees the lock
os.remove(GATE)
x4 = backup_now()
url4 = B + f"/api/admin/backups/{x4.get('name', '-')}/download"
t = A.post(url4, json={"password": PASSWORD}).json().get("ticket", "")
r = A.get(url4, params={"t": t}, stream=True)
check(r.ok and until(lambda: not lock_free(), 15), f"a second download holds the lock {r.status_code}")
r.close()
open(GATE, "w").close()
check(until(lock_free, 30), "the client went away: the lock is free again")
sys.exit(done("p2525_a_backup"))
