#!/usr/bin/env python3
"""2.207.0 B (#2763): the folder watcher program (folderwatch/, built into /app/folderwatch by the Dockerfile) against a
real server - run INSIDE the test container in its one-round mode (--once --config <file>, no page, no autostart).
freelancer-matrix: docs
 - the image carries every download (Mac zips, Windows, Linux) and SHA256SUMS matches them; the Linux file reports the
   version of the image
 - a person without an organisation creates an upload-only key (POST /api/docs/scan-keys, private space); the watcher
   uploads a finished PDF from its folder, the document is there, the file lies in "Uploaded" afterwards; hidden files
   stay where they are; the duplicate guard journal is private (0600)
 - after the key is revoked the watcher stops that inbox (paused, exit code 2) and leaves the new file in place
usage: p2207_b_watcher_test.py <datadir>"""
import base64
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, check  # noqa: E402

FW = "/app/folderwatch"
FILES = ["kalmido-folder-watcher-mac-arm64.zip", "kalmido-folder-watcher-mac-amd64.zip", "kalmido-folder-watcher-windows.exe",
         "kalmido-folder-watcher-linux-amd64", "kalmido-folder-watcher-linux-arm64", "SHA256SUMS"]
ROOT = "/tmp/fw2207"


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
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def cx(code, data=b"", timeout=60):
    """Run a Python snippet inside the test container (stdin = data) -> CompletedProcess."""
    return subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], input=data, capture_output=True, timeout=timeout)


def put(path, data):
    r = cx("import os,sys; p=%r; os.makedirs(os.path.dirname(p), exist_ok=True); open(p,'wb').write(sys.stdin.buffer.read())" % path, data)
    assert r.returncode == 0, r.stderr


def ls(path):
    r = cx("import os,json; p=%r; print(json.dumps(sorted(os.listdir(p)) if os.path.isdir(p) else None))" % path)
    return json.loads(r.stdout or b"null")


def watcher(binary, cfg):
    r = subprocess.run(["docker", "exec", CT, binary, "--once", "--config", cfg], capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


A = kt.setup()  # run_all.sh started a fresh container

# the downloads in the image
have = ls(FW) or []
check(all(f in have for f in FILES), f"all downloads in {FW}: {have}")
r = cx("import hashlib,os\nbad=[]\nfor ln in open('%s/SHA256SUMS'):\n    h,n=ln.split()\n    if hashlib.sha256(open(os.path.join('%s',n),'rb').read()).hexdigest()!=h: bad.append(n)\nprint(len(open('%s/SHA256SUMS').readlines()), bad)" % (FW, FW, FW))
check(r.returncode == 0 and r.stdout.decode().strip() == f"{len(FILES) - 1} []", f"SHA256SUMS matches the files: {r.stdout!r} {r.stderr!r}")
r = cx("import zipfile; z=zipfile.ZipFile('%s/kalmido-folder-watcher-mac-arm64.zip'); i=z.infolist()[0]; print(i.filename, oct(i.external_attr>>16 & 0o777))" % FW)
check(r.stdout.decode().split() == ["kalmido-folder-watcher", "0o755"], f"the Mac zip keeps the executable bit: {r.stdout!r}")
arch = subprocess.run(["docker", "exec", CT, "uname", "-m"], capture_output=True, text=True).stdout.strip()
BIN = f"{FW}/kalmido-folder-watcher-linux-" + ("arm64" if arch in ("aarch64", "arm64") else "amd64")
ver = subprocess.run(["docker", "exec", CT, "cat", "/app/VERSION"], capture_output=True, text=True).stdout.strip()
r = subprocess.run(["docker", "exec", CT, BIN, "--version"], capture_output=True, text=True)
check(r.returncode == 0 and r.stdout.strip() == f"kalmido-folder-watcher {ver}", f"--version: {r.stdout!r} {r.stderr!r}")

# a person without an organisation sets up an inbox in the private space
FID, Fr = freelancer(B, A)  # freelancer-matrix: docs (upload-only key, the watcher uploads into the private space)
r = Fr.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": "Scanner"})
check(r.status_code == 201, f"scan key created: {r.status_code} {r.text[:200]}")
j = r.json() if r.status_code == 201 else {}
code = j.get("code", "")
check(code.startswith("kalmido-scan:1:"), f"setup code: {code[:20]!r}")
payload = json.loads(base64.urlsafe_b64decode(code[len("kalmido-scan:1:"):] + "=" * (-len(code) % 4))) if code else {}
check(payload.get("key", "").startswith("abk_") and payload.get("url", "").startswith("http"), "the code holds url + key")
# inside the container the server listens on 127.0.0.1:3040 (the code's url is the public address)
inbox = {"id": "t1", "name": payload.get("name") or "Scanner", "url": "http://127.0.0.1:3040", "key": payload.get("key", ""),
         "target": "", "max_mb": 0, "folder": ROOT + "/in", "uploaded_dir": "Uploaded", "rejected_dir": "Not uploaded"}
CFG = ROOT + "/cfg/config.json"
put(CFG, json.dumps({"inboxes": [inbox], "autostart": False}).encode())
put(ROOT + "/in/scan-2207.pdf", tiny_pdf("Ordner Waechter 2207"))
put(ROOT + "/in/.DS_Store", b"x")
put(ROOT + "/in/half.pdf.part", b"%PDF")

rc, out, err = watcher(BIN, CFG)
check(rc == 0 and "uploaded=1" in out and "state=ready" in out, f"one round uploads the file: rc={rc} {out!r} {err[-400:]!r}")
check(ls(ROOT + "/in/Uploaded") == ["scan-2207.pdf"], f"moved into Uploaded: {ls(ROOT + '/in/Uploaded')}")
left = ls(ROOT + "/in") or []
check("scan-2207.pdf" not in left and ".DS_Store" in left and "half.pdf.part" in left, f"hidden / partial files untouched: {left}")
m = re.search(r"uploaded scan-2207\.pdf \(document (\d+)\)", err)
check(bool(m), f"the log names the document: {err[-300:]!r}")
if m:
    d = Fr.get(B + f"/api/docs/{m.group(1)}")
    check(d.ok and d.json().get("name") == "scan-2207.pdf" and not d.json().get("org_id"), f"the document is in the private space: {d.status_code} {d.text[:200]}")
r = cx("import os; print(oct(os.stat(%r).st_mode & 0o777))" % (ROOT + "/cfg/journal.json"))
check(r.stdout.decode().strip() in ("0o600", ""), f"journal private: {r.stdout!r}")

# revoked key: the inbox stops, the file stays
if j.get("id"):
    r = Fr.delete(B + f"/api/docs/scan-keys/{j['id']}")
    check(r.ok, f"key revoked: {r.status_code} {r.text[:200]}")
put(ROOT + "/in/scan-2.pdf", tiny_pdf("zweiter Scan"))
rc, out, err = watcher(BIN, CFG)
check(rc == 2 and "state=paused" in out, f"revoked key pauses the inbox: rc={rc} {out!r}")
check("scan-2.pdf" in (ls(ROOT + "/in") or []) and "scan-2.pdf" not in (ls(ROOT + "/in/Uploaded") or []), "the file stays in place")

sys.exit(kt.done("p2207_b_watcher"))
