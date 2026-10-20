#!/usr/bin/env python3
"""2.140.0 API tests, part D (#2137): birthdays back into a connected CardDAV address book. Own container (start.sh) with the
fake server fake_carddav_wb.py (writable book, a read-only mirror, a book that answers 403). Invented names only.
 - a source has writeback off by default (also after reading); a book with write right = writeback_avail "yes"
 - off: the date field of the family section (_act occ_date) changes only the task, nothing is PUT
 - on (PATCH writeback true): the date field -> the next sync starts by itself and PUTs the card with If-Match; only the BDAY
   value changes, every other byte stays (CRLF, a folded line, other properties); the year field writes the year
 - the style of the date stays: --MMDD (vCard 4) keeps no year, Apple's 1604 + X-APPLE-OMIT-YEAR gets the year and loses
   the parameter, LF line ends + a folded BDAY line, an anniversary (ANNIVERSARY) next to an untouched BDAY
 - the next read does not turn the own change back; snoozing / moving the task (due without the date field), deleting
   the task and removing the year write nothing
 - changed in the address book meanwhile: the address book wins (no PUT); a 412 on the PUT: nothing overwritten, the task
   takes the address book's date, the source shows the conflict
 - a read-only mirror (privilege set without write): writeback_avail "no", switching on = 409; a book that answers 403:
   marked read only after the first try; the password never in the server's log
 - only the owner of the source writes: a change by another list member stays in Kalmido
 - a person without an organisation (freelancer-matrix: personal) does all of the above in the own private space
usage: p2140_d_api_test.py <datadir>      (P2140D_NOSTART=1: a running server on KALMIDO_TEST_PORT with the fake server)"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date

import requests
import testclock
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
NOSTART = os.environ.get("P2140D_NOSTART") == "1"
PW = "wb-secret-2140"
URL = "http://127.0.0.1:8097/"
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def until(fn, secs=20):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


WB = os.path.join(DATA, "wb")


def card_write(acc, name, text):
    d = os.path.join(WB, acc)
    os.makedirs(d, exist_ok=True)
    os.chmod(d, 0o777)
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(text.encode("utf-8"))
    os.chmod(p, 0o666)


def card(acc, name):
    return open(os.path.join(WB, acc, name), "rb").read().decode("utf-8")


def log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "wb.log"), encoding="utf-8")]
    except OSError:
        return []


def puts():
    return [x for x in log() if x["method"] == "PUT"]


# ================================================================ start: the app + the fake address book server
os.makedirs(WB, exist_ok=True)
if not NOSTART:
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_CALENDAR_TICK=1 -e KALMIDO_CALENDAR_REFRESH_GAP=0")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
os.makedirs(WB, exist_ok=True)
os.chmod(WB, 0o777)
C1 = ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:wb-c1\r\nFN:Anna Beispiel\r\nN:Beispiel;Anna;;;\r\nNOTE:A long note that is folded over two lines s\r\n"
      " o that the folding has to stay exactly as it is\r\nBDAY:1960-03-15\r\nTEL;TYPE=CELL:+49 30 1234567\r\nX-CUSTOM-THING:keep me\r\nEND:VCARD\r\n")
C2 = "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:wb-c2\r\nFN:Ben Muster\r\nBDAY:--0704\r\nANNIVERSARY:19850720\r\nEND:VCARD\r\n"
C3 = ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:wb-c3\r\nN:Probe;Carla;;;\r\nBDAY;X-APPLE-OMIT-YEAR=1604:1604-11-02\r\n"
      "item1.X-ABDATE:2001-09-09\r\nitem1.X-ABLabel:_$!<Anniversary>!$_\r\nEND:VCARD\r\n")
C4 = "BEGIN:VCARD\nVERSION:3.0\nUID:wb-c4\nFN:Dora Test\nBDAY;VALUE=DATE:197\n 00101\nEMAIL:dora@example.com\nEND:VCARD\n"
for n, t in (("c1.vcf", C1), ("c2.vcf", C2), ("c3.vcf", C3), ("c4.vcf", C4)):
    card_write("u", n, t)
card_write("m", "c1.vcf", C1)
card_write("x", "c1.vcf", C1)
shutil.copy(os.path.join(N, "fake_carddav_wb.py"), DATA)
if not NOSTART:
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_carddav_wb.py"])
until(lambda: requests.get("http://127.0.0.1:%s/" % os.environ.get("KALMIDO_TEST_PORT", "3048")).status_code < 500, 5)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments", "family"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "cal,comments,collab,family,contacts"})
# freelancer-matrix: personal  (the whole write-back runs as a person without an organisation)
FID, Fr = freelancer(B, A)
today = testclock.today()

r = Fr.post(B + "/api/family/contacts", json={"url": URL, "username": "u", "password": PW})
check(r.status_code == 201 and r.json()["count"] == 6, "the address book read: 6 dates " + r.text[:300])
SRC = r.json()["id"]
check(r.json()["writeback"] is False and r.json()["writeback_avail"] == "yes" and r.json()["writeback_error"] == "",
      "write-back off by default, the book may be written " + r.text[:300])


def occs():
    st = Fr.get(B + "/api/state").json()
    return {t["fam"]["card"] + "|" + t["fam"]["kind"]: t for t in st["tasks"] if (t.get("fam") or {}).get("src") == f"carddav:{SRC}"}


O = occs()
check(set(O) == {"wb-c1|birthday", "wb-c2|birthday", "wb-c2|anniversary", "wb-c3|birthday", "wb-c3|anniversary", "wb-c4|birthday"}, f"the tasks {sorted(O)}")
anna = O["wb-c1|birthday"]
nxt = lambda m, d: (date(today.year, m, d) if date(today.year, m, d) >= today else date(today.year + 1, m, d)).isoformat()  # noqa: E731


def patch(t, body, s=None):
    return (s or Fr).patch(B + f"/api/tasks/{t['id']}", json=body)


# ---- off: only the task changes
n0 = len(puts())
r = patch(anna, {"due": nxt(3, 18), "_act": "occ_date"})
check(r.ok and r.json()["due"] == nxt(3, 18), "off: the date field changes the task " + r.text[:200])
time.sleep(2.5)
check(len(puts()) == n0 and card("u", "c1.vcf") == C1, "off: nothing written into the address book")
patch(anna, {"due": nxt(3, 15), "_act": "occ_date"})

# ---- on
r = Fr.patch(B + f"/api/family/contacts/{SRC}", json={"writeback": True})
check(r.ok and r.json()["writeback"] is True, "switched on " + r.text[:200])
check(Fr.patch(B + f"/api/family/contacts/{SRC}", json={"writeback": "yes"}).status_code == 400, "writeback must be true / false")
r = patch(anna, {"due": f"{today.year + 3}-03-20", "_act": "occ_date"})
check(r.ok and r.json()["due"] == nxt(3, 20) and r.json()["repeat"] == "FREQ=YEARLY", "the date field: the task moves to the next 20 March " + r.text[:200])
check(until(lambda: "BDAY:1960-03-20" in card("u", "c1.vcf")), "the next sync starts by itself and writes BDAY")
check(card("u", "c1.vcf") == C1.replace("BDAY:1960-03-15", "BDAY:1960-03-20"), "only the BDAY value changed, every other byte stays (CRLF, folded NOTE) "
      + repr(card("u", "c1.vcf")))
p = [x for x in puts() if x["path"].endswith("/c1.vcf")]
check(p and p[-1]["if_match"] and p[-1]["if_match"].startswith('"'), "PUT with If-Match (the ETag) " + repr(p[-1:]))
r = patch(anna, {"fam": {**anna["fam"], "year": 1961}})
check(r.ok, "the year field " + r.text[:200])
check(until(lambda: "BDAY:1961-03-20" in card("u", "c1.vcf")), "the year goes into the card: " + repr(card("u", "c1.vcf")))

# the next read keeps the own change (no "foreign" change turned back)
n1 = len(puts())
time.sleep(1.2)
r = Fr.post(B + f"/api/family/contacts/{SRC}/sync")
anna2 = occs()["wb-c1|birthday"]
check(r.ok and anna2["due"] == nxt(3, 20) and anna2["fam"].get("year") == 1961 and len(puts()) == n1, "read again: the task keeps 20 March 1961, nothing written again")

# the styles of the date
patch(O["wb-c2|birthday"], {"due": nxt(7, 5), "_act": "occ_date"})
check(until(lambda: "BDAY:--0705" in card("u", "c2.vcf")), "--MMDD stays without a year: " + repr(card("u", "c2.vcf")))
check(card("u", "c2.vcf") == C2.replace("BDAY:--0704", "BDAY:--0705"), "… the ANNIVERSARY next to it untouched")
patch(O["wb-c2|anniversary"], {"due": nxt(7, 21), "_act": "occ_date"})
check(until(lambda: "ANNIVERSARY:19850721" in card("u", "c2.vcf")), "an anniversary in the basic style (YYYYMMDD) " + repr(card("u", "c2.vcf")))
patch(O["wb-c3|birthday"], {"fam": {**O["wb-c3|birthday"]["fam"], "year": 1990}})
check(until(lambda: "BDAY:1990-11-02" in card("u", "c3.vcf")), "Apple's year-less date gets the year: " + repr(card("u", "c3.vcf")))
check(card("u", "c3.vcf") == C3.replace("BDAY;X-APPLE-OMIT-YEAR=1604:1604-11-02", "BDAY:1990-11-02"), "… without X-APPLE-OMIT-YEAR, the X-ABDATE untouched")
patch(O["wb-c4|birthday"], {"due": nxt(1, 2), "_act": "occ_date"})
check(until(lambda: "19700102" in card("u", "c4.vcf")), "a folded BDAY line with LF line ends: " + repr(card("u", "c4.vcf")))
check(card("u", "c4.vcf") == C4.replace("BDAY;VALUE=DATE:197\n 00101\n", "BDAY;VALUE=DATE:19700102\n"), "… LF kept, the rest untouched " + repr(card("u", "c4.vcf")))

# moving / snoozing, removing the year, deleting: nothing written
n2, c1_now = len(puts()), card("u", "c1.vcf")
patch(anna2, {"due": (date.fromisoformat(anna2["due"]).replace(day=22)).isoformat()})
patch(anna2, {"fam": {**anna2["fam"], "year": None}})
Fr.delete(B + f"/api/tasks/{O['wb-c4|birthday']['id']}")
time.sleep(2.5)
check(len(puts()) == n2 and card("u", "c1.vcf") == c1_now, "moving the task, removing the year, deleting: nothing written " + repr(puts()[n2:]))
patch(anna2, {"due": nxt(3, 20), "fam": {**anna2["fam"], "year": 1961}})

# changed in the address book meanwhile: the address book wins
time.sleep(1.2)
Fr.post(B + f"/api/family/contacts/{SRC}/sync")
n3 = len(puts())
card_write("u", "c1.vcf", card("u", "c1.vcf").replace("BDAY:1961-03-20", "BDAY:1961-04-01"))
patch(occs()["wb-c1|birthday"], {"due": nxt(3, 25), "_act": "occ_date"})
check(until(lambda: occs()["wb-c1|birthday"]["due"] == nxt(4, 1)), "changed in the address book too: the task takes its date " + occs()["wb-c1|birthday"]["due"])
check(len(puts()) == n3 and "BDAY:1961-04-01" in card("u", "c1.vcf"), "… nothing written")

# 412 on the PUT: nothing overwritten, the task takes the address book's date, the source shows it
time.sleep(1.2)
open(os.path.join(WB, "force412"), "w").close()
os.chmod(os.path.join(WB, "force412"), 0o666)
patch(occs()["wb-c1|birthday"], {"due": nxt(4, 3), "_act": "occ_date"})
check(until(lambda: not os.path.exists(os.path.join(WB, "force412"))), "the PUT was tried (412)")
check(until(lambda: occs()["wb-c1|birthday"]["due"] == nxt(4, 1)) and "BDAY:1961-04-01" in card("u", "c1.vcf"), "412: nothing overwritten, the task back on 1 April")
src = next(x for x in Fr.get(B + "/api/family/contacts").json()["sources"] if x["id"] == SRC)
check("same time" in src["writeback_error"] and src["status"] == "ok", "the source shows the conflict, reading stays ok " + json.dumps(src)[:300])

# ---- only the owner writes: a member of a shared list changes the date -> stays in Kalmido
lid = occs()["wb-c1|birthday"]["list_id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = Fr.put(B + f"/api/lists/{lid}/members", json={"user_id": ALICE, "role": "edit"})
if r.ok:
    time.sleep(1.2)
    n4, c1_now = len(puts()), card("u", "c1.vcf")
    patch(occs()["wb-c1|birthday"], {"due": nxt(4, 9), "_act": "occ_date"}, A)
    time.sleep(2.5)
    check(len(puts()) == n4 and card("u", "c1.vcf") == c1_now, "a change by another member is not written into the owner's address book")
else:
    print("note: sharing the list failed, member case skipped:", r.status_code, r.text[:200])

# ---- a read-only mirror and a book that answers 403
r = Fr.post(B + "/api/family/contacts", json={"url": URL, "username": "m", "password": PW})
check(r.status_code == 201 and r.json()["writeback_avail"] == "no", "a mirror (privilege set without write): writeback_avail no " + r.text[:300])
MSRC = r.json()["id"]
r = Fr.patch(B + f"/api/family/contacts/{MSRC}", json={"writeback": True})
check(r.status_code == 409, "… cannot be switched on (409) " + r.text[:200])
r = Fr.post(B + "/api/family/contacts", json={"url": URL, "username": "x", "password": PW})
XSRC = r.json()["id"]
check(r.status_code == 201 and r.json()["writeback_avail"] == "yes", "a book that tells no privileges: tried " + r.text[:300])
Fr.patch(B + f"/api/family/contacts/{XSRC}", json={"writeback": True})
xt = next(t for t in Fr.get(B + "/api/state").json()["tasks"] if (t.get("fam") or {}).get("src") == f"carddav:{XSRC}")
patch(xt, {"due": nxt(3, 16), "_act": "occ_date"})
check(until(lambda: next(x for x in Fr.get(B + "/api/family/contacts").json()["sources"] if x["id"] == XSRC)["writeback_avail"] == "no"),
      "403 on the PUT: the book is marked read only")
xs = next(x for x in Fr.get(B + "/api/family/contacts").json()["sources"] if x["id"] == XSRC)
check("read only" in xs["writeback_error"] and card("x", "c1.vcf") == C1, "… the source says so, the card unchanged " + json.dumps(xs)[:300])

# ---- privacy: the password never in the server's log, the sources stay private
if not NOSTART:
    lg = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    check(PW not in lg.stdout + lg.stderr, "the address book password is never logged")
check(A.patch(B + f"/api/family/contacts/{SRC}", json={"writeback": False}).status_code == 404, "another person cannot switch it")
check(not any(x.get("user") is None and x["method"] == "PUT" for x in log()), "every PUT with the account's login")

print(f"p2140_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
