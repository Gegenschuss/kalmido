#!/usr/bin/env python3
"""2.142.0 API tests, part C: export into Todoist CSV / Markdown (#2148), the admin button "Fetch mails now" (#2149), the ntfy share
inbox per person (#2150). Own container (start.sh) with a tiny ntfy server inside (stub_ntfyin.py); invented names only.
#2148:
 - GET /api/export/todoist.zip: one CSV per list in the Todoist template (TYPE,CONTENT,...), sections as TYPE=section, subtasks by INDENT,
   priority high -> 1 / medium -> 2 / low -> 3 / none -> 4, tags as @label, a repeat as "every week", completed tasks left out
 - GET /api/export/markdown.zip: one .md per list, "# list", "## section", "- [ ]" / "- [x]", indented subtasks, the note indented
 - file names without path characters; another person's lists are not in it; a list with the lock stays out (+ a note file)
 - round trip: the own Todoist importer reads the own CSV again (titles, sections, subtasks, priority, due date)
 - a person without an organisation (freelancer-matrix: tasks) gets both files, with only their own lists
#2149: POST /api/admin/mail/poll: an admin 200 {ok}, a member 403 (mail is set up in this container)
#2150: GET/PUT /api/me/ntfy-inbox
 - default off, a long random suggestion; the token is never in an answer ("has_token" only), not in the database in plain text
 - a guessable topic on the public ntfy.sh is refused (400), a long one is accepted; an invalid topic / url is a 400
 - the polling loop takes what is published to a person's topic into THAT person's basket (a second person's basket stays empty),
   with the token as the bearer (stub log), not twice; a new topic / switching off stops the polling
 - a failing server counts for that person only (fails, last_error), the others keep working
 - a person without an organisation (freelancer-matrix: own) can switch it on and receives
usage: p2142_c_api_test.py <datadir>      (P2142C_NOSTART=1 = the server already runs, with the stub on port 8099)"""
import io
import json
import os
import subprocess
import sys
import time
import zipfile

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess, until  # 2.192.0 (#2514): shared helpers (tests/kt.py)
STUB = "http://127.0.0.1:8099"


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def zip_of(r):
    return zipfile.ZipFile(io.BytesIO(r.content))


def publish(msgs):
    with open(os.path.join(DATA, "ntfyin_msgs.json"), "w") as f:
        json.dump(msgs, f)


def stub_log():
    p = os.path.join(DATA, "ntfyin.log")
    return [json.loads(x) for x in open(p).read().splitlines()] if os.path.exists(p) else []


if os.environ.get("P2142C_NOSTART") != "1":
    extra = ["-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8099", "-e KALMIDO_NTFYIN_TICK=1", "-e KALMIDO_MAIL_ADDRESS=tasks@example.test",
             "-e KALMIDO_IMAP_HOST=127.0.0.1", "-e KALMIDO_IMAP_PORT=1143", "-e KALMIDO_IMAP_SSL=0", "-e KALMIDO_IMAP_USER=kalmido",
             "-e KALMIDO_IMAP_PASSWORD=secret", "-e KALMIDO_IMAP_INTERVAL=600"]
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(extra)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["cp", os.path.join(N, "stub_ntfyin.py"), DATA])
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_ntfyin.py"])
    time.sleep(1.2)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Delta", "lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ids = {"alice": A.get(B + "/api/me").json()["id"]}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.test"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
FID, Fr = freelancer(B, A)


def mk_list(s, name):
    r = s.post(B + "/api/lists", json={"name": name})
    assert r.ok, r.text
    return r.json()["id"]


def mk_task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"list_id": lid, "title": title, **kw})
    assert r.ok, (title, r.text)
    return r.json()["id"]


# ================================================================== #2148 export
L1 = mk_list(A, "Plan / Q4: \"launch\"")
sec = A.post(B + "/api/sections", json={"list_id": L1, "name": "Phase one"})
assert sec.ok, sec.text
SEC = sec.json()["id"]
t1 = mk_task(A, L1, "Write the brief", priority=5, due="2026-11-02", due_time="14:30", content="Line one\nLine two", tags=["work"])
mk_task(A, L1, "Draft outline", parent_id=t1, priority=3)
mk_task(A, L1, "Weekly review", repeat="FREQ=WEEKLY", due="2026-11-03", section_id=SEC, priority=1)
done = mk_task(A, L1, "Old chore")
assert A.post(B + f"/api/tasks/{done}/complete", json={}).ok
mk_task(A, L1, "No priority task", section_id=SEC)
L2 = mk_list(A, "Private errands")
mk_task(A, L2, "Buy stamps")
mk_task(Bo, mk_list(Bo, "Bob only"), "Bob secret task")

r = A.get(B + "/api/export/todoist.zip")
check(r.ok and r.headers.get("Content-Type", "").startswith("application/zip"), f"todoist zip served ({r.status_code} {r.headers.get('Content-Type')})")
check("attachment" in r.headers.get("Content-Disposition", ""), "todoist zip: download header")
z = zip_of(r)
names = z.namelist()
check(all("/" not in n and "\\" not in n and ".." not in n and '"' not in n for n in names), f"safe member names {names}")
check(any("Bob only" in n for n in names) is False and "Bob secret task" not in b"".join(z.read(n) for n in names).decode(), "another person's list is not in it")
csv1 = z.read(next(n for n in names if n.startswith("Plan"))).decode()
lines = csv1.splitlines()
check(lines[0] == "TYPE,CONTENT,DESCRIPTION,PRIORITY,INDENT,AUTHOR,RESPONSIBLE,DATE,DATE_LANG,TIMEZONE", f"Todoist header {lines[0]}")
import csv as csvm  # noqa: E402
rows = list(csvm.DictReader(io.StringIO(csv1)))
by = {x["CONTENT"].split(" @")[0]: x for x in rows}
check(by["Write the brief"]["PRIORITY"] == "1" and by["Write the brief"]["INDENT"] == "1", f"high -> 1, top level {by['Write the brief']}")
check("@work" in next(x["CONTENT"] for x in rows if x["CONTENT"].startswith("Write the brief")), "tag as @label")
check(by["Write the brief"]["DESCRIPTION"] == "Line one\nLine two", "note as DESCRIPTION")
check(by["Write the brief"]["DATE"] == "2026-11-02 14:30", f"date with time {by['Write the brief']['DATE']}")
check(by["Draft outline"]["INDENT"] == "2" and by["Draft outline"]["PRIORITY"] == "2", "subtask: INDENT 2, medium -> 2")
check(by["Weekly review"]["DATE"] == "every week" and by["Weekly review"]["PRIORITY"] == "3", f"repeat as text, low -> 3 {by['Weekly review']}")
check("Old chore" not in by, "completed task left out of the CSV")
check(by["No priority task"]["PRIORITY"] == "4", "none -> 4")
check(any(x["TYPE"] == "section" and x["CONTENT"] == "Phase one" for x in rows), "section row")
order = [x["CONTENT"].split(" @")[0] for x in rows]
check(order.index("Phase one") < order.index("Weekly review"), "section row before its tasks")

r = A.get(B + "/api/export/markdown.zip")
check(r.ok and r.headers.get("Content-Type", "").startswith("application/zip"), "markdown zip served")
z = zip_of(r)
md = z.read(next(n for n in z.namelist() if n.startswith("Plan"))).decode()
check(md.startswith('# Plan / Q4: "launch"\n'), f"markdown title {md[:40]!r}")
check("- [ ] Write the brief (due 2026-11-02 14:30, high priority) #work" in md, "task line with date, priority, tag")
check("\n  - [ ] Draft outline (medium priority)" in md, "subtask indented")
check("\n  Line one\n  Line two" in md, "note indented")
check("\n## Phase one\n" in md and "- [ ] Weekly review (due 2026-11-03, low priority, repeats FREQ=WEEKLY)" not in md, "section; the rule is worded if possible")
check("- [x] Old chore" in md, "completed task as [x] in Markdown")
check(all(not n.endswith("/") and ".." not in n for n in z.namelist()), "markdown member names safe")

# round trip: the own importer reads the own CSV
zipdata = A.get(B + "/api/export/todoist.zip").content
for fname, data in (("Plan.csv", csv1.encode()), ("all.zip", zipdata)):
    r = A.post(B + "/api/import/todoist", files={"file": (fname, data)}, data={"dry_run": "1"})
    check(r.ok, f"importer takes the own Todoist {fname} ({r.status_code} {r.text[:200]})")
    if r.ok:
        txt = json.dumps(r.json())
        check("Write the brief" in txt and "Draft outline" in txt and "Phase one" in txt, f"round trip {fname}: titles + section read again")

# locked list stays out
lk = mk_list(A, "Locked list")
dbx("UPDATE lists SET e2e='x' WHERE id=?", (lk,))
z = zip_of(A.get(B + "/api/export/todoist.zip"))
check(not any(n.startswith("Locked") for n in z.namelist()), "a list with the lock is not exported")
note = [n for n in z.namelist() if n.startswith("README-locked")]
check(note and "Locked list" in z.read(note[0]).decode(), "note file names the locked list")
dbx("UPDATE lists SET e2e=NULL WHERE id=?", (lk,))

# freelancer-matrix: tasks
fl = mk_list(Fr, "Frida list")
mk_task(Fr, fl, "Frida task", priority=5)
for kind in ("todoist", "markdown"):
    r = Fr.get(B + f"/api/export/{kind}.zip")
    z = zip_of(r) if r.ok else None
    blob = b"".join(z.read(n) for n in z.namelist()).decode() if z else ""
    check(r.ok and "Frida task" in blob and "Write the brief" not in blob, f"freelancer: {kind} export has only the own lists ({r.status_code})")
check(requests.get(B + "/api/export/todoist.zip", headers=H).status_code in (401, 403), "export needs a login")

# ================================================================== #2149 admin button
r = A.post(B + "/api/admin/mail/poll")
check(r.status_code == 200 and r.json().get("ok") is True, f"admin: poll started ({r.status_code} {r.text[:80]})")
check(Bo.post(B + "/api/admin/mail/poll").status_code == 403, "member: 403")
check(Fr.post(B + "/api/admin/mail/poll").status_code == 403, "freelancer (no instance admin): 403")

# ================================================================== #2150 ntfy share inbox per person
g = Bo.get(B + "/api/me/ntfy-inbox").json()
check(g["enabled"] is False and g["topic"] == "" and len(g["suggest"]) >= 16 and g["has_token"] is False, f"default: off, a suggestion {g}")
check(Bo.get(B + "/api/me/ntfy-inbox").json()["suggest"] != g["suggest"], "the suggestion is random")
r = Bo.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": "inbox", "url": "https://ntfy.sh"})
check(r.status_code == 400, f"guessable topic on ntfy.sh refused ({r.status_code})")
r = Bo.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": "bad topic!", "url": STUB})
check(r.status_code == 400, "invalid topic refused")
r = Bo.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": "bobs-secret-share-topic-1234", "url": "file:///etc/passwd"})
check(r.status_code == 400, "file:// server refused")
r = Bo.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": "bobs-secret-share-topic-1234", "url": "https://ntfy.sh"})
check(r.ok and r.json()["enabled"] is True, f"a long topic on ntfy.sh is fine ({r.status_code} {r.text[:100]})")
TOK = "tk_secretreadtoken123"
r = Bo.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": "bobs-secret-share-topic-1234", "url": STUB, "token": TOK})
j = r.json() if r.ok else {}
check(r.ok and j.get("has_token") is True and "token" not in j and TOK not in r.text, f"token set, never returned ({r.status_code})")
check(TOK not in Bo.get(B + "/api/me/ntfy-inbox").text and TOK not in A.get(B + "/api/export.json").text, "token in no answer / export")
check(dbx("SELECT token FROM ntfy_inboxes WHERE user_id=?", (ids["bob"],))[0][0] not in ("", TOK), "token sealed in the database")
check(not Ca.get(B + "/api/me/ntfy-inbox").json()["enabled"], "carol's inbox is her own (off)")

publish([{"topic": "bobs-secret-share-topic-1234", "id": "m1", "message": "Shared by bob\nsecond line"}])
got = until(lambda: dbx("SELECT created_by FROM tasks WHERE title='Shared by bob'"))
check(got and got[0][0] == ids["bob"], f"the message is a task in bob's basket {got}")
check(not dbx("SELECT 1 FROM tasks WHERE title='Shared by bob' AND created_by<>?", (ids["bob"],)), "no copy for anyone else")
check(any(x["auth"] == "Bearer " + TOK and "/bobs-secret-share-topic-1234/json" in x["path"] for x in stub_log()), "polled with the token as bearer")
n0 = len(dbx("SELECT 1 FROM tasks WHERE title='Shared by bob'"))
time.sleep(3)
check(len(dbx("SELECT 1 FROM tasks WHERE title='Shared by bob'")) == n0 == 1, "not imported twice")
publish([{"topic": "bobs-secret-share-topic-1234", "id": "m1", "message": "Shared by bob"}, {"topic": "bobs-secret-share-topic-1234", "id": "m2", "message": "Second one"}])
check(until(lambda: dbx("SELECT 1 FROM tasks WHERE title='Second one'")), "a later message arrives")
check(dbx("SELECT fails, last_ok FROM ntfy_inboxes WHERE user_id=?", (ids["bob"],))[0][0] == 0 and dbx("SELECT last_ok FROM ntfy_inboxes WHERE user_id=?", (ids["bob"],))[0][0], "state: no failures, last_ok set")

# a failing server counts for that person only
r = Ca.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": "down-carols-topic-123456", "url": STUB})
check(r.ok, f"carol on {r.status_code}")
st = until(lambda: (lambda g: g if g["fails"] >= 1 else None)(Ca.get(B + "/api/me/ntfy-inbox").json()))
check(st and st["last_error"].startswith("http"), f"carol: failures counted ({st and st['last_error']})")
check(Bo.get(B + "/api/me/ntfy-inbox").json()["fails"] == 0, "bob unaffected")
publish([{"topic": "bobs-secret-share-topic-1234", "id": "m3", "message": "Third while carol fails"}])
check(until(lambda: dbx("SELECT 1 FROM tasks WHERE title='Third while carol fails'")), "bob still receives while carol's server fails")

# new topic / off
old = Bo.get(B + "/api/me/ntfy-inbox").json()["topic"]
r = Bo.put(B + "/api/me/ntfy-inbox", json={"new_topic": True})
check(r.ok and r.json()["topic"] != old and len(r.json()["topic"]) >= 16, "dice: a new long topic")
publish([{"topic": old, "id": "m9", "message": "To the old topic"}])
time.sleep(3)
check(not dbx("SELECT 1 FROM tasks WHERE title='To the old topic'"), "the old topic is no longer read")
Bo.put(B + "/api/me/ntfy-inbox", json={"enabled": False})
n = len(stub_log())
time.sleep(3)
check(not [x for x in stub_log()[n:] if r.json()["topic"] in x["path"]], "switched off: not polled any more")

# freelancer-matrix: own
r = Fr.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "url": STUB})
check(r.ok and len(r.json()["topic"]) >= 16, f"freelancer: switch on gives a topic ({r.status_code})")
ftopic = r.json()["topic"]
publish([{"topic": ftopic, "id": "f1", "message": "Frida shares"}])
got = until(lambda: dbx("SELECT created_by FROM tasks WHERE title='Frida shares'"))
check(got and got[0][0] == FID, "freelancer: arrives in the own basket")

print(f"p2142_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
