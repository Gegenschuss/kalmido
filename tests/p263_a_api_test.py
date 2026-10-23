#!/usr/bin/env python3
"""2.63.0 API tests (part A).
 - #1513 the public report form: a form's ttype / files / portal (validation, portal turns ask_email on); a visitor's page
   with the signed time stamp, the file field (multipart) and the required e-mail; sending too soon, without / with a forged
   stamp = the form again; a report becomes a task with the form's type, a portal_tickets row in the list's space (address
   and token sealed), the status link on the thank-you page and in ONE mail; the file stored (an executable ending gets
   .txt, counted against the list owner) and readable only for people of the list; 'task_added' carries portal and ttype;
   more than 5 links refused, a too large file refused, a second address in the field refused; 5 reports per address, form
   and hour; at most 3 confirmations per address and hour; a private list's form: the ticket in the owner's space; a
   signed-in member of the organisation gets no status link; a form without status link stays as it was
tenant-matrix: org
usage: p263_a_api_test.py <datadir>"""
import email as _em
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

from kt import FAILS, OKS, check, sess, B, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def mails(to=None):
    try:
        out = [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []
    return [m for m in out if not to or to in json.dumps(m["to"])]


def body_of(m):
    msg = _em.message_from_string(m["raw"])
    return "".join(x.get_payload(decode=True).decode() for x in msg.walk() if x.get_content_type() == "text/plain"), str(msg["Subject"])


def events(aid):
    return [json.loads(r[0]) for r in dbx("SELECT payload FROM agent_events WHERE agent_id=? ORDER BY id", (aid,))]


def png(w=4, h=4):
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def stamp_of(text):
    m = re.search(r'name="stamp" value="([^"]+)"', text)
    return m.group(1) if m else ""


def task_by(title):
    r = dbx("SELECT id, ttype, content, list_id, created_by FROM tasks WHERE title=?", (title,))
    return r[0] if r else None


# 2.149.0 (#2513): the minute of the rate limits shortened to RATE_S (test containers only) instead of waiting 61 s per batch
RATE_S = 10
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025"
           " -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test" + f" -e KALMIDO_TEST_RATE_WINDOW_S={RATE_S}")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,agents,clients,workload,forms"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
A.patch(B + "/api/admin/settings", json={"public_links": True})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
BOB = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
ORG2 = dbx("INSERT INTO orgs(name,icon,created_at) VALUES('Other','','2026-10-01T00:00:00Z') RETURNING id")[0][0]
dbx("DELETE FROM org_members WHERE user_id=?", (CAROL,))
dbx("INSERT INTO org_members(org_id,user_id) VALUES(?,?)", (ORG2, CAROL))
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
AG = r.json()["id"]
FL = A.post(B + "/api/lists", json={"name": "Support", "org_id": ORG}).json()["id"]
PL = A.post(B + "/api/lists", json={"name": "Private support", "org_id": None}).json()["id"]
A.put(B + f"/api/lists/{FL}/members", json={"user_id": AG, "role": "edit"})
A.put(B + f"/api/lists/{FL}/members", json={"user_id": BOB, "role": "edit"})
A.patch(B + f"/api/lists/{FL}", json={"listen_agent_ids": [AG], "tickets": True})

# ================================================================== the settings
r = A.post(B + f"/api/lists/{FL}/forms", json={"title": "Bug report", "access": "public", "ttype": "bug", "files": True, "portal": True, "ask_email": False})
F = r.json()
check(r.status_code == 201 and F["ttype"] == "bug" and F["files"] is True and F["portal"] is True and F["ask_email"] is True,
      "a report form: type bug, a file, a status link; the status link turns the e-mail on " + r.text[:300])
check(A.post(B + f"/api/lists/{FL}/forms", json={"title": "x", "ttype": "epic"}).status_code == 400, "ttype: only the ticket types")
check(A.post(B + f"/api/lists/{FL}/forms", json={"title": "x", "files": "yes"}).status_code == 400, "files: a boolean")
r = A.post(B + f"/api/lists/{FL}/forms", json={"title": "Wishes", "access": "public", "ttype": "feature", "ask_email": False})
FW = r.json()
check(r.status_code == 201 and FW["portal"] is False and FW["files"] is False and FW["ask_email"] is False, "a form without status link stays as before")
r = A.patch(B + f"/api/forms/{FW['id']}", json={"ask_email": False})
check(r.ok and r.json()["ask_email"] is False, "e-mail off while there is no status link")
check(Bo.patch(B + f"/api/forms/{F['id']}", json={"portal": False}).status_code == 403, "only owner / list admins change it")
r = A.patch(B + f"/api/forms/{F['id']}", json={"ask_email": False})
check(r.ok and r.json()["ask_email"] is True, "with the status link on, the e-mail stays on")
tok = F["url"].rsplit("/", 1)[1]
tokw = FW["url"].rsplit("/", 1)[1]

# ================================================================== the page
anon = sess()
p = anon.get(B + "/f/" + tok)
st = stamp_of(p.text)
# 2.81.0 (#1866): a stamp counts once -> every send below that passes the stamp check takes a page of its own
sts = [stamp_of(anon.get(B + "/f/" + tok).text) for _ in range(12)]
check(p.ok and st and 'enctype="multipart/form-data"' in p.text and 'name="file"' in p.text and re.search(r'name="email"[^>]*required', p.text)
      and "<script" not in p.text, "the page: a stamp, a file field (multipart), the e-mail required, no scripts")
check('name="file"' not in anon.get(B + "/f/" + tokw).text, "a form without files: no file field")
# batch 1 (at most 6 sends per address and minute)
p = anon.post(B + "/f/" + tok, data={"subject": "Too fast", "email": "eve@example.com", "stamp": st})
check(p.status_code == 400 and "once more" in p.text and stamp_of(p.text) and not task_by("Too fast"), "sent sooner than 3 s: the form again, nothing created")
p = anon.post(B + "/f/" + tok, data={"subject": "No stamp", "email": "eve@example.com"})
check(p.status_code == 400 and "once more" in p.text and not task_by("No stamp"), "no stamp: the form again")
time.sleep(3.3)
p = anon.post(B + "/f/" + tok, data={"subject": "Forged", "email": "eve@example.com", "stamp": str(int(time.time()) - 60) + ".0123456789abcdef0123456789abcdef"})
check(p.status_code == 400 and not task_by("Forged"), "a forged stamp: the form again")
n0 = len(events(AG))
st_used = sts.pop()
p = anon.post(B + "/f/" + tok, data={"subject": "App crashes", "text": "On start.", "name": "Eve", "email": "Eve@Example.com", "stamp": st_used},
              files={"file": ("shot.png", png(), "text/html")})
link = re.search(r'value="(https://kalmido\.example/p/[A-Za-z0-9_-]+)"', p.text)
check(p.ok and link and "We have also sent the link to Eve@Example.com" in p.text, "sent: the status link on the thank-you page, the mail mentioned " + p.text[-600:])
t = task_by("App crashes")
check(t and t[1] == "bug" and t[4] is None and "On start." in t[2] and "status link" in t[2], "a task of type bug, without a creator, the sender in the notes " + str(t))
pt = dbx("SELECT org_id, owner_id, form_id, name, email, email_hash, token, token_hash, notify FROM portal_tickets WHERE task_id=?", (t[0],)) if t else []
ptok = link.group(1).rsplit("/", 1)[1] if link else "-"
check(pt and pt[0][0] == ORG and pt[0][1] is None and pt[0][2] == F["id"] and pt[0][3] == "Eve" and pt[0][5] and pt[0][8] == 1
      and "eve@example.com" not in (pt[0][4] or "").lower() and ptok not in pt[0][6] and len(pt[0][7]) >= 40,
      "a ticket in the organisation, address and token sealed " + str(pt))
act = dbx("SELECT data FROM activity WHERE task_id=? AND kind='created'", (t[0],)) if t else []
check(act and json.loads(act[0][0]).get("portal") == 1, "history: created by the form, with a status link")
att = dbx("SELECT id, name, mime, user_id, size FROM attachments WHERE task_id=?", (t[0],)) if t else []
check(att and att[0][1] == "shot.png" and att[0][2] == "image/png" and att[0][3] == 1, "the file: kept, its type from the name (not the sender's), counted against the owner " + str(att))
if att:
    check(A.get(B + f"/api/attachments/{att[0][0]}").content == png(), "the list's owner reads the file")
    check(Ca.get(B + f"/api/attachments/{att[0][0]}").status_code in (403, 404), "another organisation: no file")
    check(anon.get(B + f"/api/attachments/{att[0][0]}").status_code in (401, 403, 404), "without an account: no file")
ev = [e for e in events(AG)[n0:] if e["event"] == "task_added"]
check(ev and ev[0]["data"].get("source") == "form" and ev[0]["data"].get("portal") is True and ev[0]["data"].get("ttype") == "bug",
      "the agent: task_added with source form, portal, ttype " + json.dumps(ev[:1])[:400])
for _ in range(30):
    if mails("eve@example.com") or mails("Eve@Example.com"):
        break
    time.sleep(0.3)
m = mails("Example.com")
mb = body_of(m[0]) if m else ("", "")
check(len(m) == 1 and mb[1] == "Your report: App crashes" and link and link.group(1) in mb[0] and "anyone who has it" in mb[0],
      "one confirmation mail with the link " + str(mb)[:400])
p = anon.post(B + "/f/" + tok, data={"subject": "Links", "text": " ".join(f"http://x{i}.example" for i in range(6)), "email": "eve@example.com", "stamp": sts.pop()})
check(p.status_code == 400 and "at most 5 links" in p.text and not task_by("Links"), "more than 5 links: refused with a hint")
p = anon.post(B + "/f/" + tok, data={"subject": "Script file", "email": "eve@example.com", "stamp": sts.pop()}, files={"file": ("run.sh", b"echo hi\n", "text/plain")})
t2 = task_by("Script file")
att2 = dbx("SELECT name FROM attachments WHERE task_id=?", (t2[0],)) if t2 else []
check(p.ok and att2 and att2[0][0] == "run.sh.txt", "an executable ending gets .txt " + str(att2))
time.sleep(RATE_S + 1)  # 2.149.0 (#2513): a new rate window
# batch 2
p = anon.post(B + "/f/" + tok, data={"subject": "No address", "stamp": sts.pop()})
check(p.status_code == 400 and "e-mail address" in p.text and not task_by("No address"), "the status link needs an address")
p = anon.post(B + "/f/" + tok, data={"subject": "Two addresses", "email": "a@x.example,b@y.example", "stamp": sts.pop()})
check(p.status_code == 400 and not task_by("Two addresses"), "one address only")
codes = [anon.post(B + "/f/" + tok, data={"subject": f"Again {i}", "email": "eve@example.com", "stamp": sts.pop()}).status_code for i in range(4)]
check(codes == [200, 200, 200, 429], "5 reports per address, form and hour " + str(codes))
for _ in range(20):
    if len(mails("xample.com")) >= 3:
        break
    time.sleep(0.3)
time.sleep(1)
check(len(mails("xample.com")) == 3, "at most 3 confirmations per address and hour " + str(len(mails("xample.com"))))
pts = dbx("SELECT COUNT(*) FROM portal_tickets WHERE form_id=?", (F["id"],))[0][0]
check(pts == 5, "every report a ticket " + str(pts))
time.sleep(RATE_S + 1)  # 2.149.0 (#2513): a new rate window
# batch 3
p = anon.post(B + "/f/" + tok, data={"subject": "Big", "email": "big@example.com", "stamp": sts.pop()}, files={"file": ("big.bin", b"0" * (10 * 1024 * 1024 + 10), "application/octet-stream")})
check(p.status_code in (400, 413) and not task_by("Big"), "a file over 10 MB: refused " + str(p.status_code))
r = A.post(B + f"/api/lists/{PL}/forms", json={"title": "Private", "access": "public", "portal": True})
tokp = r.json()["url"].rsplit("/", 1)[1]
stp = stamp_of(anon.get(B + "/f/" + tokp).text)
check(stp and stp != st, "the stamp belongs to its form")
p = anon.post(B + "/f/" + tokp, data={"subject": "Wrong stamp", "email": "pat@example.com", "stamp": st})
check(p.status_code == 400 and not task_by("Wrong stamp"), "another form's stamp: refused")
time.sleep(3.3)
p = anon.post(B + "/f/" + tokp, data={"subject": "Private report", "email": "pat@example.com", "stamp": stp})
t3 = task_by("Private report")
pt3 = dbx("SELECT org_id, owner_id FROM portal_tickets WHERE task_id=?", (t3[0],)) if t3 else []
check(p.ok and "/p/" in p.text and pt3 and pt3[0][0] is None and pt3[0][1] == 1, "a private list: the ticket in the owner's space " + str(pt3))
p = Bo.post(B + "/f/" + tok, data={"subject": "Bob reports", "text": "x"}, headers={"Sec-Fetch-Site": "same-origin"})
t4 = task_by("Bob reports")
check(p.ok and "/p/" not in p.text and t4 and t4[1] == "bug" and t4[4] == BOB and not dbx("SELECT 1 FROM portal_tickets WHERE task_id=?", (t4[0],)),
      "a signed-in member: a task of the type, no status link " + str(t4))
p = anon.post(B + "/f/" + tokw, data={"subject": "A wish", "stamp": stamp_of(anon.get(B + "/f/" + tokw).text)})
check(p.status_code == 400, "the stamp counts on every visitor form")
time.sleep(3.3)
pw = anon.get(B + "/f/" + tokw)
time.sleep(3.3)
p = anon.post(B + "/f/" + tokw, data={"subject": "A wish", "stamp": stamp_of(pw.text)}, files={"file": ("x.png", png(), "image/png")})
t5 = task_by("A wish")
check(p.ok and "/p/" not in p.text and t5 and t5[1] == "feature" and not dbx("SELECT 1 FROM attachments WHERE task_id=?", (t5[0],))
      and not dbx("SELECT 1 FROM portal_tickets WHERE task_id=?", (t5[0],)), "a form without status link / files: a feature task, no file, no ticket")
check(Ca.get(B + "/f/" + tok).ok, "the public form also opens for another organisation")
# 2.81.0 (#1866): batch 4: a used stamp is refused; at most 50 confirmation mails per form and day
time.sleep(RATE_S + 1)  # 2.149.0 (#2513): a new rate window
p = anon.post(B + "/f/" + tok, data={"subject": "Replayed", "email": "re@example.com", "stamp": st_used})
check(p.status_code == 400 and "once more" in p.text and not task_by("Replayed"), "#1866: a stamp that was sent once is refused")
day = time.strftime("%Y-%m-%d", time.gmtime())
dbx("INSERT INTO mail_counts(k,day,n) VALUES(?,?,50) ON CONFLICT(k) DO UPDATE SET n=50, day=excluded.day RETURNING k", (f"fm:{F['id']}", day))
p = anon.post(B + "/f/" + tok, data={"subject": "Day limit", "email": "day@example.com", "stamp": sts.pop()})
check(p.ok and "/p/" in p.text and "We have also sent" not in p.text and task_by("Day limit"), "#1866: over the form's daily mails: the report is kept, no mail")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
