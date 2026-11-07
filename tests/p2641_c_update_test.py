#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.641.0 C (#5011): the update check of a server (kalmido/core/instance.py update_fetch) against a WEEKLY release as
weekly-release.yml publishes it (text from tools/weekly_release.py, tag vX.Y.Z):
 - the version of the week is found, the hint shows the "Action needed" sections of ALL versions of the week (also one of an
   older version of the week), not the change list below them
 - a release on the tag latest-ok/X.Y.Z (the mistake the weekly workflow must not make) is no release: error, nothing offered
 - the same for an admin without an organisation (freelancer-matrix: settings)
usage: p2641_c_update_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, CT, DATA, H, check, done, fresh, sess, until

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import weekly_release as wr  # noqa: E402

SERVER = '''import http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = open("/data/rel.json", "rb").read()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", 9992), H).serve_forever()
'''
SECS = {
    (99, 0, 0): "Package 99.0 (Newest).\n### Added\n- A thing people see (#1).\n",
    (98, 9, 0): "Package 98.9 (Middle).\n### Action needed\n- Set `KALMIDO_NEW=1` in your .env\n\n### Fixed\n- A repaired thing (#2).\n",
    (98, 8, 0): "Package 98.8 (Oldest of the week).\n### Action needed\n- Run update.sh twice\n### Changed\n- Something else (#3).\n",
    (98, 7, 0): "### Action needed\n- belongs to the week before\n",
}
BODY, VERSIONS = wr.weekly_notes(SECS, "v98.7.0", (99, 0, 0))


def release(tag, body):
    with open(os.path.join(DATA, "rel.json"), "w") as f:
        json.dump({"tag_name": tag, "html_url": f"https://github.com/example/kalmido/releases/tag/{tag}", "body": body}, f)


fresh(prefix="P2641C", env={"KALMIDO_UPDATE_CHECK": "1", "KALMIDO_UPDATE_URL": "http://127.0.0.1:9992/repos/x/releases/latest"})
with open(os.path.join(DATA, "fake_release.py"), "w") as f:
    f.write(SERVER)
release("v99.0.0", BODY)  # after fresh(): it empties the data dir
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_release.py"])
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Org", "lang": "en", "collab_all": True})
FID, F = freelancer(B, A)


def about(s):
    return s.get(B + "/api/state").json()["about"]


def recheck(pred, s=None):
    """Switch the check off and on (queues a check) and wait until the cached answer fits pred."""
    for _ in range(4):
        A.patch(B + "/api/admin/settings", json={"update_check": False})
        r = A.patch(B + "/api/admin/settings", json={"update_check": True})
        assert r.ok, r.text
        if until(lambda: pred(about(s or A)), 12):
            return True
    return False


check(VERSIONS == [(98, 8, 0), (98, 9, 0), (99, 0, 0)], f"the week holds the versions above the last weekly release {VERSIONS}")
ok = recheck(lambda a: a.get("latest") == "99.0.0" and a.get("update_action"))
a = about(A)
act = a.get("update_action", "")
check(ok and a["available"] is True, f"the weekly release on v99.0.0 is found {ok} {a!r}")
check("KALMIDO_NEW=1" in act and "update.sh twice" in act and "98.9.0" in act and "98.8.0" in act,
      f"the hint shows the action of every version of the week, also an older one {act!r}")
check("belongs to the week before" not in act and "A thing people see" not in act and "repaired" not in act,
      f"only the collected section: no change list, nothing of the week before {act!r}")

release("latest-ok/99.0.1", BODY)
ok = recheck(lambda a: a.get("error"))
a = about(A)
check(ok and a.get("latest") == "99.0.0" and "99.0.1" not in json.dumps(a),
      f"a release on latest-ok/X.Y.Z is no release: error, the last known one stays {a!r}")

release("v99.0.0", BODY)
r = A.patch(B + "/api/users/%s" % FID, json={"is_admin": True})
check(r.ok, f"freelancer made admin {r.status_code} {r.text[:100]}")
ok = recheck(lambda a: "KALMIDO_NEW=1" in (a.get("update_action") or ""), F)
check(ok, "an admin without organisation sees the collected section too")
sys.exit(done("p2641_c_update"))
