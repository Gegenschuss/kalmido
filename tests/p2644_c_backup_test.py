#!/usr/bin/env python3
# kalmido-suite:
# freelancer-matrix: admin  (the server's backups are the operator's administration; no organisation involved, no new route)
"""2.644.0 part C (#4530): backups, the readers' lock of the shared store. Own container.
 - (L2) while a clean-up holds the readers' lock the download says "store_busy" (409) with its own text (the clean-up of
   the backup folder), not "busy" (another backup or restore)
 - (L1) the GET of a format-3 download with a ticket while a clean-up runs: 409 store_busy and the one-time ticket is NOT
   used up - once the clean-up let go, the same ticket downloads the complete file; a second use of it is refused (403)
 - (L1, the race) a clean-up that tries to start while a GET waits between its used ticket and the stream does not get
   the lock (the download took it before the ticket); the download then comes complete
 - (L3) a check (verify) holds the lock only for the server's own format-3 backups: an uploaded archive and an own
   format-2 backup are checked while a clean-up runs; an own format-3 one still says store_busy
 - (counter) a check with a typed-in passphrase that does not fit counts as a failed try (as the restore): after the
   limit the check says 429; a check with the saved passphrase is not held up by it
usage: p2644_c_backup_test.py <datadir>        (P2644C_NOSTART=1: the server already runs with the settings below)"""
import io
import json
import os
import subprocess
import sys
import threading
import zipfile
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from kt import B, CT, PASSWORD, check, done, fresh, sess, until  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
BK = os.path.join(DATA, "backups")
H = {"X-Requested-With": "kalmido"}
PASS1 = "first backup passphrase"
CLOCK = "/data/backups/.store/.read-lock"      # the readers' lock, seen from inside the container
HELD, RELEASE = os.path.join(DATA, "holder.held"), os.path.join(DATA, "holder.release")
TKG = os.path.join(DATA, "tk-gate")            # the GET waits after its ticket until this exists (open by default)
NBRES = os.path.join(DATA, "nb.res")

fresh({"KALMIDO_TEST_BK_DL_TICKET_GATE": "/data/tk-gate"}, prefix="P2644C", data=DATA)
open(TKG, "w").close()
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


def bkname(t, kind, enc=False):
    return f"kalmido-backup-{t.strftime('%Y%m%d-%H%M%S')}-{kind}.zip" + (".enc" if enc else "")


def lock_free():
    """True when nobody holds the readers' lock (checked inside the container: the flock of the app's processes)."""
    code = ("import fcntl, os, sys\n"
            f"p = {CLOCK!r}\n"
            "if not os.path.exists(p): sys.exit(0)\n"
            "fd = os.open(p, os.O_RDONLY)\n"
            "try:\n    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "except BlockingIOError:\n    sys.exit(1)\n")
    return subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True).returncode == 0


def hold():
    """A clean-up holds the readers' lock (exclusive) until release()."""
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


def release():
    open(RELEASE, "w").close()
    check(until(lock_free, 15), "setup: the clean-up let go")


def members(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return json.loads(z.read("manifest.json")), [z.read(i) for i in z.infolist() if i.filename != "manifest.json"]


# ============================================================== setup: a plain format-3 backup
BIG = b"\x89PNG\r\n" + os.urandom(200 * 1024)   # above 64 KiB: shared (format 3)
L = A.post(B + "/api/lists", json={"name": "Home"}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"title": "with a file", "list_id": L}).json()["id"]
check(A.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("pic.png", BIG, "image/png")}).ok, "setup: attachment")
x = backup_now()
check(x.get("name", "").endswith(".zip") and x.get("shared_files") == 1, f"setup: a plain format-3 backup {x}")
url = B + f"/api/admin/backups/{x.get('name', '-')}/download"
t0 = A.post(url, json={"password": PASSWORD}).json().get("ticket", "")
r0 = A.get(url, params={"t": t0})
check(r0.ok and members(r0.content)[0].get("format_version") == 2, f"setup: its download is a complete format-2 archive {r0.status_code}")
F2 = r0.content
up = A.post(B + "/api/admin/backups/upload", data=F2, headers={"Content-Type": "application/octet-stream"})
check(up.ok and up.json().get("upload", "").startswith("upload-"), f"setup: the download uploaded again {up.status_code} {up.text[:160]}")
own2 = bkname(testclock.now() - timedelta(days=1), "manual")
open(os.path.join(BK, own2), "wb").write(F2)  # an own backup of format 2 (no shared files)
ticket = A.post(url, json={"password": PASSWORD}).json().get("ticket", "")
check(bool(ticket), "setup: a ticket for the download")

# ============================================================== while a clean-up holds the lock
hold()
# (L2) its own code and text
r = A.post(url, json={"password": PASSWORD})
j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
check(r.status_code == 409 and j.get("code") == "store_busy", f"(L2) the POST says store_busy {r.status_code} {r.text[:160]}")
check("cleaned up" in j.get("error", "") and "Another backup" not in j.get("error", ""),
      f"(L2) the text names the clean-up of the backup folder, not another backup or restore: {j.get('error')!r}")
# (L1) the GET with the ticket: busy, the ticket stays
r = A.get(url, params={"t": ticket})
check(r.status_code == 409 and r.json().get("code") == "store_busy", f"(L1) the GET with a ticket says store_busy {r.status_code} {r.text[:160]}")
# (L3) the check takes the lock only for an own format-3 backup
v = A.post(B + f"/api/admin/backups/{up.json().get('upload', 'x')}/verify", json={})
check(v.ok, f"(L3) an uploaded archive is checked while a clean-up runs {v.status_code} {v.text[:160]}")
v = A.post(B + f"/api/admin/backups/{own2}/verify", json={})
check(v.ok, f"(L3) an own format-2 backup is checked while a clean-up runs {v.status_code} {v.text[:160]}")
v = A.post(B + f"/api/admin/backups/{x.get('name', '-')}/verify", json={})
check(v.status_code == 409 and v.json().get("code") == "store_busy", f"(L3) an own format-3 backup still waits for the clean-up {v.status_code} {v.text[:160]}")
release()

# (L1) the same ticket works after the clean-up, once
r = A.get(url, params={"t": ticket})
ok = r.ok and r.headers.get("content-type", "").startswith("application/octet-stream")
try:
    dman, dmem = members(r.content) if ok else ({}, [])
except (zipfile.BadZipFile, KeyError, ValueError):
    dman, dmem = {}, []
check(ok and dman.get("format_version") == 2 and BIG in dmem, f"(L1) the ticket of before downloads the complete file after the clean-up {r.status_code} {r.text[:120] if not ok else ''}")
r = A.get(url, params={"t": ticket})
check(r.status_code == 403, f"(L1) the ticket is used once only {r.status_code}")
check(until(lock_free, 15), "after the download the lock is free")

# (L1, the race) a clean-up tries to start while the GET waits between its used ticket and the stream
for p in (TKG, TKG + ".at", NBRES, RELEASE):
    if os.path.exists(p):
        os.remove(p)
t2 = A.post(url, json={"password": PASSWORD}).json().get("ticket", "")
got = {}
th = threading.Thread(target=lambda: got.update(r=A.get(url, params={"t": t2})))
th.start()
check(until(lambda: os.path.exists(TKG + ".at"), 15), "setup: the GET used its ticket and waits before the stream")
trylock = ("import fcntl, os, time\n"
           f"fd = os.open({CLOCK!r}, os.O_RDONLY)\n"
           "try:\n    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
           "except BlockingIOError:\n    open('/data/nb.res', 'w').write('refused')\n    raise SystemExit\n"
           "open('/data/nb.res', 'w').write('held')\n"
           "end = time.time() + 30\n"
           "while not os.path.exists('/data/holder.release') and time.time() < end:\n    time.sleep(0.05)\n")
subprocess.run(["docker", "exec", "-d", CT, "python", "-c", trylock], check=True)
check(until(lambda: os.path.exists(NBRES) and open(NBRES).read() in ("held", "refused"), 15), "setup: the clean-up tried to take the lock")
res = open(NBRES).read() if os.path.exists(NBRES) else ""
check(res == "refused", f"(L1) the clean-up does not get the lock while the download waits after its ticket ({res})")
open(TKG, "w").close()
th.join(60)
r = got.get("r")
ok = r is not None and r.ok and r.headers.get("content-type", "").startswith("application/octet-stream")
try:
    dman, dmem = members(r.content) if ok else ({}, [])
except (zipfile.BadZipFile, KeyError, ValueError):
    dman, dmem = {}, []
check(ok and BIG in dmem, f"(L1) that download comes complete (not busy with a used ticket) {r.status_code if r is not None else '-'} {r.text[:120] if r is not None and not ok else ''}")
open(RELEASE, "w").close()
check(until(lock_free, 15), "after the download the lock is free")

# ============================================================== (counter) a typed-in passphrase on the check counts
check(A.patch(B + "/api/admin/backups", json={"encrypt": True, "passphrase": PASS1}).ok, "setup: encryption on")
e1 = backup_now()
check(e1.get("name", "").endswith(".zip.enc"), f"setup: an encrypted backup {e1}")
ve = B + f"/api/admin/backups/{e1.get('name', '-')}/verify"
codes = [A.post(ve, json={"passphrase": f"not this one {i}"}).status_code for i in range(5)]
check(codes == [400] * 5, f"five checks with a wrong typed-in passphrase: refused {codes}")
v = A.post(ve, json={"passphrase": "not this one 6"})
check(v.status_code == 429, f"the sixth try is held up (counted as on the restore) {v.status_code} {v.text[:160]}")
v = A.post(ve, json={})
check(v.ok, f"a check with the saved passphrase is not a guess and goes on {v.status_code} {v.text[:160]}")
sys.exit(done("p2644_c_backup"))
