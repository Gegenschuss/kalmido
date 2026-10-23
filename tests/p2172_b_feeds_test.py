#!/usr/bin/env python3
"""2.172.0 API tests (part B): feeds (#2678), own container (start.sh) with the fake feed server inside (fake_feeds.py).
A website answering 403 gets its own message (no password text), 401 stays the login message, a calendar subscription
answering 403 keeps the calendar text; feeds are fetched with their own sender ("feed reader")."""
import json
import os
import shutil
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check, sess  # 2.206.0 (#2762): shared helpers (tests/kt.py)
FS = "http://127.0.0.1:8098"


def flog():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "feeds.log"), encoding="utf-8")]
    except OSError:
        return []


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "fake_feeds.py"), DATA)
os.makedirs(os.path.join(DATA, "feeds"), exist_ok=True)
with open(os.path.join(DATA, "feeds", "rss.xml"), "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0"?><rss version="2.0"><channel><title>Example</title><link>https://example.com/</link></channel></rss>')
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_feeds.py"])
time.sleep(1)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "cal,feeds"})

# ================================================================== 403: own message, 401: login
r = A.post(B + "/api/feeds", json={"url": FS + "/status-403"})
e = r.json().get("error", "")
check(r.status_code == 400 and "does not allow fetches by servers (403)" in e and "password" not in e, "feed 403: own message " + r.text[:200])
r = A.post(B + "/api/feeds", json={"url": FS + "/status-401"})
check(r.status_code == 400 and "wrong username or password" in r.json().get("error", ""), "feed 401: the login message " + r.text[:200])
# a stored fetch error (background) shows the same text
r = A.post(B + "/api/feeds", json={"url": FS + "/rss.xml"})
check(r.status_code == 201, "a working feed " + r.text[:200])
ua = [x.get("ua", "") for x in flog() if x["p"] == "/rss.xml"]
check(ua and "(feed reader; +https://kalmido.com)" in ua[-1] and "calendar" not in ua[-1], "the feed sender " + repr(ua[-1:]))

# ================================================================== the calendar keeps its text on 403
r = A.post(B + "/api/calendars", json={"kind": "ics", "url": FS + "/status-403"})
e = r.json().get("error", "") if r.headers.get("content-type", "").startswith("application/json") else r.text
check(r.status_code >= 400 and "wrong username or password" in e and "fetches by servers" not in e, "calendar 403: unchanged " + r.text[:200])
cua = [x.get("ua", "") for x in flog() if x["p"] == "/status-403"]
check(cua and "(calendar subscription)" in cua[-1], "the calendar keeps its sender " + repr(cua[-1:]))

print(f"p2172_b_feeds: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
