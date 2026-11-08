#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.742.0 part D (#5217) API tests: code integrity stage 1 - the web manifest (kalmido/core/codemanifest.py). Own container
(start.sh); the source tree next to tests/ is the one the container runs.
freelancer-matrix: public
 - GET /api/code-manifest without signing in: JSON {v: 1, version (= /api/version app), algo: sha256, files: {url: 64 hex}},
   only hashes, no cookie set, not cached; a person without an organisation gets the same bytes
 - every entry is the SHA-256 of the bytes that really go out at that url (every file under /static/, the language parts,
   /sw.js, the app page "/" and /capture), asked like a browser without packing
 - the 12-digit hashes of /sw-manifest.json (files and the language parts) are the first digits of the full ones
 - it covers every file of SHELL / LAZY / LAZY_CSS of sw.js and every script / stylesheet of the served app page; their ?v=
   is the start of the manifest's hash
 - tools/web_manifest.py (no app, no server) built twice independently gives the same bytes, and they are the bytes the
   server answers
usage: p2742_d_code_manifest_api_test.py <datadir>   (P2742D_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import hashlib
import json
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check  # noqa: E402

HEX64 = re.compile(r"[0-9a-f]{64}")
kt.fresh(prefix="P2742D")
A = kt.setup()
FID, Fr = freelancer(B, A)  # freelancer-matrix: public (the same manifest without an organisation)
anon = requests.Session()
anon.headers["Accept-Encoding"] = "identity"  # the plain bytes (no packed copy, no gzip of the language parts)

# ------------------------------------------------------------------ the route
r = anon.get(B + "/api/code-manifest")
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/json"),
      f"#5217: /api/code-manifest without signing in: {r.status_code} {r.headers.get('Content-Type')}")
check("no-store" in r.headers.get("Cache-Control", ""), f"#5217: not cached ({r.headers.get('Cache-Control')!r})")
check("Set-Cookie" not in r.headers, "#5217: no session cookie for the manifest")
BODY = r.content
man = r.json()
files = man.get("files") or {}
check(man.get("v") == 1 and man.get("algo") == "sha256", f"#5217: format v=1 sha256 ({man.get('v')}, {man.get('algo')})")
check(man.get("version") == A.get(B + "/api/version").json().get("app"), f"#5217: the version of the code ({man.get('version')})")
check(set(man) == {"v", "version", "algo", "files"}, f"#5217: nothing but the format, the version and the hashes ({sorted(man)})")
check(len(files) > 300 and all(u.startswith("/") and HEX64.fullmatch(h or "") for u, h in files.items()),
      f"#5217: {len(files)} entries, every one a path with a full SHA-256")
check(list(files) == sorted(files), "#5217: the entries sorted by path (the same bytes everywhere)")
for u in ("/", "/sw.js", "/static/app.css", "/static/js/core.js", "/static/i18n.js", "/static/i18n/de.core.json", "/static/index.html"):
    check(u in files, f"#5217: {u} is in the manifest")
check(any(u.startswith("/static/vendor/") for u in files), "#5217: the vendor files are in the manifest")
check(any(re.fullmatch(r"/static/i18n/de\.mod-[\w-]+\.json", u) for u in files), "#5217: the module language parts are in it")
check(not any(u.startswith(("/manifest.json", "/api/")) for u in files), "#5217: no dynamic answer in it (manifest.json, API)")
check(Fr.get(B + "/api/code-manifest").content == BODY, "#5217: a person without an organisation gets the same bytes")

# ------------------------------------------------------------------ every entry = the bytes that go out
bad = []
for u, h in files.items():
    g = anon.get(B + u)
    if g.status_code != 200 or hashlib.sha256(g.content).hexdigest() != h:
        bad.append((u, g.status_code))
check(not bad, f"#5217: every entry is the SHA-256 of what the server sends at that url ({len(files)} urls; differ: {bad[:8]})")
cap = anon.get(B + "/capture")
check(hashlib.sha256(cap.content).hexdigest() == files["/"], "#5217: /capture sends the same app page as /")

# ------------------------------------------------------------------ the service worker's 12 digits are the start of the full hash
swm = anon.get(B + "/sw-manifest.json").json()
off = [u for u, h in (swm.get("files") or {}).items() if not (files.get(u) or "").startswith(h)]
check(swm.get("files") and not off, f"#5217: every hash of /sw-manifest.json starts the manifest's hash ({off[:5]})")
i18n_full = {h[:12] for u, h in files.items() if u.startswith("/static/i18n/")}
check(swm.get("i18n") and set(swm["i18n"]) <= i18n_full, "#5217: the language part versions of sw-manifest.json start manifest hashes")

# ------------------------------------------------------------------ coverage: sw.js lists, the app page's tags
sw = anon.get(B + "/sw.js").text
lists = {m.group(1): re.findall(r"'(/static/[\w./-]+)'", m.group(2)) for m in re.finditer(r"const (SHELL|LAZY|LAZY_CSS) = \[(.*?)\];", sw, re.S)}
check(set(lists) == {"SHELL", "LAZY", "LAZY_CSS"} and all(lists.values()), f"#5217: sw.js has SHELL / LAZY / LAZY_CSS ({sorted(lists)})")
miss = [u for v in lists.values() for u in v if u not in files]
check(not miss, f"#5217: the manifest covers every file the service worker precaches (missing {miss[:5]})")
page = anon.get(B + "/").text
tags = re.findall(r'<(?:script|link)\b[^>]*?\b(?:src|href)="(/static/[\w./-]+\.(?:js|css))(?:\?v=([0-9a-f]+))?"', page)
check(len(tags) > 100, f"#5217: the app page loads {len(tags)} start files")
miss = [u for u, _ in tags if u not in files]
check(not miss, f"#5217: the manifest covers every script / stylesheet of the app page (missing {miss[:5]})")
wrong = [u for u, v in tags if not v or not files.get(u, "").startswith(v)]
check(not wrong, f"#5217: every ?v= of the app page is the start of the manifest's hash ({wrong[:5]})")

# ------------------------------------------------------------------ the tool: twice the same, and the server's bytes
t = subprocess.run([sys.executable, os.path.join(SRC, "tools", "web_manifest.py"), "--root", SRC, "--twice"],
                   capture_output=True, timeout=600)
check(t.returncode == 0, f"#5217: tools/web_manifest.py --twice: built twice, the same ({t.stderr.decode()[-400:]})")
tool = t.stdout
if tool != BODY:
    try:
        tf = json.loads(tool).get("files", {})
        diff = sorted(u for u in set(tf) | set(files) if tf.get(u) != files.get(u))
    except ValueError:
        diff = ["(no JSON)"]
    print("tool and server differ at:", diff[:20], flush=True)
check(tool == BODY, "#5217: the tool's manifest of the source tree is byte for byte what the server answers")

sys.exit(kt.done("p2742_d_code_manifest_api"))
