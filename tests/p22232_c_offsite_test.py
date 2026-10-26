#!/usr/bin/env python3
"""2.223.2 C (#2871) API tests, own container (start.sh, a server key; later restarted with KALMIDO_HOSTED=1, same data).

The off-site target of the backups (admin/offsite.py), its step-up and the export downloads behind it:
 - a new address of the target (WebDAV url, S3 endpoint / virtual-host bucket) drops the saved credentials unless new ones come
   in the same change: "Test" then never sends the old password to the new host (fake_offsite sees no request there)
 - step-up (orgcrypt.stepup_need, like the recovery key): changing the target, Test and Upload now answer 403 need=password
   without it, a wrong password 403, the right one goes; on / off and the count kept need none; a confirmed step-up holds
   for the session a few minutes (another session of the same person asks again)
 - the retention export of the own records (freelancer-matrix: office) and the export of the own office (organisation 0):
   POST with the step-up -> a one-time ticket, GET with it -> the file; a GET without / with a used / another person's
   ticket = 403
 - a restore keeps the current off-site target (bko_conf / bko_sec), not the one inside the backup
 - hosted (KALMIDO_HOSTED=1): http, 169.254.169.254, 127.0.0.1, 10.x, localhost refused when saving (400); a target saved
   before is refused when connecting ("blocked", no request reaches the fake); SFTP: no telling refused from timed out
usage: p22232_c_offsite_test.py <datadir>      (a fresh container; P22232C_NOSTART=1 = the server already runs, no restart)"""
import json
import os
import shutil
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, dbx, done, fresh, nostart, sess, su_get, until  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = "A" * 43 + "="
PW = "password123"
DAVPASS, S3KEY, S3SECRET = "dav-password-for-the-test-7b1e", "AKFAKETESTKEY01", "s3-secret-for-the-test-9f2c"
OFF = B + "/api/admin/backups/offsite"
RX = B + "/api/retention"

fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SECRET_KEY": KEY, "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_OFFSITE_TIMEOUT": "10"},
      prefix="P22232C", data=DATA)
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": PW}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
assert A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": PW, "email": "bob@example.com"}).ok
Bo = sess("bob")
FID, Fr = freelancer(B, A, features="cal,comments,collab,office,clients,docs,files")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
for mode, port in (("webdav", 8094), ("webdav", 8095), ("s3", 8093)):
    shutil.copy(os.path.join(N, "fake_offsite.py"), os.path.join(DATA, "fake_offsite.py"))
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_offsite.py", mode, str(port),
                    S3KEY if mode == "s3" else "kbk", S3SECRET if mode == "s3" else DAVPASS])
time.sleep(1.0)
REM = os.path.join(DATA, "fake-remote")


def dav_log():
    try:
        return [json.loads(x) for x in open(os.path.join(REM, "webdav.log")) if x.strip()]
    except OSError:
        return []


# ============================================================== step-up
DAV1 = {"url": "http://127.0.0.1:8094/dav/bk", "user": "kbk", "password": DAVPASS}
A2 = sess("alice")  # another session of the same admin: no step-up of its own yet
r = A2.patch(OFF, json={"type": "webdav", "webdav": DAV1})
check(r.status_code == 403 and r.json().get("need") == "password", f"step-up: the target without the password 403 need=password {r.status_code} {r.text[:200]}")
check(A2.get(OFF).json().get("type") == "", "step-up: nothing saved without it")
r = A2.patch(OFF, json={"type": "webdav", "webdav": DAV1, "password": "wrong-password"})
check(r.status_code == 403 and A2.get(OFF).json().get("type") == "", f"step-up: a wrong password 403, nothing saved {r.status_code}")
r = A.patch(OFF, json={"type": "webdav", "webdav": DAV1, "password": PW})
check(r.ok and r.json()["webdav"]["password_set"], f"step-up: with the password the target is saved {r.status_code} {r.text[:200]}")
check(A.patch(OFF, json={"webdav": {"user": "kbk"}}).ok, "step-up: holds for this session a few minutes (no second question)")
A3 = sess("alice")
check(A3.patch(OFF, json={"keep": 3}).ok and A3.patch(OFF, json={"on": False}).ok, "step-up: on / off and the count kept need none")
for m, path in (("PATCH", ""), ("POST", "/test"), ("POST", "/upload")):
    r = A3.request(m, OFF + path, json={"webdav": {"user": "kbk"}} if m == "PATCH" else {})
    check(r.status_code == 403 and r.json().get("need") == "password", f"step-up: {m} offsite{path} without it 403 ({r.status_code})")
check(Bo.patch(OFF, json={"type": "s3", "password": PW}).status_code == 403, "not an instance admin: 403 as before (also with a password)")
r = A3.post(OFF + "/test", json={"password": PW})
check(r.ok and r.json().get("ok") is True, f"Test with the step-up works {r.text[:300]}")
check(any(x["path"].startswith("/dav/bk/kalmido-probe-") and x["sig"] for x in dav_log()), "Test: the probe reached the first WebDAV with its password")

# ============================================================== a new address drops the credentials
n0 = len(dav_log())
r = A.patch(OFF, json={"webdav": {"url": "http://127.0.0.1:8095/dav2/bk"}})
j = r.json() if r.ok else {}
check(r.ok and j["webdav"]["password_set"] is False and "dav_pass" in j.get("missing", []),
      f"WebDAV: another address without a password: the saved one is gone, the target says it is missing {r.text[:300]}")
j = A.post(OFF + "/test").json()
check(j.get("ok") is False and j.get("code") == "incomplete", f"Test then: incomplete, nothing is sent {j}")
check(not any(x["path"].startswith("/dav2/") for x in dav_log()[n0:]), "the new host saw no request (no old password at another host)")
r = A.patch(OFF, json={"webdav": {"url": "http://127.0.0.1:8095/dav2/bk", "password": DAVPASS}})
check(r.ok and r.json()["webdav"]["password_set"], "WebDAV: a new password with the new address is kept")
j = A.post(OFF + "/test").json()
check(j.get("ok") is True and any(x["path"].startswith("/dav2/") and x["sig"] for x in dav_log()), f"Test at the new host with its own password {j}")
check(A.patch(OFF, json={"webdav": {"user": "kbk"}}).json()["webdav"]["password_set"], "WebDAV: another user name alone keeps the password")
# S3: endpoint and (virtual-host style) bucket are the host
r = A.patch(OFF, json={"type": "s3", "s3": {"endpoint": "http://127.0.0.1:8093", "bucket": "kbk", "key": S3KEY, "secret": S3SECRET}})
check(r.ok and r.json()["s3"]["key_set"] and r.json()["s3"]["secret_set"], "S3: key + secret saved")
check(A.patch(OFF, json={"s3": {"bucket": "kbk2"}}).json()["s3"]["secret_set"], "S3 path style: another bucket is the same host, the keys stay")
s3 = A.patch(OFF, json={"s3": {"endpoint": "http://127.0.0.1:8099", "key": "AKOTHERKEY"}}).json()["s3"]
check(s3["key_set"] and not s3["secret_set"], f"S3: another endpoint keeps only the key that came along {s3}")
A.patch(OFF, json={"s3": {"secret": S3SECRET}})
s3 = A.patch(OFF, json={"s3": {"path_style": False}}).json()["s3"]
check(not s3["key_set"] and not s3["secret_set"], f"S3: virtual-host style (the bucket in the host name): the keys go {s3}")
# SFTP: the key pair is this server's own: it stays with another host (the host key goes, as before)
sf = A.patch(OFF, json={"type": "sftp", "sftp": {"host": "127.0.0.1", "port": 1, "user": "backup"}}).json()["sftp"]
sf2 = A.patch(OFF, json={"sftp": {"host": "127.0.0.2"}}).json()["sftp"]
check(sf["public_key"] and sf2["public_key"] == sf["public_key"], "SFTP: another host keeps the key pair")

# ============================================================== downloads behind the step-up (freelancer-matrix: office)
r = Fr.get(RX + "/me/export.zip")
check(r.status_code == 403 and r.json().get("need") == "password" and not r.content.startswith(b"PK"), f"retention ZIP: a GET without a ticket 403 {r.status_code}")
check(Fr.post(RX + "/me/export.zip", json={}).status_code == 403, "retention ZIP: the ticket needs the password")
check(Fr.post(RX + "/me/export.zip", json={"password": "wrong"}).status_code == 403, "retention ZIP: not with a wrong one")
t = Fr.post(RX + "/me/export.zip", json={"password": PW}).json().get("ticket", "")
r = Fr.get(RX + "/me/export.zip", params={"t": t})
check(t and r.ok and r.content[:2] == b"PK" and "no-store" in r.headers.get("Cache-Control", ""), f"freelancer: the own retention ZIP with the ticket {r.status_code}")
check(Fr.get(RX + "/me/export.zip", params={"t": t}).status_code == 403, "a ticket works once")
t = Fr.post(RX + "/me/export.zip", json={"password": PW}).json().get("ticket", "")
check(Bo.get(RX + "/me/export.zip", params={"t": t}).status_code == 403, "another person cannot use the ticket")
check(Fr.get(B + "/api/orgs/0/export/file", params={"t": t}).status_code in (403, 404), "a ticket counts only for its address")
# the export of the own office (organisation 0)
Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Frida Studio", "city": "Hamburg", "country": "DE"}})
check(Fr.post(B + "/api/orgs/0/export").status_code == 202, "setup: the own office's export starts")
until(lambda: Fr.get(B + "/api/orgs/0/export").json().get("state") != "running", 120)
r = Fr.get(B + "/api/orgs/0/export/file")
check(r.status_code == 403 and r.json().get("need") == "password", f"own office export: a GET without the step-up 403 {r.status_code} {r.text[:120]}")
r = su_get(Fr, B + "/api/orgs/0/export/file")
check(r.ok and r.content[:13] == b"KALMIDO-ORGX\n", f"own office export with the step-up {r.status_code} {r.content[:40]}")

# ============================================================== a restore keeps the current target
A.patch(OFF, json={"type": "webdav", "webdav": DAV1})
before = {x["name"] for x in A.get(B + "/api/admin/backups").json()["items"]}
time.sleep(1.1)
assert A.post(B + "/api/admin/backups").status_code == 202
bk = until(lambda: [x["name"] for x in A.get(B + "/api/admin/backups").json()["items"] if x["name"] not in before]
           and not A.get(B + "/api/admin/backups").json()["running"]
           and [x["name"] for x in A.get(B + "/api/admin/backups").json()["items"] if x["name"] not in before], 60)
check(bool(bk), "setup: a backup with the WebDAV target in it")
check(A.patch(OFF, json={"remove": True}).ok, "the target is removed after the backup")
r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "name": bk[0] if bk else ""})
check(r.ok, f"restore {r.status_code} {r.text[:200]}")
A = sess("alice")
j = A.get(OFF).json()
check(j.get("type") == "" and not j["webdav"]["url"] and not j["webdav"]["password_set"],
      f"the restore keeps the removed target removed (no old address, no old password) {j.get('type')} {j.get('webdav')}")
check(dbx("SELECT COUNT(*) AS n FROM users WHERE username='bob'", data=DATA)[0]["n"] == 1, "the restore itself ran (the data is there)")

# ============================================================== hosted: only public https
if not nostart("P22232C"):
    A.patch(OFF, json={"type": "webdav", "webdav": DAV1, "password": PW})  # saved while self-hosted (a NAS in the LAN is fine there)
    fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SECRET_KEY": KEY, "KALMIDO_HOSTED": "1", "KALMIDO_OFFSITE_TIMEOUT": "10"},
          prefix="P22232C", keep=True, data=DATA)
    until(lambda: requests.get(B + "/api/health", timeout=2).ok, 30)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_offsite.py", "webdav", "8094", "kbk", DAVPASS])
    time.sleep(1.0)
    A = sess("alice")
    n0 = len(dav_log())
    j = A.post(OFF + "/test", json={"password": PW}).json()
    check(j.get("ok") is False and j.get("code") == "blocked", f"hosted: a target in the local network saved before is refused when connecting {j}")
    check(len(dav_log()) == n0, "hosted: no request reached it")
    for t, x in (("s3", {"endpoint": "http://s3.example.com"}), ("s3", {"endpoint": "https://169.254.169.254"}),
                 ("s3", {"endpoint": "https://127.0.0.1:8093"}), ("s3", {"endpoint": "https://10.0.0.5:9000"}),
                 ("s3", {"endpoint": "https://localhost"}), ("s3", {"endpoint": "https://[::1]:9000"}),
                 ("webdav", {"url": "http://127.0.0.1:8094/dav/bk"}), ("webdav", {"url": "https://10.0.0.7/dav"}),
                 ("sftp", {"host": "10.1.2.3"}), ("sftp", {"host": "127.0.0.1"}), ("sftp", {"host": "localhost"})):
        r = A.patch(OFF, json={t: x})
        check(r.status_code == 400 and "public addresses" in r.text, f"hosted: {t} {x} refused 400 {r.status_code} {r.text[:120]}")
    check(A.patch(OFF, json={"s3": {"endpoint": "https://s3.example.com"}}).ok, "hosted: a public https address is fine")
    r = A.patch(OFF, json={"s3": {"region": "eu-central-1", "bucket": "kbk", "prefix": "srv1"}})
    check(r.ok, f"hosted: the other S3 fields as before (only addresses are checked) {r.status_code} {r.text[:120]}")
    check(A.patch(OFF, json={"sftp": {"host": "sftp.example.com"}}).ok, "hosted: a public SFTP host name is fine (checked when connecting)")
    code = ("from kalmido.admin.offsite import sftp_error\n"
            "print(sftp_error('ssh: connect to host h port 22: Connection refused').text('en'))\n"
            "print(sftp_error('ssh: connect to host h port 22: Connection timed out').text('en'))")
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=120)
    out = r.stdout.strip().splitlines()[-2:]
    check(len(out) == 2 and out[0] == out[1] and "refused" not in out[0] and "timed out" not in out[0],
          f"hosted: SFTP says the same for a closed and a silent port {out} {r.stderr[-200:]}")

sys.exit(done("p22232_c_offsite"))
