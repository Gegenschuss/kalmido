#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.574.0 C (#3779): sharing through the ntfy app is gone (decided 30.10.2026), notifications through ntfy stay. Own container
(start.sh, its ntfy stub on 127.0.0.1:9999 logs every publish to /data/ntfy.log), old NTFY_INBOX_* variables set; invented names only.
 - the personal share inbox has no route any more (GET / PUT /api/me/ntfy-inbox 404), for a member and a person without an
   organisation (freelancer-matrix: own)
 - the table ntfy_inboxes of an older version (with a row) is dropped at the start (migrations.d/3779.py), and stays gone
 - /api/state carries no ntfy_inbox any more (me and top level), ntfy_url stays
 - old NTFY_INBOX_* variables start no inbox loop and no admin alert
 - notifications by ntfy go on: the test push reaches the person's topic (member and freelancer), an admin sets a push topic
   (before 2.574 it was checked against the share inboxes)
usage: p2574_c_ntfy_test.py <datadir>"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, DATA, check, sess, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
import requests  # noqa: E402

kt.fresh(env={"NTFY_INBOX_URL": "http://127.0.0.1:9999", "NTFY_INBOX_TOKEN": "tk-old-3779",
              "NTFY_INBOX_TOPIC": "old-share-inbox-topic-3779"}, prefix="P2574C")
A = kt.setup()
check(A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": kt.PASSWORD, "email": "bob@example.com"}).ok, "setup: bob")
Bo = sess("bob")
FID, Fr = freelancer(B, A)
uid = {r[0]: r[1] for r in kt.dbx("SELECT username, id FROM users")}


def healthy():
    try:
        return requests.get(B + "/api/health", timeout=2).ok
    except requests.RequestException:
        return False


def pushes(topic):
    try:
        with open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip() and json.loads(x)["topic"] == topic]
    except FileNotFoundError:
        return []


# ---- an older version's table with a row: the start drops it
kt.dbx("CREATE TABLE IF NOT EXISTS ntfy_inboxes (user_id BIGINT PRIMARY KEY, enabled BIGINT NOT NULL DEFAULT 0, topic TEXT NOT NULL DEFAULT '')")
kt.dbx("INSERT INTO ntfy_inboxes(user_id, enabled, topic) VALUES(%d, 1, 'bobs-old-share-topic-3779')" % uid["bob"])
check(kt.dbx("SELECT to_regclass('ntfy_inboxes')")[0][0], "setup: the old table with a row")
subprocess.run(["docker", "restart", CT], capture_output=True)
check(until(healthy, 60), "the server comes back after the restart")
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_ntfy.py"], capture_output=True)
check(kt.dbx("SELECT to_regclass('ntfy_inboxes')")[0][0] is None, "#3779: the start dropped the table ntfy_inboxes")

# ---- no route, no state
Bo, Fr = sess("bob"), sess("frida")
for who, s in (("member", Bo), ("admin", A), ("freelancer", Fr)):
    g, p = s.get(B + "/api/me/ntfy-inbox"), s.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": "some-long-share-topic-3779"})
    check(g.status_code == 404 and p.status_code in (404, 405), f"#3779: {who}: the share inbox route is gone ({g.status_code} / {p.status_code})")
st = Bo.get(B + "/api/state").json()
check("ntfy_inbox" not in st and "ntfy_inbox" not in st["me"] and "ntfy_url" in st, f"#3779: the state has no ntfy_inbox, ntfy_url stays {sorted(k for k in st if 'ntfy' in k)}")
check(kt.dbx("SELECT to_regclass('ntfy_inboxes')")[0][0] is None, "#3779: the table stays gone")

# ---- notifications by ntfy go on (the stub has the push in its log)
for who, s, u in (("member", Bo, "bob"), ("freelancer", Fr, "frida")):
    topic = kt.dbx("SELECT value FROM user_settings WHERE user_id=%d AND key='ntfy_topic'" % uid[u])
    topic = topic[0][0] if topic else ""
    check(topic, f"setup: {who} has a push topic")
    r = s.post(B + "/api/ntfy/test")
    check(r.ok and r.json().get("ok") is True, f"#3779: {who}: the ntfy test push is sent ({r.status_code} {r.text[:80]})")
    check(until(lambda: pushes(topic), 15), f"#3779: {who}: the push reached the ntfy topic")
# an admin sets a push topic (before 2.574 it was compared with the share inboxes); the next push goes there
r = A.patch(B + "/api/users/%d" % uid["bob"], json={"ntfy_topic": "bobs-old-share-topic-3779"})
check(r.ok, f"#3779: the push topic of a former share inbox is free ({r.status_code} {r.text[:80]})")
r = sess("bob").post(B + "/api/ntfy/test")
check(r.ok and until(lambda: pushes("bobs-old-share-topic-3779"), 15), "#3779: the push goes to the new topic")

# ---- old NTFY_INBOX_* start nothing: no inbox loop in the log, no admin alert about it
log = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
check("ntfy inbox" not in (log.stdout + log.stderr).lower(), "#3779: no ntfy inbox loop / warning in the server log")
check(not [x for x in kt.dbx("SELECT key FROM settings WHERE key LIKE 'ntfy_inbox%'")], "#3779: no ntfy_inbox_since written")

sys.exit(kt.done("p2574_c_ntfy"))
