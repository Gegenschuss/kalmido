#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.380 H API tests (offline queue rest, guest list of an event, pictures in shared pages, the organisation move of polls
and bookmarks), own container (start.sh) with the mail stub and the fake web server of the bookmarks. Invented names only,
addresses @example.com.
freelancer-matrix: wiki
 - #3387: an idempotency key lives 14 days: a write sent again after 10 days gets its stored answer back (nothing changes
   twice), a key older than 14 days goes when the person claims a new one
 - #3392: an event's switch guests_visible (default off): on, the invitation to an external guest names all guests; off,
   only the recipient; not a boolean = 400; the calendar export carries X-KALMIDO-GUESTS-VISIBLE:TRUE only for the event
   with the switch on; a calendar file with the line sets it, one without the line leaves it as it is, FALSE turns it off;
   the invitation itself never carries the line; a person without an organisation sets it the same way
 - #2356: a page share shows a file store picture embedded in the page only with its switch "images" (default off): the
   public link and a guest (person share) see the picture through a route under the share; never a file that is no
   picture, never a picture that is not embedded in the page, never after the switch went off or the picture went to the
   trash; images not a boolean = 400 (as a person without an organisation)
 - #2398: the organisation export carries the organisation's polls (options, votes) and bookmarks (with the picture);
   imported into an empty organisation they come with a new poll link (the old one is dead, the report says so), the votes
   name the new options, the bookmark's picture opens; the person's own poll / bookmark (no organisation) stays out
usage: p2380r_h_api_test.py <datadir>"""
import base64
import email as _em
import email.policy  # noqa: F401  (_em.policy)
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib
from datetime import date, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess, su_get, until  # noqa: E402
from testclock import now as tnow  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
FEED = "http://127.0.0.1:8098/"


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


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


def png(w=2, h=2):
    raw = b"".join(b"\x00" + b"\x80\x40\xc0" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def put_feed(name, data):
    os.makedirs(os.path.join(DATA, "feeds"), exist_ok=True)
    with open(os.path.join(DATA, "feeds", name), "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


def upload(s, name, data, mime, **form):
    r = s.post(B + "/api/files/upload", data=form, files={"file": (name, data, mime)})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def iso_s(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")



def imp_upload(s, data, name="alpha.kalmido-export"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def imp_wait(s, iid, secs=240):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


# ---------------------------------------------------------------- server, people
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SMTP_HOST=127.0.0.1"
           " -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test"
           f" -e KALMIDO_SECRET_KEY={KEY} -e KALMIDO_BOOKMARK_ALLOW_HOSTS=127.0.0.1:8098")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
for f in ("stub_mail.py", "fake_feeds.py"):
    shutil.copy(os.path.join(N, f), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/" + f])
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A = usess("alice")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
if not one("SELECT email FROM users WHERE id=?", (ALICE,)):
    dbx("UPDATE users SET email='alice@example.com' WHERE id=?", (ALICE,))
orgs = {}
for name in ("Alpha Team", "Gamma Leer"):
    r = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": ALICE})
    assert r.status_code == 201, r.text
    orgs[name] = r.json()["id"]
ORG, ORG2 = orgs["Alpha Team"], orgs["Gamma Leer"]
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca = usess("bob"), usess("carol")
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
D = (date.today() + timedelta(days=5)).isoformat()
PNG = png()

# ================================================================== #3387: idempotency keys live 14 days
L = A.post(B + "/api/lists", json={"name": "Idem"}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Null", "list_id": L}).json()["id"]
K1 = {"Idempotency-Key": "p2380h-k1"}
r = A.patch(B + f"/api/tasks/{T}", json={"title": "Eins"}, headers=K1)
check(r.ok and r.json().get("title") == "Eins", "#3387: a change with its key " + r.text[:120])
check(one("SELECT COUNT(*) FROM idem_keys WHERE user_id=? AND k='p2380h-k1'", (ALICE,)) == 1, "#3387: the key is kept")
dbx("UPDATE idem_keys SET created_at=? WHERE user_id=? AND k='p2380h-k1'", (iso_s(tnow() - timedelta(days=10)), ALICE))
dbx("INSERT INTO idem_keys(user_id,k,method,path,status,body,created_at) VALUES(?,?,?,?,?,?,?)",
    (ALICE, "p2380h-old", "PATCH", f"/api/tasks/{T}", 200, "{}", iso_s(tnow() - timedelta(days=15))))
r = A.patch(B + f"/api/tasks/{T}", json={"title": "Zwei"}, headers={"Idempotency-Key": "p2380h-k2"})
check(r.ok and r.json().get("title") == "Zwei", "#3387: another change with a new key (the old keys are tidied now)")
check(one("SELECT COUNT(*) FROM idem_keys WHERE user_id=? AND k='p2380h-old'", (ALICE,)) == 0, "#3387: a key older than 14 days went")
r = A.patch(B + f"/api/tasks/{T}", json={"title": "Eins"}, headers=K1)
check(r.ok and r.headers.get("Idempotent-Replayed") == "true", f"#3387: the change sent again after 10 days gets its answer back "
      f"({r.status_code} {r.headers.get('Idempotent-Replayed')})")
check(A.get(B + f"/api/tasks/{T}").json().get("title") == "Zwei", "#3387: and changes nothing a second time")
# 2.380 review: the keys of one person are capped (IDEM_MAX_KEYS 5000), the oldest go first
dbx("INSERT INTO idem_keys(user_id,k,method,path,status,body,created_at) SELECT ?, 'p2380h-f' || g, 'PATCH', '/x', 200, '{}', ? "
    "FROM generate_series(1, 5000) g", (ALICE, iso_s(tnow() - timedelta(days=1))))
r = A.patch(B + f"/api/tasks/{T}", json={"title": "Zwei"}, headers={"Idempotency-Key": "p2380h-k3"})
check(r.ok and one("SELECT COUNT(*) FROM idem_keys WHERE user_id=?", (ALICE,)) == 5000
      and one("SELECT COUNT(*) FROM idem_keys WHERE user_id=? AND k='p2380h-k1'", (ALICE,)) == 0
      and one("SELECT COUNT(*) FROM idem_keys WHERE user_id=? AND k='p2380h-k3'", (ALICE,)) == 1,
      "#3387 review: at most 5000 keys per person, the oldest went, the new one stays")

# ================================================================== #3392: the guest list of an event
CAL = A.post(B + "/api/evcals", json={"name": "Alice Termine", "org_id": None}).json()["id"]


def ev(title, guests, **kw):
    return A.post(B + "/api/events", json={"cal_id": CAL, "title": title, "start": f"{D}T10:00", "end": f"{D}T11:00", "tz": "Europe/Berlin",
                                           "send_invites": True, "attendees": [{"email": g, "name": g.split("@")[0]} for g in guests], **kw})


r = ev("Workshop offen", ["gv.eins@example.com", "gv.zwei@example.com"], guests_visible=True)
check(r.status_code == 201 and r.json().get("guests_visible") is True, "#3392: an event with the guest list visible " + r.text[:200])
E1 = r.json().get("id")
m = until(lambda: mails("gv.eins@example.com"), 15)
ics = ics_of(m[0]) if m else ""
check("mailto:gv.eins@example.com" in ics and "mailto:gv.zwei@example.com" in ics, "#3392: the invitation names every guest " + ics[-500:])
check("X-KALMIDO-GUESTS-VISIBLE" not in ics, "#3392: the invitation does not carry the switch")
r = ev("Workshop still", ["off.eins@example.com", "off.zwei@example.com"])
check(r.status_code == 201 and r.json().get("guests_visible") is False, "#3392: default off " + r.text[:200])
E2 = r.json().get("id")
m = until(lambda: mails("off.eins@example.com"), 15)
ics = ics_of(m[0]) if m else ""
check("mailto:off.eins@example.com" in ics and "off.zwei" not in ics, "#3392: off = the invitation names only its recipient (as since 2.360)")
check(A.patch(B + f"/api/events/{E2}", json={"guests_visible": "yes"}).status_code == 400, "#3392: not a boolean = 400")
check(A.get(B + f"/api/events/{E1}").json().get("guests_visible") is True and A.get(B + f"/api/events/{E2}").json().get("guests_visible") is False,
      "#3392: the API shows the switch")
ex = A.get(B + f"/api/evcals/{CAL}/export.ics").text
check(ex.count("X-KALMIDO-GUESTS-VISIBLE:TRUE") == 1, "#3392: the calendar file carries the line only for the event with the switch on")


def ics_file(title, line=None):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Example//EN\r\nBEGIN:VEVENT\r\nUID:p2380h-gv@example.com\r\nDTSTAMP:20261001T000000Z\r\n"
            f"DTSTART:{D.replace('-', '')}T090000Z\r\nDTEND:{D.replace('-', '')}T100000Z\r\nSUMMARY:{title}\r\n"
            + (f"X-KALMIDO-GUESTS-VISIBLE:{line}\r\n" if line else "") + "END:VEVENT\r\nEND:VCALENDAR\r\n").encode()


def imp(title, line=None):
    r = A.post(B + f"/api/evcals/{CAL}/import", files={"file": ("x.ics", ics_file(title, line), "text/calendar")})
    got = dbx("SELECT title, guests_visible, extra FROM events WHERE cal_id=? AND uid='p2380h-gv@example.com' AND deleted_at IS NULL", (CAL,))
    return r, (got[0] if got else None)


r, g = imp("Aus Datei", "TRUE")
check(r.ok and g and g[1] == 1 and "GUESTS-VISIBLE" not in (g[2] or ""), f"#3392: a calendar file with the line turns it on {g} {r.text[:120]}")
r, g = imp("Aus Datei, geaendert")
check(r.ok and g and g[0] == "Aus Datei, geaendert" and g[1] == 1, f"#3392: a file without the line leaves the switch as it is {g}")
r, g = imp("Aus Datei, aus", "FALSE")
check(r.ok and g and g[1] == 0, f"#3392: FALSE turns it off {g}")
FCAL = Fr.post(B + "/api/evcals", json={"name": "Freie Termine", "org_id": None}).json()["id"]
r = Fr.post(B + "/api/events", json={"cal_id": FCAL, "title": "Kundentermin", "start": f"{D}T15:00", "end": f"{D}T16:00", "tz": "Europe/Berlin",
                                     "guests_visible": True, "attendees": [{"email": "kunde.eins@example.com"}]})
check(r.status_code == 201 and r.json().get("guests_visible") is True, "#3392: without an organisation the same " + r.text[:200])

# ================================================================== #2356: pictures of the file store in shared pages (freelancer)
IMG = upload(Fr, "plan.png", PNG, "image/png", space="private")
TXT = upload(Fr, "notiz.txt", b"geheime Notiz", "text/plain", space="private")
IMG2 = upload(Fr, "anderes.png", png(3, 3), "image/png", space="private")
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Kunde Y/Plan",
                                         "body": f"# Plan\n\n![Der Plan](/api/files/nodes/{IMG}/content)\n\n![Notiz](/api/files/nodes/{TXT}/content)\n\n```\n![Code](/api/files/nodes/{IMG2}/content)\n```\n\n`![Inline](/api/files/nodes/{IMG2}/content)`\n"})
assert r.status_code == 201, r.text
PID = r.json()["id"]
check(Fr.post(B + "/api/wiki/shares", json={"page_id": PID, "kind": "link", "images": "ja"}).status_code == 400, "#2356: images not a boolean = 400")
r = Fr.post(B + "/api/wiki/shares", json={"page_id": PID, "kind": "link"})
check(r.status_code == 201 and r.json().get("images") is False, "#2356: a link without the switch (default off) " + r.text[:200])
T0 = r.json().get("url", "").rsplit("/", 1)[-1]
p = requests.get(B + "/s/w/" + T0)
check(p.ok and "/img/" not in p.text and "<img" not in p.text, "#2356: off = no picture on the public page")
check(requests.get(B + f"/s/w/{T0}/img/{PID}/{IMG}").status_code == 404, "#2356: off = the picture route answers 404")
r = Fr.post(B + "/api/wiki/shares", json={"page_id": PID, "kind": "link", "images": True})
check(r.status_code == 201 and r.json().get("images") is True, "#2356: a link with the switch " + r.text[:200])
S1, T1 = r.json().get("id"), r.json().get("url", "").rsplit("/", 1)[-1]
p = requests.get(B + "/s/w/" + T1)
check(p.ok and f'src="/s/w/{T1}/img/{PID}/{IMG}"' in p.text, "#2356: the public page shows the picture " + p.text[-400:])
check(f"/{TXT}" not in p.text and "geheime" not in p.text, "#2356: a file that is no picture stays hidden")
q = requests.get(B + f"/s/w/{T1}/img/{PID}/{IMG}")
check(q.ok and q.content == PNG and q.headers.get("Content-Type", "").startswith("image/png") and "nosniff" in q.headers.get("X-Content-Type-Options", "")
      and "no-store" in q.headers.get("Cache-Control", ""), f"#2356: the picture comes through the link ({q.status_code} {q.headers.get('Content-Type')})")
check(requests.get(B + f"/s/w/{T1}/img/{PID}/{TXT}").status_code == 404, "#2356: the text file never comes through the route")
check(requests.get(B + f"/s/w/{T1}/img/{PID}/{IMG2}").status_code == 404, "#2356: a picture only named in code (not embedded) never comes")
check(requests.get(B + f"/s/w/{T0}x/img/{PID}/{IMG}").status_code in (404, 410), "#2356: an unknown link: nothing")
# a guest (person share by e-mail address) with the switch
r = Fr.post(B + "/api/wiki/shares", json={"page_id": PID, "kind": "person", "email": "bob@example.com", "images": True})
check(r.ok, "#2356: shared with bob, pictures on " + r.text[:160])
g = Bo.get(B + f"/api/wiki/shared/pages/{PID}")
check(g.ok and f"/api/wiki/shared/pages/{PID}/img/{IMG}" in g.json().get("html", ""), "#2356: the guest sees the picture " + g.text[:300])
q = Bo.get(B + f"/api/wiki/shared/pages/{PID}/img/{IMG}")
check(q.ok and q.content == PNG, f"#2356: the guest's picture route ({q.status_code})")
check(Bo.get(B + f"/api/wiki/shared/pages/{PID}/img/{TXT}").status_code == 404, "#2356: the guest never gets the text file")
check(Ca.get(B + f"/api/wiki/shared/pages/{PID}/img/{IMG}").status_code == 404, "#2356: somebody the page is not shared with: 404")
# the switch goes off
check(Fr.patch(B + f"/api/wiki/shares/{S1}", json={"images": False}).ok, "#2356: the switch goes off")
check(requests.get(B + f"/s/w/{T1}/img/{PID}/{IMG}").status_code == 404 and "<img" not in requests.get(B + "/s/w/" + T1).text,
      "#2356: off again = the picture is gone from the link")
check(Fr.patch(B + f"/api/wiki/shares/{S1}", json={"images": True}).ok and requests.get(B + f"/s/w/{T1}/img/{PID}/{IMG}").ok, "#2356: on again")
# the picture goes to the trash: the sharer cannot see it any more
check(Fr.delete(B + f"/api/files/nodes/{IMG}").ok, "the picture goes to the trash")
check(requests.get(B + f"/s/w/{T1}/img/{PID}/{IMG}").status_code == 404 and Bo.get(B + f"/api/wiki/shared/pages/{PID}/img/{IMG}").status_code == 404,
      "#2356: a picture in the trash is never shown")

# ================================================================== #2398: polls and bookmarks move with the organisation
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
put_feed("pic.png", PNG)
put_feed("page.html", '<!doctype html><html><head><meta charset="utf-8"><title>Beispielseite</title><meta property="og:image" content="/pic.png">'
                      '</head><body><p>Ein paar Worte Text auf der Seite, damit es etwas zu lesen gibt.</p></body></html>')
r = A.post(B + "/api/polls", json={"title": "Teamtreffen", "duration": 60, "space": f"org:{ORG}",
                                   "options": [{"start": f"{D}T10:00"}, {"start": f"{D}T14:00"}]})
check(r.status_code == 201, "an organisation poll " + r.text[:200])
POLL = r.json().get("poll", {})
OPTS = [o["id"] for o in POLL.get("options", [])]
OLD_TOK = (POLL.get("url") or "").rsplit("/", 1)[-1]
NOW = iso_s(tnow())
if len(OPTS) == 2:
    dbx("INSERT INTO sched_poll_votes(poll_id,name,email,answers,edit_hash,ip_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (POLL["id"], "Gast Beispiel", "", json.dumps({str(OPTS[0]): "y", str(OPTS[1]): "n"}), "x" * 64, "iphash", NOW, NOW))
r = A.post(B + "/api/polls", json={"title": "Privates Treffen", "duration": 30, "space": "private",
                                   "options": [{"start": f"{D}T09:00"}, {"start": f"{D}T11:00"}]})
check(r.status_code == 201, "a private poll " + r.text[:200])
r = A.post(B + "/api/bookmarks", json={"url": FEED + "page.html", "space": f"org:{ORG}"})
check(r.status_code == 201, "an organisation bookmark " + r.text[:200])
BM = r.json().get("bookmark", {}).get("id")
bm = until(lambda: (lambda j: j if j.get("preview") not in ("pending", "image") else None)(A.get(B + f"/api/bookmarks/{BM}").json()), 30) or {}
check(bm.get("image", "").startswith(f"/api/bookmarks/{BM}/image"), "the bookmark has its picture " + json.dumps(bm)[:200])
check(A.post(B + "/api/bookmarks", json={"url": FEED + "page.html?privat=1", "space": "private"}).status_code == 201, "a private bookmark")
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, "organisation export started " + r.text[:120])
until(lambda: A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running", 240)
OX = su_get(A, B + f"/api/orgs/{ORG}/export/file").content
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
check(OX[:13] == b"KALMIDO-ORGX\n" and RK, "the organisation export + recovery key")
iid = imp_upload(A, OX)
j = imp_wait(A, iid)
if j.get("state") == "key":
    check(A.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": RK}).status_code == 202, "the recovery key is taken")
    j = imp_wait(A, iid)
check(j.get("state") == "preview", f"the export opens {j.get('state')} {j.get('error')}")
r = A.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": ORG2, "people": {}})
check(r.status_code == 202, "the import runs " + r.text[:160])
j = imp_wait(A, iid)
check(j.get("state") == "done", f"imported into the empty organisation {j.get('state')} {j.get('error')}")
polls = dbx("SELECT id, title, token_hash, chosen_id FROM sched_polls WHERE org_id=? AND deleted_at IS NULL", (ORG2,))
check([p[1] for p in polls] == ["Teamtreffen"], f"#2398: the organisation's poll came along, the private one not {polls}")
NP = polls[0][0] if polls else 0
check(polls and not polls[0][2].startswith("import:") and polls[0][2] != one("SELECT token_hash FROM sched_polls WHERE id=?", (POLL.get("id"),)),
      "#2398: the poll has a new link")
nopts = [x[0] for x in dbx("SELECT id FROM sched_poll_options WHERE poll_id=? ORDER BY start", (NP,))]
check(len(nopts) == 2 and not set(nopts) & set(OPTS), f"#2398: its options came along {nopts}")
votes = dbx("SELECT name, answers, ip_hash, edit_hash FROM sched_poll_votes WHERE poll_id=?", (NP,))
check(votes and votes[0][3] and votes[0][3] != "x" * 64, "#2398 review: the vote gets a new edit hash, never the exported one")
ans = json.loads(votes[0][1]) if votes else {}
check(len(votes) == 1 and votes[0][0] == "Gast Beispiel" and len(nopts) == 2 and ans == {str(nopts[0]): "y", str(nopts[1]): "n"} and votes[0][2] == "",
      f"#2398: the vote came along and names the new options {votes}")
NT = A.get(B + f"/api/polls/{NP}").json().get("poll", {}).get("url", "") if NP else ""
check(NT and requests.get(NT.replace(NT.split("/s/v/")[0], B.rstrip("/"))).ok, "#2398: the new link opens " + NT)
check(OLD_TOK and requests.get(B + "/s/v/" + OLD_TOK).ok, "the old organisation's link still works (it was not removed)")
check("new links" in json.dumps(j), "#2398: the import report says the poll links are new")
bms = dbx("SELECT id, url, image FROM bookmarks WHERE org_id=? AND deleted_at IS NULL", (ORG2,))
check(len(bms) == 1 and bms[0][1] == FEED + "page.html" and bms[0][2].startswith("bookmarks/"), f"#2398: the organisation's bookmark came along {bms}")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
q = A.get(B + f"/api/bookmarks/{bms[0][0]}/image") if bms else None
check(q is not None and q.ok and q.content == PNG, f"#2398: its picture opens ({q.status_code if q is not None else '-'})")

print(f"p2380r_h_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
