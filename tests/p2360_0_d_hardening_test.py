#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.360.0 D (#2496) API tests: hardening of calendar, team, forms, knowledge, video and family, own container (start.sh).
Invented names only, addresses @example.com. freelancer-matrix: wiki
 - a public link of a knowledge page is bound to that page: the page in the trash and a new page of the same name -> the
   link does not show the new one (404); the old page restored -> the link works again
 - moving private pages into an organisation leaves their earlier versions behind (the dry run names them)
 - withdrawing an approval request needs the write right: the asker turned into a viewer gets 403, the request stays
 - a public form of a private list: a signed-in stranger sends like a visitor (no author); a signed-in sender whose browser
   sends a foreign Origin without Sec-Fetch-Site is refused (403), without such headers it works
 - the weekly capacity of someone else: only an admin of an organisation the person is in (not the instance admin for a
   person outside; the freelancer sets her own)
 - kid stars: a repeating task ticked twice on one day earns its stars once; reopening the done copy takes them back
 - invitations: the calendar file names only its recipient (not the other external guest); the server's daily limit -> 429;
   an event title from an .ics file is one line
 - a video sign-off: who only views the task does not answer the customer's comment (403), the editor does
usage: p2360_0_d_hardening_test.py <datadir>"""
import email as _em
import email.policy  # noqa: F401  (_em.policy)
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check, sess, until  # noqa: E402  shared helpers (tests/kt.py)
from testclock import now as tnow  # noqa: E402


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def usess(user):
    s = sess(user)
    r = s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
    assert r.ok, (user, r.text)
    return s


def mails(to=None):
    try:
        out = [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []
    return [m for m in out if not to or to in json.dumps(m["to"])]


def ics_of(m):
    msg = _em.message_from_string(m["raw"], policy=_em.policy.default)
    out = ""
    for x in msg.walk():
        if x.get_content_type() == "text/calendar":
            c = x.get_content()
            out += c.decode("utf-8") if isinstance(c, bytes) else c
    return re.sub(r"\r\n[ \t]", "", out)


def stamp_of(text):
    m = re.search(r'name="stamp" value="([^"]+)"', text)
    return m.group(1) if m else ""


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SMTP_HOST=127.0.0.1"
           " -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test"
           " -e KALMIDO_INVITE_MAIL_DAY=1500")  # 2.360.0 R (#2496, review): the server's daily invitation limit is set here
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = usess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = usess("alice")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
if not dbx("SELECT email FROM users WHERE id=?", (ALICE,))[0][0]:
    dbx("UPDATE users SET email='alice@example.com' WHERE id=?", (ALICE,))
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca = usess("bob"), usess("carol")
FID, Fr = freelancer(B, A)

# ================================================================== the wiki: a page link is bound to its page (freelancer)
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Kunde X/Zugang", "body": "Alter Zugang"})
assert r.status_code == 201, r.text
OLD = r.json()["id"]
r = Fr.post(B + "/api/wiki/shares", json={"page_id": OLD, "kind": "link"})
check(r.status_code == 201 and r.json().get("url"), "freelancer: a public link of her own page " + r.text[:200])
TOK = r.json().get("url", "").rsplit("/", 1)[-1]
check(requests.get(B + "/s/w/" + TOK).status_code == 200, "the link opens the page")
check(Fr.delete(B + f"/api/wiki/pages/{OLD}").ok, "the page goes to the trash")
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Kunde X/Zugang", "body": "Neue interne Notiz Pfirsich"})
NEW = r.json().get("id") if r.status_code == 201 else None
check(NEW, "a new page with the same name " + r.text[:200])
p = requests.get(B + "/s/w/" + TOK)
check(p.status_code == 404 and "Pfirsich" not in p.text, f"#2496: the old link does not show the new page of the same name ({p.status_code})")
r = Fr.get(B + f"/api/wiki/pages/{NEW}")
check(r.ok and r.json().get("shares", 0) == 0, "#2496: the new page carries no share mark " + str(r.json().get("shares")))
Fr.delete(B + f"/api/wiki/pages/{NEW}")
check(Fr.post(B + "/api/wiki/restore", json={"ids": [OLD]}).ok, "the old page comes back")
p = requests.get(B + "/s/w/" + TOK)
check(p.status_code == 200 and "Alter Zugang" in p.text, f"#2496: the link shows its own page again ({p.status_code})")

# ================================================================== the wiki: the history stays private when moved into the organisation
r = Bo.post(B + "/api/wiki/pages", json={"space": "private", "path": "Notiz/Umzug", "body": "Passwort 1234 (alt)"})
MV = r.json()["id"]
assert Bo.patch(B + f"/api/wiki/pages/{MV}", json={"body": "bereinigt"}).ok
assert Bo.patch(B + f"/api/wiki/pages/{MV}", json={"body": "bereinigt, zweite Fassung"}).ok
nv = dbx("SELECT COUNT(*) FROM wiki_versions WHERE page_id=?", (MV,))[0][0]
check(nv >= 1, f"earlier versions in the private space ({nv})")
r = Bo.post(B + "/api/wiki/move-space", json={"pages": [MV], "space": "private", "to": f"org:{ORG}", "dest": "", "dry": True})
check(r.ok and r.json().get("versions") == nv and any("earlier version" in x for x in r.json().get("notes", [])),
      "#2496: the dry run names the versions that stay behind " + r.text[:300])
r = Bo.post(B + "/api/wiki/move-space", json={"pages": [MV], "space": "private", "to": f"org:{ORG}", "dest": ""})
check(r.ok and not dbx("SELECT 1 FROM wiki_versions WHERE page_id=?", (MV,)), "#2496: in the organisation no earlier private version " + r.text[:200])
vv = Ca.get(B + f"/api/wiki/pages/{MV}/versions")
check(vv.ok and not any("1234" in json.dumps(x) for x in vv.json().get("versions", [])), "#2496: another member reads no old state")

# ================================================================== approvals: withdrawing needs the write right
L = A.post(B + "/api/lists", json={"name": "Freigaben"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["bob"], "role": "edit"})
T = Bo.post(B + "/api/tasks", json={"title": "Logo", "list_id": L}).json()["id"]
r = Bo.post(B + f"/api/tasks/{T}/approval", json={"action": "request", "approver_id": ALICE})
check(r.ok and r.json().get("approval") == "pending", "bob asks alice for an approval " + r.text[:200])
A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["bob"], "role": "view"})
r = Bo.post(B + f"/api/tasks/{T}/approval", json={"action": "cancel"})
check(r.status_code == 403 and dbx("SELECT approval FROM tasks WHERE id=?", (T,))[0][0] == "pending",
      f"#2496: bob as a viewer cannot withdraw it ({r.status_code})")
A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["bob"], "role": "edit"})
check(Bo.post(B + f"/api/tasks/{T}/approval", json={"action": "cancel"}).ok, "with the write right again he can")

# ================================================================== forms: a stranger is a visitor, a foreign origin is refused
FL = A.post(B + "/api/lists", json={"name": "Anfragen privat", "org_id": None}).json()["id"]
r = A.post(B + f"/api/lists/{FL}/forms", json={"title": "Kontakt", "access": "public"})
check(r.status_code == 201, "a public form of alice's private list " + r.text[:200])
FTOK = r.json()["url"].rsplit("/", 1)[-1]
pg = Ca.get(B + "/f/" + FTOK)
st = stamp_of(pg.text)
check(pg.ok and st, "#2496: carol (signed in, not in the list) gets the visitor's page with its stamp")
time.sleep(3.2)  # FRM_MIN_S: the stamp is valid 3 s after loading (a bot check), nothing to wait for in the server
r = Ca.post(B + "/f/" + FTOK, data={"subject": "Von Carol", "text": "Hallo", "name": "Carol", "stamp": st}, headers=H)
row = dbx("SELECT created_by FROM tasks WHERE list_id=? AND title='Von Carol'", (FL,))
check(r.ok and row and row[0][0] is None, f"#2496: her send is a visitor's (no author) {row}")
r = A.post(B + "/f/" + FTOK, data={"subject": "Fremde Seite", "text": "x"}, headers={**H, "Origin": "https://evil.example"})
check(r.status_code == 403 and not dbx("SELECT 1 FROM tasks WHERE title='Fremde Seite'"), f"#2496: a foreign Origin without Sec-Fetch-Site: 403 ({r.status_code})")
r = A.post(B + "/f/" + FTOK, data={"subject": "Fremder Verweis", "text": "x"}, headers={**H, "Referer": "https://evil.example/page"})
check(r.status_code == 403, f"#2496: a foreign Referer without Origin: 403 ({r.status_code})")
r = A.post(B + "/f/" + FTOK, data={"subject": "Eigene Seite", "text": "x"}, headers={**H, "Origin": B})
check(r.ok and dbx("SELECT created_by FROM tasks WHERE title='Eigene Seite'")[0][0] == ALICE, "the own origin: sent as alice")
# 2.360.0 R (#2496, review): behind a proxy that rewrites Host the page's origin is the proxy's host (X-Forwarded-Host)
r = A.post(B + "/f/" + FTOK, data={"subject": "Hinter Proxy", "text": "x"},
           headers={**H, "Origin": "https://forms.example", "X-Forwarded-Host": "forms.example"})
check(r.ok and dbx("SELECT 1 FROM tasks WHERE title='Hinter Proxy'"), f"#2496 R: the origin of X-Forwarded-Host is the own one ({r.status_code})")
r = A.post(B + "/f/" + FTOK, data={"subject": "Proxy fremd", "text": "x"},
           headers={**H, "Origin": "https://evil.example", "X-Forwarded-Host": "forms.example"})
check(r.status_code == 403, f"#2496 R: a foreign Origin stays refused behind the proxy ({r.status_code})")

# ================================================================== workload: the capacity of someone else
check(A.put(B + f"/api/workload/capacity/{uid['bob']}", json={"hours": 20}).ok, "alice (admin of Alpha) sets bob's capacity")
r = A.put(B + f"/api/workload/capacity/{FID}", json={"hours": 5})
check(r.status_code == 403, f"#2496: the instance admin does not set the freelancer's capacity ({r.status_code})")
check(Fr.put(B + f"/api/workload/capacity/{FID}", json={"hours": 30}).json().get("capacity_h") == 30, "freelancer: her own capacity")
check(Bo.put(B + f"/api/workload/capacity/{uid['carol']}", json={"hours": 1}).status_code == 403, "a member does not set another's")

# ================================================================== kid stars once per task and day
r = A.post(B + "/api/users", json={"username": "kim", "display_name": "Kim", "password": "password123", "kid": True, "parents": [ALICE]})
check(r.ok, "a kid account " + r.text[:200])
KID = r.json()["id"]
KL = A.post(B + "/api/lists", json={"name": "Haushalt", "org_id": None}).json()["id"]
A.put(B + f"/api/lists/{KL}/members", json={"user_id": KID, "role": "edit"})
Ki = sess("kim")
Ki.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})  # a kid may not change everything
KT = A.post(B + "/api/tasks", json={"title": "Tisch decken", "list_id": KL, "assignee_id": KID, "stars": 2, "due": tnow().date().isoformat(),
                                    "repeat": "FREQ=DAILY"}).json()["id"]


def stars():
    return Ki.get(B + "/api/family/kids").json()["kids"][0]["stars"]


check(Ki.post(B + f"/api/tasks/{KT}/complete", json={}).ok and stars() == 2, f"the kid ticks it: +2 ({stars()})")
check(Ki.post(B + f"/api/tasks/{KT}/complete", json={}).ok and stars() == 2, f"#2496: ticked again (the next date) the same day: still 2 ({stars()})")
copies = [x[0] for x in dbx("SELECT id FROM tasks WHERE list_id=? AND title='Tisch decken' AND status=2 ORDER BY id", (KL,))]
check(len(copies) == 2, f"two done copies {copies}")
if copies:
    Ki.post(B + f"/api/tasks/{copies[0]}/reopen", json={})
    check(stars() == 0, f"#2496: reopening the done copy takes its stars back ({stars()})")
    # 2.360.0 R (#2496, review): reopening a done copy never takes the stars of another task done at the same moment
    KX = A.post(B + "/api/tasks", json={"title": "Zimmer aufraeumen", "list_id": KL, "assignee_id": KID, "stars": 3}).json()["id"]
    check(Ki.post(B + f"/api/tasks/{KX}/complete", json={}).ok and stars() == 3, f"another task: +3 ({stars()})")
    cat = dbx("SELECT completed_at FROM tasks WHERE id=?", (copies[1],))[0][0]
    dbx("UPDATE kid_stars SET at=? WHERE task_id=?", (cat, KX))  # done in the same second as the second copy
    Ki.post(B + f"/api/tasks/{copies[1]}/reopen", json={})
    check(stars() == 3, f"#2496 R: reopening the copy (no stars of its own) leaves the other task's stars ({stars()})")

# ================================================================== invitations
D = (date.today() + timedelta(days=5)).isoformat()
CAL = A.post(B + "/api/evcals", json={"name": "Alice Termine", "org_id": None}).json()["id"]
r = A.post(B + "/api/events", json={"cal_id": CAL, "title": "Workshop", "start": f"{D}T10:00", "end": f"{D}T11:00", "tz": "Europe/Berlin",
                                    "send_invites": True, "attendees": [{"email": "gast.eins@example.com", "name": "Gast Eins"},
                                                                        {"email": "gast.zwei@example.com", "name": "Gast Zwei"}]})
check(r.status_code == 201, "an event with two external guests " + r.text[:200])
m = until(lambda: mails("gast.eins@example.com"), 10)
ics = ics_of(m[0]) if m else ""
check("mailto:gast.eins@example.com" in ics and "gast.zwei" not in ics, "#2496: the calendar file names only its recipient " + ics[-400:])
day = tnow().date().isoformat()  # 2.360.0 R (#2496, review): the local day, like the person's counter (was the UTC day)
dbx("INSERT INTO mail_counts(k,day,n) VALUES('i:evinvite',?,1500) ON CONFLICT(k) DO UPDATE SET n=1500, day=excluded.day", (day,))
r = A.post(B + "/api/events", json={"cal_id": CAL, "title": "Zu viel", "start": f"{D}T12:00", "end": f"{D}T13:00", "tz": "Europe/Berlin",
                                    "send_invites": True, "attendees": [{"email": "gast.drei@example.com"}]})
check(r.status_code == 429 and "server" in r.text, f"#2496: the server's daily limit of invitation mails (R: KALMIDO_INVITE_MAIL_DAY=1500) ({r.status_code} {r.text[:120]})")
dbx("DELETE FROM mail_counts WHERE k='i:evinvite'")
ICS = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Example//EN\r\nBEGIN:VEVENT\r\nUID:p2360d-1@example.com\r\nDTSTAMP:20261001T000000Z\r\n"
       f"DTSTART:{D.replace('-', '')}T090000Z\r\nDTEND:{D.replace('-', '')}T100000Z\r\nSUMMARY:Zeile eins\\nZeile zwei\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
r = A.post(B + f"/api/evcals/{CAL}/import", files={"file": ("x.ics", ICS.encode(), "text/calendar")})
t = dbx("SELECT title FROM events WHERE cal_id=? AND uid='p2360d-1@example.com'", (CAL,))
check(r.ok and t and "\n" not in t[0][0] and t[0][0] == "Zeile eins, Zeile zwei", f"#2496: an imported title is one line {t} {r.text[:120]}")

# ================================================================== video sign-off: a viewer does not answer the customer
VL = A.post(B + "/api/lists", json={"name": "Filme", "kind": "project"}).json()["id"]
A.put(B + f"/api/lists/{VL}/members", json={"user_id": uid["bob"], "role": "view"})
VT = A.post(B + "/api/tasks", json={"title": "Schnitt", "list_id": VL}).json()["id"]
r = A.post(B + "/api/videos", json={"task_id": VT, "title": "Film", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
check(r.ok, "a video sign-off " + r.text[:200])
VID = r.json()["id"]
so = A.post(B + f"/api/videos/{VID}/signoff", json={})
QT = so.json()["url"].split("/s/q/")[1] if so.ok else ""
pg = requests.get(B + "/s/q/" + QT)
fk = re.search(r'name="f" value="([^"]+)"', pg.text)
vk = re.search(r'name="v" value="([^"]+)"', pg.text)
r = requests.post(B + f"/s/q/{QT}/comments", data={"f": fk.group(1) if fk else "", "v": vk.group(1) if vk else "", "name": "Kundin Example",
                                                     "text": "Bitte heller"}, allow_redirects=False)
cc = dbx("SELECT id FROM video_comments WHERE review_id=? AND ext_name<>''", (VID,))
check(r.status_code in (200, 303) and cc, f"the customer comments through the link ({r.status_code})")
if cc:
    r = Bo.post(B + f"/api/videos/{VID}/comments", json={"body": "Antwort vom Leser", "parent_id": cc[0][0]})
    check(r.status_code == 403 and not dbx("SELECT 1 FROM video_comments WHERE body='Antwort vom Leser'"),
          f"#2496: bob (only views) does not answer the customer ({r.status_code})")
    check(Bo.post(B + f"/api/videos/{VID}/comments", json={"body": "Interne Notiz"}).ok, "bob still comments internally")
    check(A.post(B + f"/api/videos/{VID}/comments", json={"body": "Wird gemacht", "parent_id": cc[0][0]}).ok, "alice (editor) answers")

# ================================================================== 2.360.0 R (#2496, review): booking names
# (the server's own pattern, run in its container: the public booking post is limited to a few per minute)
NAMES = {"Dr.med. Example": False, "St.Pauli Film": False, "Hans-J.Beispiel": False, "Anna Example": False,
         "Pay at evil.example now": True, "see https://evil.example": True, "x.co.uk": True, "www.example": True, "a@example.com": True}
r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", "import json, sys\nfrom kalmido.calendars.apptbook import APB_NAME_BAD\n"
                    "print(json.dumps({n: bool(APB_NAME_BAD.search(n)) for n in json.loads(sys.argv[1])}))", json.dumps(list(NAMES))],
                   capture_output=True, text=True, timeout=120)
got = json.loads((r.stdout or "{}").strip().splitlines()[-1] if r.stdout.strip() else "{}")
check(got == NAMES, f"#2496 R: names with a dot are names, links / addresses are refused {got} {r.stderr[-300:]}")

print(f"p2360_0_d_hardening: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
