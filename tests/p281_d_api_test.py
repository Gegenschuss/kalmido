#!/usr/bin/env python3
"""2.81.0 API tests, part D: the Paperless-ngx import of an export ZIP. Invented names only, generated file contents.
 - #1874: the last part only stores (state check, the answer comes at once); the worker checks the ZIP in the background:
   an export -> ready, not a ZIP -> bad with the reason, nothing left on the disk
 - #1875 N2: a run that lost its claim (cut off as stale, taken by another process) ends before it files the next document
   and writes nothing more (no second run in parallel); the heartbeat only holds with the run's own beat (unit, in the container)
 - #1875 N3: every export gets its own source key (stable for the same Paperless-ngx): two servers with the same label ids
   -> the rules of both come
usage: p281_d_api_test.py <datadir>"""
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
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def sh(cmd):
    return subprocess.run(["docker", "exec", CT, "sh", "-c", cmd], capture_output=True, text=True).stdout.strip()


def py(code):
    p = subprocess.run(["docker", "exec", "-w", "/app", CT, "python", "-c", code], capture_output=True, text=True, timeout=120)
    return p.stdout.strip(), p.stderr[-600:]


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def tiny_pdf(text):
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


def rec(model, pk, **fields):
    return {"model": model, "pk": pk, "fields": fields}


def drec(pk, title, fname, **kw):
    f = {"title": title, "content": title, "created": "2025-01-01", "correspondent": None, "document_type": None, "tags": [],
         "archive_serial_number": None, "original_filename": fname, "mime_type": "application/pdf", "checksum": "x" * 32}
    f.update(kw)
    return {"model": "documents.document", "pk": pk, "fields": f, "__exported_file_name__": fname}


def build_zip(records, files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(records))
        z.writestr("metadata.json", json.dumps({"version": "2.17.1"}))
        for name, data in files.items():
            z.writestr(name, data)
    return b.getvalue()


def state(s, ws="private"):
    return s.get(B + f"/api/paperless?ws={ws}").json()


def upload(s, data, ws="private"):
    """All parts; returns (the answer of the last part, the state once the background check is done)."""
    r = s.post(B + "/api/paperless/zip", json={"ws": ws, "size": len(data), "name": "export.zip"})
    assert r.ok, r.text
    z = r.json()["zip"]
    n, chunk = z["next"], z["chunk"]
    while n * chunk < len(data):
        r = s.post(B + "/api/paperless/zip/part", data={"ws": ws, "n": str(n)}, files={"part": ("part", data[n * chunk:(n + 1) * chunk])})
        assert r.ok, r.text
        n += 1
    last = r.json().get("zip") or {}
    done = until(lambda: (lambda z: z if z.get("state") != "check" else None)(state(s, ws).get("zip") or {}), 60)
    return last, done or {}


def zip_idle(s, ws="private", secs=90):
    return until(lambda: (lambda j: j if (j.get("zip") or {}).get("state") == "done" and j["zip"]["run"]["state"] == "idle" else None)(state(s, ws)), secs)


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_PAPERLESS_ZIP_CHUNK_KB=64"))
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en"})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
f = A.get(B + "/api/state").json()["settings"].get("features") or ""
if "docs" not in f.split(","):
    A.patch(B + "/api/settings", json={"features": f + ",docs"})
UID = dbx("SELECT id FROM users WHERE username='alice'")[0][0]


def user(pk, name, joined):
    return rec("auth.user", pk, username=name, date_joined=joined, password="!", is_superuser=True)


# ---- #1874: the check in the background
X_TAG = rec("documents.tag", 1, name="Tax", match="tax office", matching_algorithm=1, is_insensitive=True)
X_USER = user(1, "admin", "2023-01-05T10:00:00.123456Z")
XDOCS = [drec(11 + i, f"Letter {i}", f"x{i}.pdf", tags=[1]) for i in range(3)]
ZX = build_zip([X_USER, X_TAG] + XDOCS, {f"x{i}.pdf": tiny_pdf(f"Letter {i}") + bytes(range(256)) * 400 for i in range(3)})
check(len(ZX) > 64 * 1024, f"setup: the ZIP spans several parts ({len(ZX)})")
last, z = upload(A, ZX)
check(last.get("state") == "check" and last.get("got") == len(ZX), f"#1874: the last part answers at once, the ZIP is being checked ({last.get('state')})")
check(z.get("state") == "ready", f"#1874: the worker checked it: ready ({z.get('state')} {z.get('error_text')})")
RID = z.get("id")
SRC_X = (dbx("SELECT src FROM pl_uploads WHERE id=?", (RID,)) or [[""]])[0][0]
LEGACY = hashlib.sha256(b"paperless-export").hexdigest()[:12]
check(SRC_X and SRC_X != LEGACY, f"#1875: the export has a key of its own ({SRC_X!r})")

# ---- #1875 N2: a run that lost its claim (unit, inside the container; the worker does not touch a fresh busy row)
dbx("UPDATE pl_uploads SET run_state='busy', run_by=?, run_beat=? WHERE id=?", (UID, now_iso(), RID), write=True)
CODE = f"""
import json
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.paperless import ngx as P, zipimp as Z
RID, THIEF = {RID}, "2099-01-01T00:00:00+00:00"
c = connect()
out = {{}}
with system_ctx(c):
    own = [c.execute("SELECT run_beat FROM pl_uploads WHERE id=?", (RID,)).fetchone()[0]]
    P.pl_beat(c, "pl_uploads", RID, own, run_total=0)
    c.commit()
    out["own"] = "held"
    try:
        P.pl_beat(c, "pl_uploads", RID, ["1999-01-01T00:00:00+00:00"])
        out["other"] = "held"
    except P.PlLost:
        out["other"] = "lost"
    c.rollback()
    read = Z._read
    def steal(*a, **k):  # another process claims the run between two documents (this one was cut off as stale)
        if not a[1].filename.endswith(".pdf"):  # the manifest
            return read(*a, **k)
        x = connect()
        with system_ctx(x):
            x.execute("UPDATE pl_uploads SET run_state='busy', run_beat=? WHERE id=?", (THIEF, RID))
            x.commit()
        x.close()
        Z._read = read
        return read(*a, **k)
    Z._read = steal
    Z.plh_zip_run(c, RID)
    r = c.execute("SELECT state, run_state, run_beat, run_done, run_new FROM pl_uploads WHERE id=?", (RID,)).fetchone()
    out["row"] = [r[0], r[1], r[2], int(r[3]), int(r[4])]
    out["imported"] = c.execute("SELECT COUNT(*) FROM pl_imported").fetchone()[0]
c.close()
print(json.dumps(out))
"""
out, e = py(CODE)
try:
    res = json.loads(out.splitlines()[-1])
except (ValueError, IndexError):
    res = {}
    print("unit:", out[-400:], e, flush=True)
check(res.get("own") == "held" and res.get("other") == "lost", f"#1875: the heartbeat holds only with the run's own beat ({res})")
check(res.get("row") == ["ready", "busy", "2099-01-01T00:00:00+00:00", 0, 0],
      f"#1875: the run that lost its claim stops before filing and leaves the row to the other run ({res.get('row')})")
check(res.get("imported") == 0, f"#1875: nothing filed by the run that lost ({res.get('imported')})")
check(sh(f"test -e /data/paperless-zip/{RID}/part-000000 && echo yes") == "yes", "#1875: its parts stay for the run that has it now")
dbx("UPDATE pl_uploads SET run_state='', run_beat=? WHERE id=?", (now_iso(), RID), write=True)

# ---- #1875 N3: a second Paperless-ngx with the same label ids -> its rules come too
r = A.post(B + "/api/paperless/zip/import", json={"ws": "private"})
check(r.ok, f"import of export X ({r.status_code} {r.text[:160]})")
run = ((zip_idle(A) or {}).get("zip") or {}).get("run") or {}
check(run.get("new") == 3 and (run.get("learn") or {}).get("rules_new") == 1, f"export X: 3 new, its rule taken over ({run})")
Y_TAG = rec("documents.tag", 1, name="Insurance", match="policy number", matching_algorithm=1, is_insensitive=True)
Y_USER = user(1, "admin", "2024-07-11T08:30:00.654321Z")
ZY = build_zip([Y_USER, Y_TAG, drec(11, "Policy", "y.pdf", tags=[1])], {"y.pdf": tiny_pdf("Policy letter")})
_last, z = upload(A, ZY)
SRC_Y = (dbx("SELECT src FROM pl_uploads WHERE id=?", (z.get("id"),)) or [[""]])[0][0]
check(z.get("state") == "ready" and SRC_Y and SRC_Y not in (SRC_X, LEGACY), f"#1875: another server, another key ({SRC_X} {SRC_Y})")
p = A.get(B + "/api/paperless/zip/preview?ws=private").json()
check(p.get("already") == 0 and (p.get("rules") or {}).get("convert") == 1 and (p.get("rules") or {}).get("dup") == 0,
      f"#1875: the preview of server Y: its document and rule are new, though the ids match X ({p.get('already')} {p.get('rules')})")
A.post(B + "/api/paperless/zip/import", json={"ws": "private"})
run = ((zip_idle(A) or {}).get("zip") or {}).get("run") or {}
check(run.get("new") == 1 and (run.get("learn") or {}).get("rules_new") == 1, f"export Y: its document and its rule came in ({run})")
rules = [x.get("match") for x in A.get(B + "/api/docs/settings?ws=private").json().get("rules") or []]
check("tax office" in rules and "policy number" in rules, f"#1875: the rules of both servers ({rules})")
# the same server exported again later (one more document): the same key, nothing twice
ZX2 = build_zip([X_USER, X_TAG, rec("documents.tag", 2, name="New", match="", matching_algorithm=0, is_insensitive=True)] + XDOCS
                + [drec(20, "Letter later", "x9.pdf", tags=[1, 2])],
                {**{f"x{i}.pdf": tiny_pdf(f"Letter {i}") + bytes(range(256)) * 400 for i in range(3)}, "x9.pdf": tiny_pdf("Letter later")})
_last, z = upload(A, ZX2)
SRC_X2 = (dbx("SELECT src FROM pl_uploads WHERE id=?", (z.get("id"),)) or [[""]])[0][0]
check(SRC_X2 == SRC_X, f"#1875: a later export of the same server keeps its key ({SRC_X} {SRC_X2})")
p = A.get(B + "/api/paperless/zip/preview?ws=private").json()
check(p.get("count") == 4 and p.get("already") == 3, f"#1875: the documents of the first export are known ({p.get('count')} {p.get('already')})")

# ---- #1874: a ZIP that is none -> bad, nothing stays
_last, z = upload(A, os.urandom(5000))
check(z.get("state") == "bad" and "not a ZIP" in (z.get("error_text") or ""), f"#1874: not a ZIP: refused by the worker with the reason ({z.get('state')} {z.get('error_text')})")
check(sh(f"test -e /data/paperless-zip/{z.get('id')} && echo yes") == "", "#1874: the refused ZIP is gone from the disk")

print(f"p281_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
