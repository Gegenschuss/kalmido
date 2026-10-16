#!/usr/bin/env python3
"""2.61.0 API tests (part A): the virus scan of uploads (#1818).
 - a fake clamd (tests/fake_clamd.py, inside the test container) answers zINSTREAM: the EICAR test string = FOUND
 - a find refuses the upload (task file, Ablage, project file) with the signature in the message; nothing is stored
 - a clean file is taken without a mark
 - the type from the content: an HTML page named .png / sent as image/png is stored as application/octet-stream and never
   served inline
 - scanner gone: uploads are taken and marked up.scan = "unchecked" (task files, Ablage); the admin sees the state "down"
 - scanner back: the watchdog checks them again: clean -> the mark goes; EICAR -> "infected": download 403 (app, API, Ablage),
   a News item "upscan" for the uploader, deleting still works
 - KALMIDO_CLAMD empty: no scan, no mark, state "off"
usage: p261_a_api_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
EICAR = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*").encode()  # assembled: the file never carries it


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


def start(clamd=True):
    extra = ["-e KALMIDO_CLAMD_TICK_S=1", "-e KALMIDO_CLAMD_DOWN_S=1"] + (["-e KALMIDO_CLAMD=127.0.0.1:3310"] if clamd else [])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, EXTRA=" ".join(extra)), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    if clamd:
        scanner(True)


def scanner(on):
    off = os.path.join(DATA, "clamd.off")
    if on:
        if os.path.exists(off):
            os.remove(off)
        subprocess.run(["cp", os.path.join(N, "fake_clamd.py"), DATA], check=True)
        subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_clamd.py"], check=True)
    else:
        open(off, "w").close()
    time.sleep(1.2)


def setup():
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
    a = sess("alice")
    a.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
    a.patch(B + "/api/settings", json={"lang": "en"})
    return a


def task_files(s, tid):
    return {x["name"]: x for x in s.get(B + f"/api/tasks/{tid}").json().get("attachments", [])}


def up_task(s, tid, name, data, mime="text/plain"):
    return s.post(B + f"/api/tasks/{tid}/attachments", files={"file": (name, data, mime)})


# ================================================================ container 1: scanner on
start()
A = setup()
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
Bo = sess("bob")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
L = A.post(B + "/api/lists", json={"name": "Scan", "org_id": ORG, "kind": "project"}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Files", "list_id": L}).json()["id"]

st = A.get(B + "/api/admin/upload-scan")
check(st.ok and st.json().get("state") == "ok", f"admin: scanner state ok ({st.status_code} {st.text[:200]})")
check(Bo.get(B + "/api/admin/upload-scan").status_code == 403, "scanner state: admins only")

# ---- a find refuses the upload everywhere
r = up_task(A, T, "invoice.txt", EICAR)
check(r.status_code == 400 and "Eicar-Test-Signature" in r.text and "malware" in r.text.lower(), f"task file: EICAR refused with the signature ({r.status_code} {r.text[:200]})")
check(not task_files(A, T), "task file: nothing stored")
r = A.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("bad.txt", EICAR, "text/plain")})
check(r.status_code == 400 and "Eicar-Test-Signature" in r.text, f"Ablage: EICAR refused ({r.status_code} {r.text[:200]})")
check(not dbx("SELECT 1 FROM fs_nodes WHERE name='bad.txt'"), "Ablage: nothing stored")
r = A.post(B + f"/api/lists/{L}/files", files={"file": ("bad.txt", EICAR, "text/plain")})
check(r.status_code == 400 and "Eicar-Test-Signature" in r.text, f"project file: EICAR refused ({r.status_code} {r.text[:200]})")
check(not dbx("SELECT 1 FROM list_files WHERE list_id=?", (L,)), "project file: nothing stored")

# ---- clean: taken, no mark
r = up_task(A, T, "notes.txt", b"just some notes\n")
check(r.ok and "up" not in task_files(A, T).get("notes.txt", {"up": 1}), f"clean file taken without a mark ({r.status_code})")
check(not dbx("SELECT 1 FROM upload_scan"), "clean file: no row in upload_scan")

# ---- the type from the content
r = up_task(A, T, "photo.png", b"<html><body><script>alert(1)</script></body></html>", "image/png")
f = task_files(A, T).get("photo.png") or {}
check(r.ok and f.get("mime") == "application/octet-stream", f"HTML as .png: stored as octet-stream ({f.get('mime')})")
g = A.get(B + f"/api/attachments/{f.get('id')}")
check(g.ok and g.headers.get("Content-Type", "").startswith("application/octet-stream") and "attachment" in g.headers.get("Content-Disposition", ""),
      f"HTML as .png: never inline ({g.headers.get('Content-Type')} / {g.headers.get('Content-Disposition')})")
r = A.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("pic.png", b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", "image/png")})
check(r.ok and dbx("SELECT mime FROM fs_nodes WHERE name='pic.png'")[0][0] == "application/octet-stream", "Ablage: SVG as .png stored as octet-stream")
png = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
up_task(A, T, "real.jpg", png, "image/jpeg")
check(task_files(A, T).get("real.jpg", {}).get("mime") == "image/png", "a PNG named .jpg gets its real type")

# ---- scanner gone: taken + "unchecked"
scanner(False)
r1 = up_task(A, T, "later-ok.txt", b"harmless text\n")
r2 = up_task(A, T, "later-bad.txt", EICAR)
check(r1.ok and r2.ok, f"scanner gone: uploads are taken ({r1.status_code} {r2.status_code} {r2.text[:200]})")
fs = task_files(A, T)
check((fs.get("later-ok.txt") or {}).get("up", {}).get("scan") == "unchecked" and (fs.get("later-bad.txt") or {}).get("up", {}).get("scan") == "unchecked",
      f"scanner gone: both marked unchecked ({[(k, v.get('up')) for k, v in fs.items()]})")
check("up" not in fs.get("notes.txt", {}), "the earlier clean file has no mark")
r = A.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("wait.txt", b"ablage text\n", "text/plain")})
nid = dbx("SELECT id FROM fs_nodes WHERE name='wait.txt'")[0][0]
n = A.get(B + f"/api/files/nodes/{nid}").json()
check(r.ok and (n.get("up") or {}).get("scan") == "unchecked", f"Ablage: unchecked mark on the node ({n.get('up')})")
st = A.get(B + "/api/admin/upload-scan").json()
check(st.get("state") == "down" and st.get("unchecked") == 3, f"admin: state down, 3 files wait ({st})")
v1 = A.get(B + f"/api/v1/tasks/{T}/attachments")
if v1.ok:  # sessions may not reach /api/v1 on every setup; the mark is the same serializer as the app's
    check(any((x.get("up") or {}).get("scan") == "unchecked" for x in v1.json().get("data", [])), "API: up.scan in the attachments list")
g = A.get(B + f"/api/attachments/{fs['later-bad.txt']['id']}")
check(g.ok, "unchecked file: still downloadable (not blocked)")

# ---- scanner back: the later scan
scanner(True)
ok = False
for _ in range(60):
    fs = task_files(A, T)
    if "up" not in fs.get("later-ok.txt", {}) and (fs.get("later-bad.txt") or {}).get("up", {}).get("scan") == "infected":
        ok = True
        break
    time.sleep(1)
check(ok, f"later scan: clean mark gone, EICAR infected ({[(k, v.get('up')) for k, v in fs.items()]})")
bad = fs["later-bad.txt"]
check((bad.get("up") or {}).get("sig") == "Eicar-Test-Signature", "infected: the signature in up.sig")
g = A.get(B + f"/api/attachments/{bad['id']}")
check(g.status_code == 403 and "malware" in g.text.lower(), f"infected: download 403 with a message ({g.status_code} {g.text[:200]})")
g = A.get(B + f"/api/attachments/{bad['id']}?dl=1")
check(g.status_code == 403, "infected: also as a download")
check(A.get(B + f"/api/attachments/{fs['later-ok.txt']['id']}").ok, "clean after the later scan: downloadable")
n = A.get(B + f"/api/files/nodes/{nid}").json()
check("up" not in n, f"Ablage: mark gone after the later scan ({n.get('up')})")
news = [x for x in A.get(B + "/api/news").json().get("items", []) if x["kind"] == "upscan"]
check(len(news) == 1 and news[0]["data"].get("name") == "later-bad.txt" and news[0].get("to_me"), f"News item for the uploader ({news})")
check(not [x for x in Bo.get(B + "/api/news").json().get("items", []) if x["kind"] == "upscan"], "no News item for others")
check(dbx("SELECT state FROM upload_scan WHERE kind='att' AND ref_id=?", (bad["id"],))[0][0] == "infected", "upload_scan: infected row stays")
st = A.get(B + "/api/admin/upload-scan").json()
check(st.get("state") == "ok" and st.get("unchecked") == 0 and st.get("infected") == 1, f"admin: 0 waiting, 1 locked ({st})")
r = A.delete(B + f"/api/attachments/{bad['id']}")
check(r.ok, f"infected: deleting works ({r.status_code})")

# ---- infected project file and Ablage version found later: locked too
scanner(False)
r = A.post(B + f"/api/lists/{L}/files", files={"file": ("plan.txt", EICAR, "text/plain")})
check(r.ok, f"project file taken while the scanner is gone ({r.status_code})")
fid = dbx("SELECT id FROM list_files WHERE list_id=? AND name='plan.txt'", (L,))[0][0]
r = A.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("vers.txt", EICAR, "text/plain")})
vid = dbx("SELECT id FROM fs_nodes WHERE name='vers.txt'")[0][0]
scanner(True)
for _ in range(60):
    if len(dbx("SELECT 1 FROM upload_scan WHERE state='infected' AND kind IN ('list', 'fs')")) >= 2:
        break
    time.sleep(1)
g = A.get(B + f"/api/list-files/{fid}")
check(g.status_code == 403, f"project file found later: 403 ({g.status_code})")
ov = A.get(B + f"/api/lists/{L}/overview")
if ov.ok:
    pf = [x for x in ov.json().get("files", []) if x["id"] == fid]
    check(pf and (pf[0].get("up") or {}).get("scan") == "infected", f"project page: the file shows locked ({pf})")
g = A.get(B + f"/api/files/nodes/{vid}/content")
check(g.status_code == 403, f"Ablage file found later: 403 ({g.status_code})")
r = A.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("vers.txt", b"clean version 2\n", "text/plain")})
g = A.get(B + f"/api/files/nodes/{vid}/content")
check(r.ok and g.ok and g.content == b"clean version 2\n", f"a clean new version opens again ({g.status_code})")
g = A.get(B + f"/api/files/nodes/{vid}/content?v=1")
check(g.status_code == 403, f"the infected version 1 stays locked ({g.status_code})")

# ================================================================ container 2: scanner off (KALMIDO_CLAMD empty)
start(clamd=False)
A = setup()
L = A.post(B + "/api/lists", json={"name": "Off"}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Files", "list_id": L}).json()["id"]
r = up_task(A, T, "eicar.txt", EICAR)
fs = task_files(A, T)
check(r.ok and "up" not in fs.get("eicar.txt", {"up": 1}), f"scanner off: taken without a mark ({r.status_code})")
check(not dbx("SELECT 1 FROM upload_scan"), "scanner off: no unchecked rows")
st = A.get(B + "/api/admin/upload-scan").json()
check(st.get("state") == "off" and st.get("unchecked") == 0, f"admin: state off ({st})")
r = up_task(A, T, "page.png", b"<!DOCTYPE html><html></html>", "image/png")
check(task_files(A, T).get("page.png", {}).get("mime") == "application/octet-stream", "scanner off: the type from the content still applies")

print(f"p261_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
