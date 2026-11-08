#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.663.0 B (#4191): sealed files are no longer held whole in memory without a limit.
Own container with a server key. A helper process inside the container calls core/orgcrypt.py directly (the budget is per
process, so its counters are checked there); the routes are checked over HTTP. Invented names only.
freelancer-matrix: files
 - step 1, RAM budget: a sealed file from 10 MB on counts twice its size while it is opened whole; over the budget a request
   waits briefly and then answers 503 + Retry-After (was: no limit, every parallel download held its plain text); the room
   is handed back when the answer is closed; a small file is not counted; a background job (no request) goes on after its
   wait; a single file larger than the whole budget still opens when nothing else is held
 - step 2, chunk format (MAGIC2 "KENC2"): a large new upload is sealed in chunks of 1 MiB (an organisation's list and a
   person without an organisation, key named in the header); both formats are read (a single-piece file of the same size
   still downloads, whole and as a range); a range across a chunk border answers 206 with the right bytes and decrypts only
   the chunks it touches (was: the whole file for every range); a public link answers ranges the same way; a chunk changed,
   moved, dropped or appended, a file cut off at a chunk border or a changed header does not open; plain size, rotation
   (rck_rekey_file keeps the format) and the way back (orgcrypt_cli files-to-v1, KALMIDO_SEAL_CHUNKS off) work
usage: p2663_b_seal_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from kt import docker_logs_on_first_fail  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

docker_logs_on_first_fail()
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()


def in_ct(code):
    """Python inside the app container; the last stdout line is JSON."""
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "600", "KALMIDO_SECRET_KEY": KEY,
          "TASKS_MAX_FILE_MB": "8"})  # uploads above one chunk size (the default test container allows 1 MB)
A = kt.setup()
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": "collab,files,comments", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
FID, Fr = freelancer(B, A)

BASE = f"""import io, json, os, threading, time
from kalmido.core.db import connect
from kalmido.core.config import app
from kalmido.core import orgcrypt as oc
c = connect()
ORG = {ORG}
KEY = oc.oc_key(c, ORG)
c.commit()
MB = 1024 * 1024
def sealed_v1(name, n):  # a sealed file of the older format (one piece), plain bytes of a known pattern
    p = "/tmp/p2663b-" + name
    data = bytes(i % 251 for i in range(n))
    with open(p, "wb") as f:
        f.write(oc._seal_v1(KEY, ORG, data))  # 2.663.0 B (#4191): oc_seal_raw writes large files in chunks
    return p, data
"""

# ---------------------------------------------------------------- step 1: the RAM budget (one process, its own counters)
r = in_ct(BASE + """out = {}
oc.SEAL_RAM_BUDGET, oc.SEAL_RAM_WAIT, oc.SEAL_RAM_BG_WAIT = 30 * MB, 0.3, 0.3
big, data = sealed_v1("big", 12 * MB)
small, sdata = sealed_v1("small", 2 * MB)
held = oc.oc_ram_take(os.path.getsize(big))  # another download holds 2 x 12 MB
out["held"] = oc.oc_ram_held() // MB
with app.test_request_context("/x"):
    try:
        oc.oc_send_file(c, big, mimetype="application/octet-stream")
        out["busy"] = None
    except oc.SealBusy as e:
        rv = app.make_response(app.handle_user_exception(e))
        out["busy"] = [rv.status_code, rv.headers.get("Retry-After"), oc.oc_ram_held() // MB]
    rv = oc.oc_send_file(c, small, mimetype="application/octet-stream")  # under 10 MB: never counted
    out["small"] = [rv.status_code, b"".join(rv.response) == sdata, oc.oc_ram_held() // MB]
    rv.close()
t0 = time.monotonic()
bg = oc.oc_read_file(c, big)  # a background job: waits, then goes on
out["bg"] = [bg == data, oc.oc_ram_held() // MB]
oc.oc_ram_give(held)
with app.test_request_context("/x"):
    rv = oc.oc_send_file(c, big, mimetype="application/octet-stream")
    out["sent"] = [rv.status_code, oc.oc_ram_held() // MB]
    out["body"] = b"".join(rv.response) == data
    rv.close()
    rv.close()  # closing twice hands back once
    out["after"] = oc.oc_ram_held()
oc.SEAL_RAM_BUDGET = 5 * MB  # smaller than the one file: still opens when nothing else is held
with app.test_request_context("/x"):
    rv = oc.oc_send_file(c, big, mimetype="application/octet-stream")
    out["alone"] = [rv.status_code, oc.oc_ram_held() > 0]
    rv.close()
out["end"] = oc.oc_ram_held()
# 2.663.0 (#4191, Fable review): the WSGI server closes only the body iterator of a send_file answer (direct_passthrough),
# never the Response itself - the room must come back on that path too (was: held until the process restarted)
oc.SEAL_RAM_BUDGET = 30 * MB
from flask import request, g
with app.test_request_context("/x"):
    rv = oc.oc_send_file(c, big, mimetype="application/octet-stream")
    it = rv.get_app_iter(request.environ)
    body = b"".join(it)
    mid = oc.oc_ram_held()
    it.close()
    out["wsgi"] = [body == data, mid >= 24, oc.oc_ram_held()]
# a public link (nobody signed in) does not wait for room; a signed-in person waits until it is free
oc.SEAL_RAM_WAIT = 5
held = oc.oc_ram_take(os.path.getsize(big))
with app.test_request_context("/x"):
    t0 = time.monotonic()
    try:
        oc.oc_send_file(c, big, mimetype="application/octet-stream")
        out["pub"] = None
    except oc.SealBusy:
        out["pub"] = time.monotonic() - t0 < 2
with app.test_request_context("/x"):
    g.user = {"id": 1}
    threading.Timer(0.3, oc.oc_ram_give, [held]).start()
    rv = oc.oc_send_file(c, big, mimetype="application/octet-stream")
    out["signed"] = rv.status_code
    rv.close()
# more than SEAL_RAM_QUEUE waiting at once: the next one is refused at once
held = oc.oc_ram_take(os.path.getsize(big))
oc._RAM_WAITING[0] = oc.SEAL_RAM_QUEUE
with app.test_request_context("/x"):
    g.user = {"id": 1}
    t0 = time.monotonic()
    try:
        oc.oc_send_file(c, big, mimetype="application/octet-stream")
        out["queue"] = None
    except oc.SealBusy:
        out["queue"] = time.monotonic() - t0 < 2
oc._RAM_WAITING[0] = 0
oc.oc_ram_give(held)
out["end2"] = oc.oc_ram_held()
print(json.dumps(out))""")
check(r["held"] >= 24, f"step 1: the other download is counted twice its size {r}")
check(r["busy"] and r["busy"][0] == 503 and r["busy"][1] == "10" and r["busy"][2] == r["held"],
      f"step 1: over the budget a request answers 503 + Retry-After and holds nothing (was: no limit) {r}")
check(r["small"] == [200, True, r["held"]], f"step 1: a file under 10 MB is not counted {r}")
check(r["bg"] == [True, r["held"]], f"step 1: a background job goes on after its wait and hands the room back {r}")
check(r["sent"][0] == 200 and r["sent"][1] >= 24 and r["body"], f"step 1: with room the download is counted while it is sent {r}")
check(r["after"] == 0, f"step 1: closing the answer hands the room back (once) {r}")
check(r["alone"] == [200, True] and r["end"] == 0, f"step 1: a file larger than the budget opens when nothing else is held {r}")
check(r["wsgi"] == [True, True, 0], f"step 1: closing the body iterator as the WSGI server does hands the room back (was: never) {r}")
check(r["pub"] is True, f"step 1: without a signed-in person (public link) a busy budget answers 503 at once {r}")
check(r["signed"] == 200, f"step 1: a signed-in person waits for room and then gets the file {r}")
check(r["queue"] is True and r["end2"] == 0, f"step 1: with SEAL_RAM_QUEUE requests already waiting the next is refused at once {r}")

# ---------------------------------------------------------------- step 2: the chunk format inside one process
r = in_ct(BASE + """out = {}
from kalmido.admin import orgcrypt_cli as cli
from kalmido.core.config import ATT_DIR
pat = lambda n: bytes((i * 7 + i // 997) % 256 for i in range(n))
def opens(blob):
    try:
        return oc.oc_open_k(KEY, blob)
    except oc.OrgCryptError:
        return "error"
for name, n in (("odd", 5 * MB + 123), ("exact", 4 * MB), ("empty", 0)):
    data = pat(n)
    blob = oc.oc_seal_chunks(KEY, ORG, data)
    p = "/tmp/p2663b-v2-" + name
    with open(p, "wb") as f:
        f.write(blob)
    out[name] = [blob[:6] == oc.MAGIC2, opens(blob) == data, oc.oc_plain_size(p) == n, oc.oc_file_org(blob) == ORG,
                 oc.oc_is_sealed_file(p), oc.oc_read_file(c, p) == data]
data = pat(5 * MB + 123)
out["raw_big"] = oc.oc_seal_raw(KEY, ORG, data)[:6] == oc.MAGIC2
out["raw_small"] = oc.oc_seal_raw(KEY, ORG, data[:MB])[:6] == oc.MAGIC
out["raw_ctx"] = oc.oc_seal_raw(KEY, ORG, data, b"other")[:6] == oc.MAGIC  # only stored files (FILE_CTX) are chunked
v1 = oc._seal_v1(KEY, ORG, data)
out["v1"] = opens(v1) == data
blob = oc.oc_seal_chunks(KEY, ORG, data)
H, S = oc._HEAD2, oc.CHUNK + 16
def ch(i):
    return blob[H + i * S:H + (i + 1) * S]
bad = {
    "flip": blob[:H + S + 5] + bytes([blob[H + S + 5] ^ 1]) + blob[H + S + 6:],
    "swap": blob[:H] + ch(1) + ch(0) + blob[H + 2 * S:],
    "drop_last": blob[:H + 5 * S],
    "drop_mid": blob[:H + S] + blob[H + 2 * S:],
    "append": blob + ch(5),
    "cut": blob[:-7],
    "head_org": blob[:6] + (ORG + 1).to_bytes(8, "big", signed=True) + blob[14:],
    "head_size": blob[:14] + (oc.CHUNK // 2).to_bytes(4, "big") + blob[18:],
    "head_salt": blob[:H - 1] + bytes([blob[H - 1] ^ 1]) + blob[H:],
    "other_key": oc.oc_seal_chunks(os.urandom(32), ORG, data),
    "other_ctx": oc.oc_seal_chunks(KEY, ORG, data, b"other"),
}
out["bad"] = {k: opens(v) == "error" for k, v in bad.items()}
# ranges: only the chunks a range touches are decrypted
p = "/tmp/p2663b-v2-odd"
seen = []
keep = oc._ChunkFile.chunk
def counted(self, i):
    seen.append(i)
    return keep(self, i)
oc._ChunkFile.chunk = counted
odd = pat(5 * MB + 123)
with app.test_request_context("/x", headers={"Range": "bytes=%d-%d" % (MB - 100, MB + 99)}):
    rv = oc.oc_send_file(c, p, mimetype="application/octet-stream", as_attachment=True, download_name="v.bin")
    body = b"".join(rv.response)
    out["range"] = [rv.status_code, rv.headers.get("Content-Range"), body == odd[MB - 100:MB + 100], sorted(set(seen)),
                    oc.oc_ram_held()]
    rv.close()
seen.clear()
with app.test_request_context("/x", headers={"Range": "bytes=-50"}):
    rv = oc.oc_send_file(c, p, mimetype="application/octet-stream")
    out["suffix"] = [rv.status_code, b"".join(rv.response) == odd[-50:], sorted(set(seen))]
    rv.close()
with app.test_request_context("/x", headers={"Range": "bytes=%d-" % (6 * MB)}):
    try:  # werkzeug raises RequestedRangeNotSatisfiable (Flask answers it as 416)
        out["beyond"] = oc.oc_send_file(c, p, mimetype="application/octet-stream").status_code
    except Exception as e:
        out["beyond"] = getattr(e, "code", repr(e))
with app.test_request_context("/x"):
    rv = oc.oc_send_file(c, p, mimetype="application/octet-stream")
    out["whole"] = [rv.status_code, rv.headers.get("Accept-Ranges"), rv.content_length == len(odd), b"".join(rv.response) == odd]
    rv.close()
oc._ChunkFile.chunk = keep
with open("/tmp/p2663b-v2-cut", "wb") as f:
    f.write(bad["drop_last"])
with app.test_request_context("/x"):
    try:
        oc.oc_send_file(c, "/tmp/p2663b-v2-cut", mimetype="application/octet-stream")
        out["send_cut"] = "sent"
    except oc.OrgCryptError:
        out["send_cut"] = "error"
# rotation keeps the format, the way back writes the single-piece one
k2 = os.urandom(32)
new = oc.rck_rekey_file(KEY, k2, blob)
out["rot"] = [new[:6] == oc.MAGIC2, oc.oc_open_k(k2, new) == data, oc.rck_rekey_file(KEY, k2, new) is None]
d = os.path.join(ATT_DIR, "p2663b")
os.makedirs(d, exist_ok=True)
f2 = os.path.join(d, "big.bin")
with open(f2, "wb") as f:
    f.write(blob)
n, nbad = cli.files_to_v1(c)
with open(f2, "rb") as f:
    back = f.read()
out["v1_back"] = [n >= 1, nbad, back[:6] == oc.MAGIC, oc.oc_open_k(KEY, back) == data]
os.remove(f2)
oc.SEAL_CHUNKS = False
out["switch_off"] = oc.oc_seal_raw(KEY, ORG, data)[:6] == oc.MAGIC
print(json.dumps(out))""")
for name in ("odd", "exact", "empty"):
    check(r[name] == [True] * 6, f"step 2: chunk format {name}: magic, opens, plain size, header id, read whole {r[name]}")
check(r["raw_big"] and r["raw_small"] and r["raw_ctx"], f"step 2: a large stored file is chunked, a small one / another ctx not {r}")
check(r["v1"], "step 2: the single-piece format still opens")
for k, v in r["bad"].items():
    check(v, f"step 2: a damaged chunked file does not open: {k}")
check(r["range"][0] == 206 and r["range"][1] == f"bytes {1024 * 1024 - 100}-{1024 * 1024 + 99}/{5 * 1024 * 1024 + 123}" and r["range"][2],
      f"step 2: a range across a chunk border answers 206 with the right bytes {r['range']}")
check(r["range"][3] == [0, 1, 5] and r["range"][4] == 0,
      f"step 2: only the touched chunks (+ the last, checked first) are decrypted, nothing counted against the budget {r['range']}")
check(r["suffix"] == [206, True, [5]], f"step 2: a suffix range reads only the last chunk {r['suffix']}")
check(r["beyond"] == 416, f"step 2: a range beyond the end: 416 {r}")
check(r["whole"] == [200, "bytes", True, True], f"step 2: the whole file streams with its plain length {r['whole']}")
check(r["send_cut"] == "error", f"step 2: a file cut off at a chunk border is refused before the answer starts {r}")
check(r["rot"] == [True, True, True], f"step 2: rotation reseals a chunked file chunked with the new key {r['rot']}")
check(r["v1_back"] == [True, 0, True, True], f"step 2: orgcrypt_cli files-to-v1 writes the single-piece format {r['v1_back']}")
check(r["switch_off"], "step 2: KALMIDO_SEAL_CHUNKS off: large files in the single-piece format again")

# ---------------------------------------------------------------- step 2 over HTTP: uploads, downloads, ranges, public link
BIG = bytes((i * 13 + i // 1009) % 256 for i in range(5 * 1024 * 1024 + 4321))
MB1 = 1024 * 1024
RNG = {"Range": f"bytes={MB1 - 10}-{2 * MB1 + 9}"}
WANT = BIG[MB1 - 10:2 * MB1 + 10]


def upload(s, lid, name):
    t = s.post(B + "/api/tasks", json={"list_id": lid, "title": "Rohschnitt " + name}).json()["id"]
    r = s.post(B + f"/api/tasks/{t}/attachments", files={"file": (name, BIG, "application/octet-stream")})
    check(r.ok, f"setup: upload {name} ({r.status_code} {r.text[:150]})")
    att = [a for a in r.json().get("attachments") or [] if a["name"] == name]
    return t, att[0]["id"] if att else 0


def head_of(aid):
    return in_ct(f"""import json, os
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.core.config import ATT_DIR
from kalmido.core import orgcrypt as oc
c = connect()
with system_ctx(c):
    rel = c.execute("SELECT path FROM attachments WHERE id=?", ({aid},)).fetchone()[0]
p = os.path.join(ATT_DIR, rel)
with open(p, "rb") as f:
    h = f.read(64)
print(json.dumps([h[:6].decode("latin-1"), oc.oc_file_org(h), oc.oc_plain_size(p), p]))""")


L = A.post(B + "/api/lists", json={"name": "Projekt Nordlicht", "org_id": ORG}).json()["id"]
T, AID = upload(A, L, "schnitt.bin")
h = head_of(AID)
check(h[:3] == ["KENC2\n", ORG, len(BIG)], f"step 2: the upload of an organisation's list is sealed in chunks with its key {h}")
r = A.get(B + f"/api/attachments/{AID}?dl=1")
check(r.status_code == 200 and r.content == BIG, f"step 2: the whole download ({r.status_code}, {len(r.content)} bytes)")
r = A.get(B + f"/api/attachments/{AID}?dl=1", headers=RNG)
check(r.status_code == 206 and r.content == WANT and r.headers.get("Content-Range") == f"bytes {MB1 - 10}-{2 * MB1 + 9}/{len(BIG)}",
      f"step 2: a range across a chunk border ({r.status_code} {r.headers.get('Content-Range')})")

# the public link (no sign-in): the same file, whole and as a range
r = A.put(B + f"/api/lists/{L}/public-link", json={"mode": "view"})
TOK = r.json()["link"]["url"].split("/s/")[1] if r.ok else ""
r = A.put(B + f"/api/lists/{L}/public-link", json={"show": {"files": True}})
check(r.ok, f"setup: public link with files ({r.status_code} {r.text[:120]})")
anon = sess()
r = anon.get(B + f"/s/{TOK}/file/{AID}")
check(r.status_code == 200 and r.content == BIG and "attachment" in r.headers.get("Content-Disposition", "")
      and "sandbox" in r.headers.get("Content-Security-Policy", ""), f"step 2: public link: the whole file ({r.status_code})")
r = anon.get(B + f"/s/{TOK}/file/{AID}", headers=RNG)
check(r.status_code == 206 and r.content == WANT, f"step 2: public link: a range across a chunk border ({r.status_code})")

# the older single-piece format of the same file still downloads (the file on disk replaced)
in_ct(f"""import json
from kalmido.core.db import connect
from kalmido.core import orgcrypt as oc
c = connect()
p = {json.dumps(h[3])}
with open(p, "rb") as f:
    data = oc.oc_open(c, f.read())
oc.oc_reseal_file(p, oc._seal_v1(oc.oc_key(c, {ORG}, create=False), {ORG}, data))
print(json.dumps(1))""")
check(head_of(AID)[:3] == ["KENC1\n", ORG, len(BIG)], "setup: the file in the single-piece format")
r = A.get(B + f"/api/attachments/{AID}?dl=1")
check(r.status_code == 200 and r.content == BIG, f"step 2: single-piece format: the whole download ({r.status_code})")
r = anon.get(B + f"/s/{TOK}/file/{AID}", headers=RNG)
check(r.status_code == 206 and r.content == WANT, f"step 2: single-piece format: a range on the public link ({r.status_code})")

# a person without an organisation: a private list, the account key
PL = Fr.post(B + "/api/lists", json={"name": "Frida privat"}).json()["id"]
FT, FA = upload(Fr, PL, "frida.bin")
h = head_of(FA)
check(h[:3] == ["KENC2\n", -FID, len(BIG)], f"step 2: a freelancer's upload is chunked with the account key {h}")
r = Fr.get(B + f"/api/attachments/{FA}?dl=1", headers=RNG)
check(r.status_code == 206 and r.content == WANT, f"step 2: freelancer: a range across a chunk border ({r.status_code})")

sys.exit(kt.done("p2663_b_seal"))
