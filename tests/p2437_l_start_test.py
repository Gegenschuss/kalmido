#!/usr/bin/env python3
"""2.437.0 (#3729): init_db names its steps and their milliseconds in the start log; no content, and lines the operator's
filtered start log keeps. A one-shot that takes over a second (the projects trees over many lists) gets a line of its own."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kt import check, dbx, done, fresh, setup, sess, until, B  # noqa: E402

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
LISTS, TASKS = 200, 2000
LINE = re.compile(r"^migrations: start (step [a-z0-9_]+ \d+ ms|total \d+ ms, \d+ step\(s\) under 1 s took \d+ ms|still running, \d+ s since step [a-z0-9_]+)$")


def logs():
    p = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return [x.strip() for x in (p.stdout + p.stderr).splitlines()]


def clock_lines():
    return [x for x in logs() if x.startswith("migrations: start")]


fresh()
setup()
A = sess("alice")
SECRET = "unmistakable-title-3729"
lid = A.post(B + "/api/lists", json={"name": "L", "folder": "F"}).json()["id"]
A.post(B + "/api/tasks", json={"title": SECRET, "list_id": lid})
first = clock_lines()
check(any(" total " in x for x in first), "the start log has the total of the steps")
check(all(LINE.match(x) for x in first), "only step names and numbers: " + repr(first[:3]))
check(all("migrat" in x for x in first), "every line passes the operator's filter")

cols = [r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_name='lists' AND column_name NOT IN ('id','name','folder') "
                          "AND is_generated='NEVER' ORDER BY ordinal_position")]
cs = ",".join(cols)
dbx(f"INSERT INTO lists(name,folder,{cs}) SELECT 'm' || g, 'F' || (g % 20), {cs} FROM lists l, generate_series(1,{LISTS}) g WHERE l.id={lid}")
tc = [r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_name='tasks' AND column_name NOT IN ('id','list_id','title') "
                        "AND is_generated='NEVER' AND column_name NOT LIKE 'tt_%' ORDER BY ordinal_position")]
ts = ",".join(tc)
tid = dbx("SELECT id FROM tasks WHERE title=?", (SECRET,))[0][0]
dbx(f"INSERT INTO tasks(list_id,title,{ts}) SELECT (SELECT min(id) FROM lists) + (g % {LISTS}), 't' || g, {ts} FROM tasks t, generate_series(1,{TASKS}) g WHERE t.id={tid}")
for u in ("bob", "carol", "dave", "erin"):
    A.post(B + "/api/users", json={"username": u, "display_name": u, "password": "password123"})
aid = dbx("SELECT id FROM users WHERE username='alice'")[0][0]
dbx(f"UPDATE lists SET owner_id={aid} WHERE owner_id IS NULL")
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,added_at) SELECT l.id,u.id,'edit','edit','2026-01-01T00:00:00' FROM lists l, users u WHERE u.id<>l.owner_id AND l.is_inbox=0 ON CONFLICT DO NOTHING")
dbx("INSERT INTO folder_people(owner_id,folder,user_id,role,created_at) SELECT DISTINCT l.owner_id,l.folder,u.id,'edit','2026-01-01T00:00:00' FROM lists l, users u WHERE u.id<>l.owner_id AND l.folder<>'' ON CONFLICT DO NOTHING")
dbx("DELETE FROM settings WHERE key='migr_lf2352'")
subprocess.run(["docker", "restart", CT], check=True, capture_output=True)
until(lambda: sum(" total " in x for x in clock_lines()) > 1, 300)
new = clock_lines()[len(first):]
check(any(" step migr_lf2352 " in x for x in new), "a one-shot over 1 s has a line of its own: " + repr(new))
check(any(" total " in x for x in new), "a second start reports too")
check(all(LINE.match(x) for x in new), "only names and numbers on the second start")
check(not any(SECRET in x for x in logs()), "no content in the log")
sys.exit(done("p2437_l_start"))
