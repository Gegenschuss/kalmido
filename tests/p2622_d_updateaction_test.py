#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.622.0 D (#4514): the update hint shows the section "Action needed" of the target version's release text
 - update check against a fake release API (KALMIDO_UPDATE_URL): with the section (any heading level / case, cut at the next
   heading of the same or a higher level, HTML kept as plain text, length limited), without it (no field text)
 - an admin sees it (about.update_action), a plain user sees nothing of the update check
 - the same for an admin without an organisation (freelancer-matrix: settings)
usage: p2622_d_updateaction_test.py <datadir>      (KMT_NOSTART=1 / P2622D_NOSTART=1: a running server)"""
import json
import os
import subprocess
import sys
import time

import requests

from freelancer_fixture import freelancer
from kt import B, CT, DATA, H, check, done, fresh, sess, until

SERVER = '''import http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = open("/data/rel.json", "rb").read()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", 9991), H).serve_forever()
'''
BODY = ("## What's new\n- something\n\n### action needed:\n- Set `KALMIDO_X=1` in your .env\n- <script>alert(1)</script>\n\n"
        "### Other\nnot part of it\n")
BIG = "## Action Needed\n" + "line of text\n" * 400


def release(body):
    with open(os.path.join(DATA, "rel.json"), "w") as f:
        json.dump({"tag_name": "v99.0.0", "html_url": "https://github.com/example/kalmido/releases/tag/v99.0.0", "body": body}, f)


fresh(prefix="P2622D", env={"KALMIDO_UPDATE_CHECK": "1", "KALMIDO_UPDATE_URL": "http://127.0.0.1:9991/repos/x/releases/latest"})
with open(os.path.join(DATA, "fake_release.py"), "w") as f:
    f.write(SERVER)
release(BODY)  # after fresh(): it empties the data dir
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_release.py"])
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Org", "lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
assert r.ok, r.text
Bo = sess("bob")
FID, F = freelancer(B, A)


def about(s):
    return s.get(B + "/api/state").json()["about"]


def recheck(pred):
    """Switch the check off and on (queues a check) and wait until the cached answer fits pred (queued again if it did not)."""
    for _ in range(4):
        A.patch(B + "/api/admin/settings", json={"update_check": False})
        r = A.patch(B + "/api/admin/settings", json={"update_check": True})
        assert r.ok, r.text
        if until(lambda: pred(about(A)), 12):
            return True
    return False


ok = recheck(lambda a: a.get("latest") == "99.0.0" and a.get("update_action") == "- Set `KALMIDO_X=1` in your .env\n- <script>alert(1)</script>")
a = about(A)
check(ok and a["available"] is True, f"with the section: plain text, cut before the next heading {ok} {a!r}")
check("Other" not in a["update_action"] and "something" not in a["update_action"], "only the section")
check("update_action" not in about(Bo) and "latest" not in about(Bo), "a plain user sees nothing of the update check")
release(BIG)
ok = recheck(lambda a: len(a.get("update_action", "")) > 100)
check(ok and len(about(A)["update_action"]) <= 1500, f"a long section is limited {len(about(A)['update_action'])}")
release("## What's new\n- nothing to do\n")
ok = recheck(lambda a: a.get("update_action") == "")
check(ok and about(A)["available"] is True, "without the section: the hint stays, no text")
release(BODY)
# the same for an admin without an organisation (freelancer-matrix: settings)
r = A.patch(B + "/api/users/%s" % FID, json={"is_admin": True})
check(r.ok, f"freelancer made admin {r.status_code} {r.text[:100]}")
ok = recheck(lambda a: a.get("update_action"))
check(ok and "KALMIDO_X=1" in about(F).get("update_action", ""), "admin without organisation sees the section")
sys.exit(done("p2622_d"))
