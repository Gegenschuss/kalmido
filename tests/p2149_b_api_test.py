#!/usr/bin/env python3
"""2.149.0 API tests, part B: measuring (#2504), static files without a session (#2505), the service worker's hash
manifest (#2506). Own container (start.sh) with KALMIDO_SLOW_REQUEST_MS=1, so every request counts as slow.
freelancer-matrix: public
 - #2504: every signed-in answer carries Server-Timing (app;dur, db;dur;desc="n=..."), none without signing in (2.149.0
   review); a signed-in /api/state counts statements; the
   slow log line names method + route pattern only (no query string, no id, no user name); GET /api/admin/health has
   p50 / p95 / max of the last requests for the instance admin, 403 for a person without an organisation
 - #2505: a static file costs no database statement, with a valid, a wrong or no session cookie; it is served without
   signing in; the served index.html gives every start script / stylesheet ?v=<content hash> (sha256, 12 digits) and is
   never cached itself; the file with its hash is immutable, with another ?v= or none it stays revalidated
 - #2506: /sw-manifest.json without signing in: every static file of SHELL / LAZY / LAZY_CSS in sw.js with the hash of
   its served content, the dynamic pages ("/", "/manifest.json") not in it; no-cache
usage: p2149_b_api_test.py <datadir>   (P2149B_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import hashlib
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer, login  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
STARTED = not (os.environ.get("P2149B_NOSTART") or os.environ.get("KMT_NOSTART"))
TIMING = re.compile(r'^app;dur=(\d+(?:\.\d+)?), db;dur=(\d+(?:\.\d+)?);desc="n=(\d+)"$')


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def timing(r):
    m = TIMING.match(r.headers.get("Server-Timing", ""))
    return (float(m.group(1)), float(m.group(2)), int(m.group(3))) if m else None


if STARTED:
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA],
                       env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_SLOW_REQUEST_MS=1"),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FID, Fr = freelancer(B, A)  # freelancer-matrix: public (the same headers, files and manifest without an organisation)
anon = requests.Session()

# ================================================================== #2504 measuring
r = A.get(B + "/api/state")
t = timing(r)
check(r.ok and t is not None, f"#2504: /api/state carries Server-Timing {r.headers.get('Server-Timing')!r}")
check(t is not None and t[2] > 0 and t[1] > 0 and t[0] >= t[1], f"#2504: statements counted, db time within the request {t}")
r = Fr.get(B + "/api/state")
check(r.ok and (timing(r) or (0, 0, 0))[2] > 0, f"#2504: also for a person without an organisation {r.headers.get('Server-Timing')!r}")
r = anon.get(B + "/api/health")
# 2.149.0 review (#2504): Server-Timing only for signed-in requests (statement counts on login / password reset leaked
# whether an account exists), so an answer without signing in carries none
check(r.ok and "Server-Timing" not in r.headers, f"#2504: an answer without signing in carries no Server-Timing {r.headers.get('Server-Timing')!r}")
r = A.get(B + "/api/nope-does-not-exist")
check(timing(r) is not None, f"#2504: an error answer carries it too ({r.status_code})")
for i in range(5):
    A.get(B + "/api/state")
r = A.get(B + "/api/admin/health")
rq = r.json().get("requests") if r.ok else None
check(isinstance(rq, dict) and rq.get("n", 0) >= 5 and (rq.get("slow_ms") == 1 or not STARTED), f"#2504: health has the request numbers {rq}")
if isinstance(rq, dict):
    check(all(rq[k]["p50"] is not None and rq[k]["p50"] <= rq[k]["p95"] <= rq[k]["max"] for k in ("ms", "statements", "db_ms")),
          f"#2504: p50 <= p95 <= max {rq}")
check(Fr.get(B + "/api/admin/health").status_code == 403, "#2504: a person without an organisation reads no health numbers")
if STARTED:
    A.get(B + f"/api/tasks?scope=search&q=secretword{FID}")
    time.sleep(0.5)
    log = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    lines = [ln for ln in (log.stdout + log.stderr).splitlines() if ln.startswith("slow request:")]
    check(any(re.match(r"^slow request: GET /api/state \d+ ms, \d+ statements, db \d+ ms$", ln) for ln in lines),
          f"#2504: the slow log line (threshold 1 ms) {lines[-3:]}")
    check(not any("secretword" in ln or "?" in ln or "alice" in ln or "frida" in ln for ln in lines),
          "#2504: no query string, search word or user name in the slow log")
    check(not any(" /static/" in ln or "/api/health" in ln for ln in lines), "#2504: static files and the health check are never logged as slow")

# ================================================================== #2505 static files
for who, s in (("signed in", A), ("freelancer", Fr), ("no cookie", anon)):
    r = s.get(B + "/static/app.css")
    t = timing(r)
    # 2.149.0 review: Server-Timing only for signed-in requests; static files skip the session, so no header (or n=0)
    check(r.ok and (t is None or t[2] == 0), f"#2505: a static file costs no database statement ({who}: {t})")
r = anon.get(B + "/api/state")
check("Server-Timing" not in r.headers, f"review: no Server-Timing without signing in {r.headers.get('Server-Timing')!r}")
bad = requests.Session()
bad.cookies.set("kalmido_session", "not-a-session")
for p in ("/static/js/core.js", "/sw.js", "/robots.txt", "/sw-manifest.json"):
    r = bad.get(B + p)
    t = timing(r)
    # 2.149.0 review (#2504): a wrong cookie is no sign-in, and static files skip the session: header absent or n=0
    check(r.ok and (t is None or t[2] == 0), f"#2505: {p} with a wrong cookie: served, no statement {r.status_code} {r.headers.get('Server-Timing')!r}")
r = anon.get(B + "/manifest.json")
check(r.ok, "the app manifest still answers without signing in")
r = anon.get(B + "/api/state")
check(r.status_code == 401, f"an API route still needs a session ({r.status_code})")

r = A.get(B + "/")
html = r.text
check(r.ok and "no-cache" in r.headers.get("Cache-Control", "") and "immutable" not in r.headers.get("Cache-Control", ""),
      f"#2505: index.html itself is revalidated {r.headers.get('Cache-Control')!r}")
tags = re.findall(r'<script src="(/static/[\w./-]+\.js)(\?v=[^"]*)?"', html) + re.findall(r'<link rel="stylesheet" href="(/static/[\w./-]+\.css)(\?v=[^"]*)?"', html)
check(len(tags) > 100, f"#2505: the start scripts and stylesheets ({len(tags)})")
nov = [u for u, q in tags if not re.fullmatch(r"\?v=[0-9a-f]{12}", q or "")]
check(not nov, f"#2505: every start script / stylesheet carries ?v=<12 hex digits> (without: {nov[:5]})")
check(not re.search(r'<script[^>]*\sdefer', html), "#2505: start scripts keep their order and timing (no defer, see report)")
byurl = dict(tags)
for u in ("/static/js/core.js", "/static/app.css", "/static/i18n.js", "/static/js/main.js"):
    q = byurl.get(u) or ""
    body = anon.get(B + u).content
    check(q == "?v=" + hashlib.sha256(body).hexdigest()[:12], f"#2505: {u}: the hash is the served content's {q}")
    r = anon.get(B + u + q)
    cc = r.headers.get("Cache-Control", "")
    check(r.ok and "immutable" in cc and "max-age=31536000" in cc and "public" in cc, f"#2505: {u}{q} is immutable ({cc!r})")
    r = anon.get(B + u + "?v=000000000000")
    check(r.ok and "immutable" not in r.headers.get("Cache-Control", ""), f"#2505: {u} with another hash is not immutable {r.headers.get('Cache-Control')!r}")
    r = anon.get(B + u + "?v=2.149.0")
    check(r.ok and "immutable" not in r.headers.get("Cache-Control", ""), f"#2505: {u} with the code version (modules on demand) stays revalidated")
    r = anon.get(B + u)
    check(r.ok and "immutable" not in r.headers.get("Cache-Control", ""), f"#2505: {u} without ?v= stays as before {r.headers.get('Cache-Control')!r}")
r = A.get(B + "/capture")
check(r.ok and re.search(r'src="/static/js/main\.js\?v=[0-9a-f]{12}"', r.text), "#2505: the quick capture page is the same app page with hashes")
r = anon.get(B + "/static/%2e%2e/kalmido/core/pages.py?v=000000000000", allow_redirects=False)
check(r.status_code in (303, 400, 404) and "def static_hash" not in r.text, f"#2505: no file outside static/ ({r.status_code})")

# ================================================================== #2506 the service worker's manifest
r = anon.get(B + "/sw-manifest.json")
check(r.ok and "no-cache" in r.headers.get("Cache-Control", ""), f"#2506: /sw-manifest.json without signing in, no-cache {r.status_code} {r.headers.get('Cache-Control')!r}")
m = r.json() if r.ok else {}
files = m.get("files") or {}
sw = anon.get(B + "/sw.js").text
lists = re.findall(r"const (?:SHELL|LAZY|LAZY_CSS) = \[(.*?)\];", sw, re.S)
want = [u for blk in lists for u in re.findall(r"'(/static/[\w./-]+)'", blk)]
check(m.get("v") == 1 and len(lists) == 3 and len(want) > 200, f"#2506: manifest v1, the three lists of sw.js ({len(lists)}, {len(want)} files)")
check(set(files) == set(want), f"#2506: the manifest names exactly the static files of the lists (missing {sorted(set(want) - set(files))[:5]}, extra {sorted(set(files) - set(want))[:5]})")
check("/" not in files and "/manifest.json" not in files, "#2506: the dynamic pages are not hashed (always loaded)")
check(all(re.fullmatch(r"[0-9a-f]{12}", h) for h in files.values()), "#2506: 12 hex digits each")
for u in ("/static/js/core.js", "/static/icon-192.png", "/static/i18n/de.json", "/static/css/office.css", "/static/js/office.js"):
    if u in files:
        check(files[u] == hashlib.sha256(anon.get(B + u).content).hexdigest()[:12], f"#2506: {u}: the hash matches the served file")
    else:
        check(False, f"#2506: {u} in the manifest")
check(files.get("/static/js/core.js") and byurl.get("/static/js/core.js") == "?v=" + files["/static/js/core.js"],
      "#2506: index.html and the manifest name the same hash")
r = Fr.get(B + "/sw-manifest.json")
check(r.ok and r.json().get("files") == files, "#2506: the same for everyone (no user data in it)")

print(f"p2149_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
