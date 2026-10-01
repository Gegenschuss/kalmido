#!/usr/bin/env python3
"""2.5.0 tests: the app name Kalmido everywhere a client or integration sees it.
 - web app: page title, PWA manifest (name, short_name), service worker (notification fallback title, one shell cache,
   every other cache deleted on activate), i18n, the CSRF header value, the session cookie name
 - API: OpenAPI title + x-kalmido-scope, X-Kalmido-Unknown-Fields, the WWW-Authenticate realm, the ICS feed (PRODID, file
   name), backup file names and manifest format
 - configuration: KALMIDO_* environment variables are read (KALMIDO_UPDATE_CHECK=0 from start.sh, KALMIDO_API=0 in an
   own container turns the REST API off)
Starts its OWN containers (start.sh).
usage: p250_rename_test.py <datadir>"""
import json
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def start(extra=""):
    subprocess.run(["docker", "rm", "-f", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)  # 2.7.2: the old container must not write while its data goes
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=extra),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


start()
# ---- web app shell
html = requests.get(B + "/").text
check("<title>Kalmido</title>" in html, "index.html: title Kalmido")
check('apple-mobile-web-app-title" content="Kalmido"' in html, "index.html: iOS app title Kalmido")
man = requests.get(B + "/static/manifest.json").json()
check(man.get("name") == "Kalmido" and man.get("short_name") == "Kalmido", f"manifest: name / short_name ({man.get('name')}, {man.get('short_name')})")
sw = requests.get(B + "/static/sw.js").text
check("d.title || 'Kalmido'" in sw, "service worker: notification fallback title Kalmido")
check(len(re.findall(r"const CACHE = '[a-z-]+-v\d+';", sw)) == 1, "service worker: one versioned shell cache")
check("ks.filter(k => k !== CACHE).map(k => caches.delete(k))" in sw, "service worker: activate deletes every other (older) cache")
check("'X-Requested-With': 'kalmido'" in sw, "service worker: CSRF header value kalmido")
js = requests.get(B + "/static/app.js").text
check("const APP_NAME = 'Kalmido';" in js, "app.js: APP_NAME")
check("github.com/Gegenschuss/kalmido" in js, "app.js: repository links")
de = requests.get(B + "/static/i18n/de.json").json()
check(any("Kalmido" in k for k in de) and any("Kalmido" in v for v in de.values()), "de.json: Kalmido in keys and values")

# ---- sign-in: CSRF value + cookie name
s = requests.Session()
r = s.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
check(r.status_code == 403, f"setup without the CSRF header refused ({r.status_code})")
s.headers.update(H)
r = s.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
check(r.ok, f"setup with X-Requested-With: kalmido ({r.status_code} {r.text[:80]})")
check("kalmido_session" in s.cookies.get_dict(), f"session cookie kalmido_session ({list(s.cookies.get_dict())})")
bad = requests.Session()
bad.cookies.update(s.cookies)
bad.headers.update({"X-Requested-With": "other"})
check(bad.post(B + "/api/lists", json={"name": "x"}).status_code == 403, "another CSRF header value refused")
lid = s.post(B + "/api/lists", json={"name": "Rename"}).json()["id"]

# ---- API names
spec = requests.get(B + "/api/v1/openapi.json").json()
check("Kalmido" in spec["info"]["title"], f"OpenAPI title ({spec['info']['title']})")
check('"x-kalmido-scope"' in requests.get(B + "/api/v1/openapi.json").text, "OpenAPI: x-kalmido-scope")
r = requests.get(B + "/api/v1/lists")
check(r.status_code == 401 and 'realm="kalmido"' in r.headers.get("WWW-Authenticate", ""), f"API 401 realm ({r.headers.get('WWW-Authenticate')})")
r = s.post(B + "/api/tasks", json={"title": "t", "list_id": lid, "wibble": 1})
check(r.ok and r.headers.get("X-Kalmido-Unknown-Fields") == "wibble", f"X-Kalmido-Unknown-Fields ({r.headers.get('X-Kalmido-Unknown-Fields')})")
about = s.get(B + "/api/about").json()
check(about.get("update_env") is False or about.get("update_check") is False, f"KALMIDO_UPDATE_CHECK=0 read ({about})")
url = s.post(B + "/api/ical", json={"action": "create"}).json().get("url") or ""
r = requests.get(B + "/ical/" + url.rsplit("/ical/", 1)[-1])
check(r.ok and "PRODID:-//Kalmido//" in r.text and 'filename="kalmido.ics"' in r.headers.get("Content-Disposition", ""),
      f"ICS feed: PRODID + file name ({r.status_code})")
r = s.post(B + "/api/admin/backups", json={})
names = []
for _ in range(40):
    bdir = os.path.join(DATA, "backups")
    names = sorted(os.listdir(bdir)) if os.path.isdir(bdir) else []
    if any(n.endswith(".zip") for n in names):
        break
    time.sleep(0.5)
zips = [n for n in names if n.endswith(".zip")]
check(r.status_code == 202 and zips and all(n.startswith("kalmido-backup-") for n in zips), f"backup file names ({r.status_code} {names})")
if zips:
    import zipfile
    with zipfile.ZipFile(os.path.join(DATA, "backups", zips[0])) as z:
        man = next((json.loads(z.read(n)) for n in z.namelist() if n.endswith("manifest.json")), {})
    check(man.get("format") == "kalmido-backup", f"backup manifest format ({man.get('format')})")

# ---- KALMIDO_API=0 turns the REST API off (the new variable names are read)
start("-e KALMIDO_API=0")
check(requests.get(B + "/api/v1/openapi.json").status_code == 404, "KALMIDO_API=0: REST API off")
subprocess.run(["docker", "rm", "-f", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)

print(f"p250_rename: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
