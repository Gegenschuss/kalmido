#!/usr/bin/env python3
"""2.306.0 A API tests (#2885): the journal (text + mood) and the private filed e-mails are sealed with the account key of
the person while the private spaces are encrypted, like the private files. Own container (start.sh) with a server key.
Invented names and texts only (example.com / example.test).
 - a journal entry: "kenc1:" in the database (text and mood_enc, mood NULL), plain for the person in the day / week view,
   the history (search, mood filter, cursor), the statistics, the export (Markdown / CSV, "my data"), the 409 of a stale save
 - nobody else reads it: another person sees no entry, an agent and a token without the scope "private" get no journal
 - a plain entry from before (written straight into the database) is read and sealed by encrypt-all
 - a private filed mail (hub inbox of the private space): sender, subject, text sealed, shown plain to its owner
 - the way back: decrypt-private opens journal + private mails (organisation mails stay sealed), new entries stay plain
   (private_encrypt=0, the privacy line says so), encrypt-private seals everything again
 - 2.306.0 Fix-2a: a text that only looks sealed stays a text, a sent private mail is sealed, a plain mood written later wins,
   one key that does not open never stops the pass, the account ZIP is readable and its import sealed again,
   decrypt-private / decrypt-all count the rows that stay sealed (exit 1), decrypt-all opens everything
 - the person without an organisation does every step (freelancer-matrix: life)
usage: p2306_a_private_seal_test.py <datadir>      (P2306A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import email.message
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import date, timedelta

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
MAILENV = " ".join(["-e KALMIDO_MAIL_ADDRESS=tasks@example.test", "-e KALMIDO_IMAP_HOST=127.0.0.1", "-e KALMIDO_IMAP_PORT=1143",
                    "-e KALMIDO_IMAP_SSL=0", "-e KALMIDO_IMAP_USER=kalmido", "-e KALMIDO_IMAP_PASSWORD=secret", "-e KALMIDO_IMAP_INTERVAL=600"])
from kt import FAILS, OKS, check, sess, su_get  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def cli(*args):
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-m", "kalmido.admin.orgcrypt_cli", *args], capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def box(code):
    """Python code inside the app container (a fresh process with the server's settings)."""
    r = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code
                        + "\nc.commit()\nc.close()"], capture_output=True, text=True, timeout=120)
    return (r.stdout + r.stderr).strip()


def D(n=0):
    return (date.today() - timedelta(days=n)).isoformat()


def jrow(uid, day):
    r = sql("SELECT text, mood, mood_enc FROM journal WHERE user_id=? AND day=?", (uid, day))
    return tuple(r[0]) if r else None


def sealed(v):
    return isinstance(v, str) and v.startswith("kenc1:")


def file_mail(addr, subject, text):
    """A mail to a hub address, taken in like the mail input does (hbm_mail_import) -> the output of the call."""
    m = email.message.EmailMessage()
    m["From"] = "Nora Sender <nora@example.com>"
    m["To"] = addr
    m["Subject"] = subject
    m["Message-ID"] = f"<{time.time_ns()}@example.com>"
    m.set_content(text)
    raw = m.as_bytes()
    return box("import email, email.policy\nfrom kalmido.hub import hubmail as H\n"
               f"raw = {raw!r}\nmsg = email.message_from_bytes(raw, policy=email.policy.default)\n"
               "print('mid', H.hbm_mail_import(c, msg, raw))")


def mrow(subject_like_id):
    r = sql("SELECT from_addr, from_name, subject, body, org_id FROM hub_mails WHERE id=?", (subject_like_id,))
    return dict(zip(("from_addr", "from_name", "subject", "body", "org_id"), r[0])) if r else None


def mid_of(out):
    for line in out.splitlines():
        if line.startswith("mid "):
            try:
                return int(line.split()[1])
            except ValueError:
                return None
    return None


def export_of(s, secs=120):
    """2.306.0 Fix-2a: the account export (ZIP) of the person of session s, waiting for its state."""
    r = s.post(B + "/api/account/export")
    assert r.status_code == 202, r.text
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + "/api/account/export").json()
        if j.get("state") != "running":
            break
        time.sleep(0.25)
    assert j.get("state") == "done", j
    r = su_get(s, B + "/api/account/export/file")  # 2.360.0 (#2496): the step-up
    assert r.ok, r.text[:200]
    return r.content


def import_into(s, data, secs=180):
    """2.306.0 Fix-2a: the account import of the ZIP data into the private space of session s -> its final state."""
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "kalmido-account.zip"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        assert s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"}).ok
        off += len(part)

    def state():
        j = {}
        for _ in range(secs * 4):
            j = s.get(B + f"/api/account/import/{iid}").json()
            if j.get("state") not in ("checking", "running", "upload"):
                return j
            time.sleep(0.25)
        return j
    state()
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": "private", "people": {}})
    assert r.status_code == 202, r.text
    return state()


if os.environ.get("P2306A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 "
               f"-e KALMIDO_SECRET_KEY={KEY} {MAILENV}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
FEAT = "cal,comments,collab,review,clients,office"
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
FID, Fr = freelancer(B, A)
PEOPLE = (("bob (organisation member)", Bo, BOB), ("frida (no organisation)", Fr, FID))

# ================================================================== the journal, sealed
for who, s, uid in PEOPLE:
    r = s.put(B + f"/api/life/journal/{D(0)}", json={"text": "Walked to the lighthouse_garden today.", "mood": 4})
    check(r.ok and r.json()["text"] == "Walked to the lighthouse_garden today." and r.json()["mood"] == 4, f"{who}: write ({r.status_code} {r.text[:200]})")
    s.put(B + f"/api/life/journal/{D(1)}", json={"text": "A quiet rainy day.", "mood": 2})
    s.put(B + f"/api/life/journal/{D(2)}", json={"text": "", "mood": 5})
    t, m, me_ = jrow(uid, D(0))
    check(sealed(t) and "lighthouse" not in t and m is None and sealed(me_), f"{who}: text and mood sealed in the database ({str(t)[:20]}, {m}, {str(me_)[:12]})")
    t2, m2, me2 = jrow(uid, D(2))
    check(t2 == "" and m2 is None and sealed(me2), f"{who}: a mood without text: the mood sealed ({t2!r}, {m2})")
    rv = s.get(B + "/api/life/review", params={"period": "week", "date": D(0)}).json()
    ent = {x["day"]: x for x in rv.get("journal") or []}
    check(ent.get(D(0), {}).get("text") == "Walked to the lighthouse_garden today." and ent[D(0)]["mood"] == 4 and rv.get("journal_sealed") is True,
          f"{who}: the review shows the entry plain and says it is sealed")
    j = s.get(B + "/api/life/journal").json()
    check([x["day"] for x in j["entries"]][:3] == [D(0), D(1), D(2)] and j.get("sealed") is True, f"{who}: the history newest first, sealed {j.get('sealed')}")
    check([x["day"] for x in s.get(B + "/api/life/journal", params={"q": "LIGHTHOUSE_garden"}).json()["entries"]] == [D(0)], f"{who}: search in sealed texts (case, _ literal)")
    check(s.get(B + "/api/life/journal", params={"q": "lighthousexgarden"}).json()["entries"] == [], f"{who}: _ is a literal")
    check([x["day"] for x in s.get(B + "/api/life/journal", params={"mood": 2}).json()["entries"]] == [D(1)], f"{who}: the mood filter on sealed moods")
    p1 = s.get(B + "/api/life/journal", params={"limit": 1}).json()
    p2 = s.get(B + "/api/life/journal", params={"limit": 1, "before": p1["next"]}).json()
    check(p1["next"] == D(0) and [x["day"] for x in p2["entries"]] == [D(1)], f"{who}: the cursor over sealed entries")
    st = s.get(B + "/api/life/journal/stats", params={"days": 30}).json()
    check(st["rated"] == 3 and st["dist"]["4"] == 1 and st["dist"]["5"] == 1 and st["written"] == 2, f"{who}: the statistics read the sealed moods {st}")
    ex = s.get(B + "/api/life/journal/export", params={"format": "csv"}).text
    check("lighthouse_garden" in ex and "kenc1:" not in ex, f"{who}: the CSV export is plain")
    md = s.get(B + "/api/life/journal/export").text
    check(f"## {D(0)} (4/5)" in md and "kenc1:" not in md, f"{who}: the Markdown export is plain")
    mine = s.get(B + "/api/export.json").json().get("journal") or []
    check(any(x.get("text") == "A quiet rainy day." and x.get("mood") == 2 for x in mine) and "kenc1:" not in str(mine) and "mood_enc" not in str(mine),
          f"{who}: my data export: the journal plain")
    old = s.put(B + f"/api/life/journal/{D(1)}", json={"text": "From the phone", "expect_updated_at": "1999-01-01T00:00:00.000Z"})
    check(old.status_code == 409 and "A quiet rainy day." in old.text and "kenc1:" not in old.text, f"{who}: a stale save: 409 with the entry plain")
    check(s.put(B + f"/api/life/journal/{D(1)}", json={"text": "", "mood": None}).ok and jrow(uid, D(1)) is None, f"{who}: an empty entry is deleted")

# nobody else reads it
check(A.get(B + "/api/life/journal").json()["entries"] == [], "alice (admin) does not see the journal of bob / frida")
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"})
check(r.ok and r.json().get("token"), f"setup: an agent ({r.status_code} {r.text[:200]})")
AGH = {"Authorization": "Bearer " + (r.json().get("token") or "none")}
rv = requests.get(V + "/life/review", headers=AGH)
check(rv.status_code in (401, 403, 409) or "journal" not in rv.json(), f"an agent gets no journal ({rv.status_code})")
check(requests.put(V + f"/life/journal/{D(0)}", headers=AGH, json={"text": "x"}).status_code in (401, 403, 409), "an agent cannot write a journal")
tk = Bo.post(B + "/api/me/tokens", json={"name": "t1", "scopes": ["read", "tasks:write"]}).json()["token"]
rv = requests.get(V + "/life/review", headers={"Authorization": "Bearer " + tk}).json()
check("journal" not in rv and "journal_sealed" not in rv, "a token without the scope private: no journal")

# a plain entry from before 2.306 (straight into the database) is read and sealed by the start-up pass / encrypt-all
sql("INSERT INTO journal(user_id, day, text, mood, updated_at) VALUES(?,?,?,?,?)", (FID, D(5), "An old plain entry.", 3, "2026-01-01T00:00:00.000Z"), write=True)
check([x["text"] for x in Fr.get(B + "/api/life/journal", params={"q": "old plain"}).json()["entries"]] == ["An old plain entry."], "a plain entry is read")
rc, out = cli("encrypt-all")
t, m, me_ = jrow(FID, D(5))
check(rc == 0 and sealed(t) and m is None and sealed(me_), f"encrypt-all seals the plain entry ({rc} {out[-200:]})")
check([x["mood"] for x in Fr.get(B + "/api/life/journal", params={"q": "old plain"}).json()["entries"]] == [3], "... and it reads the same")

# ================================================================== private filed mails
IN_F = Fr.post(B + "/api/hubmail/address", json={"ws": "private"}).json().get("address") or ""
IN_B = Bo.post(B + "/api/hubmail/address", json={"ws": f"org:{ORG}"}).json().get("address") or ""
check("+" in IN_F and "+" in IN_B, f"setup: the hub inbox addresses ({IN_F!r}, {IN_B!r})")
MF = mid_of(file_mail(IN_F, "Private appointment confirmation", "Your appointment is on Monday."))
MB = mid_of(file_mail(IN_B, "Alpha project update", "The project goes on."))
check(bool(MF) and bool(MB), f"setup: both mails filed ({MF}, {MB})")
mf = mrow(MF) or {}
check(all(sealed(mf.get(k)) for k in ("from_addr", "from_name", "subject", "body")) and mf.get("org_id") is None,
      f"a private filed mail: sender, subject, text sealed {[str(mf.get(k))[:10] for k in ('from_addr', 'subject', 'body')]}")
check(sealed((mrow(MB) or {}).get("subject")), "an organisation mail stays sealed")
lst = Fr.get(B + "/api/hubmail/mails", params={"unassigned": 1}).json().get("mails") or []
check(any(x.get("subject") == "Private appointment confirmation" for x in lst) and "kenc1:" not in str(lst), "its owner sees it plain")
check(not any(x.get("id") == MF for x in Bo.get(B + "/api/hubmail/mails", params={"unassigned": 1}).json().get("mails") or []), "another person does not see it")
hit = Fr.get(B + "/api/hubmail/mails", params={"unassigned": 1, "q": "appointment"}).json().get("mails") or []
check([x.get("id") for x in hit] == [MF], "the search finds the sealed private mail")

# ================================================================== 2.306.0 Fix-2a (#2885): review findings
# a text that only starts like a sealed value stays a text: sealed like any other, read back (an invisible mark in front)
r = Fr.put(B + f"/api/life/journal/{D(7)}", json={"text": "kenc1:just my own words", "mood": 3})
t7 = jrow(FID, D(7)) or ("",)
e7 = [x for x in Fr.get(B + "/api/life/journal").json()["entries"] if x["day"] == D(7)]
check(r.ok and sealed(t7[0]) and e7 and e7[0]["text"].lstrip("\u200b") == "kenc1:just my own words" and e7[0]["mood"] == 3,
      f"a journal text that starts like a sealed value is sealed and read back {e7}")
MK = mid_of(file_mail(IN_F, "kenc1:not sealed", "Body of an odd mail."))
mk = mrow(MK) or {}
r = Fr.get(B + f"/api/hubmail/mails/{MK}")
check(sealed(mk.get("subject")) and r.ok and (r.json().get("subject") or "").lstrip("\u200b") == "kenc1:not sealed" and "Body of an odd mail." in r.text,
      f"a mail whose subject starts like a sealed value keeps its texts ({r.status_code} {r.text[:200]})")
# a sent private mail is sealed like a received one
SENT = {"from_addr": "frida@example.com", "from_name": "Frida", "to_addrs": "nora@example.com", "subject": "Reply sent privately", "body": "Sent text."}
out = box("import email.message\nfrom kalmido.core.config import app as fa\nfrom kalmido.hub import mailbox as MB, hubmail as H\n"
          "m = email.message.EmailMessage()\nm['Message-ID'] = '<sent-2306a@example.com>'\nm['Subject'] = 'Reply sent privately'\n"
          f"m.set_content('Sent text.')\nplain = {SENT!r}\nwith fa.test_request_context():\n"
          f"    print('mid', MB._file_sent(c, {FID}, None, None, None, H._ws(None, {FID}), m, bytes(m), plain))")
MS = mid_of(out)
ms = mrow(MS) or {}
r = Fr.get(B + f"/api/hubmail/mails/{MS}")
check(bool(MS) and all(sealed(ms.get(k)) for k in ("from_addr", "subject", "body")) and ms.get("org_id") is None,
      f"a sent private mail: sealed in the database ({MS} {out[-200:]})")
check(r.ok and "Reply sent privately" in r.text and '"kenc1:' not in r.text, f"... and plain for its sender ({r.status_code})")
# a plain mood written later (an older version on the way back keeps mood_enc) wins over the sealed one
Fr.put(B + f"/api/life/journal/{D(6)}", json={"text": "Mood changed later.", "mood": 4})
sql("UPDATE journal SET mood=2 WHERE user_id=? AND day=?", (FID, D(6)), write=True)
e6 = [x for x in Fr.get(B + "/api/life/journal").json()["entries"] if x["day"] == D(6)]
check(e6 and e6[0]["mood"] == 2, f"the mood written later wins {e6}")
# one account key that cannot be opened (made with another server key) does not stop the pass for the others
KC = sql("SELECT kek_check FROM user_keys WHERE user_id=?", (BOB,))[0][0]
sql("UPDATE user_keys SET kek_check='made-with-another-key' WHERE user_id=?", (BOB,), write=True)
for uid, txt in ((BOB, "Bob plain before."), (FID, "Frida plain before.")):
    sql("INSERT INTO journal(user_id, day, text, mood, updated_at) VALUES(?,?,?,?,?)", (uid, D(9), txt, 2, "2026-01-01T00:00:00.000Z"), write=True)
rc, out = cli("encrypt-all")
sql("UPDATE user_keys SET kek_check=? WHERE user_id=?", (KC, BOB), write=True)
check(sealed((jrow(FID, D(9)) or ("",))[0]) and jrow(BOB, D(9)) == ("Bob plain before.", 2, None),
      f"a key that does not open: its rows stay as they are, the others are sealed ({rc} {out[-300:]})")
t6 = jrow(FID, D(6)) or ("", 0, "")
check(t6[1] is None and sealed(t6[2]) and [x["mood"] for x in Fr.get(B + "/api/life/journal").json()["entries"] if x["day"] == D(6)] == [2],
      f"encrypt-all seals the mood written later {t6[1]}")
# the account export (ZIP): journal and private mails readable; its import into another account: sealed again
EXP = export_of(Fr)
z = zipfile.ZipFile(io.BytesIO(EXP))
jz, hz = z.read("data/journal.json").decode(), z.read("data/hub_mails.json").decode()
check("Walked to the lighthouse_garden today." in jz and '"kenc1:' not in jz and "Frida plain before." in jz, "the account ZIP: the journal readable")
check("Private appointment confirmation" in hz and "Reply sent privately" in hz and '"kenc1:' not in hz, "the account ZIP: the private mails readable")
FI2, Fi = freelancer(B, A, "fiona")
st = import_into(Fi, EXP)
fi0 = jrow(FI2, D(0)) or ("", 0, "")
check(st.get("state") == "done" and sealed(fi0[0]) and fi0[1] is None and sealed(fi0[2]), f"the account import: the journal sealed for the new account {st.get('state')} {st.get('error')}")
check([x["text"] for x in Fi.get(B + "/api/life/journal", params={"q": "lighthouse"}).json()["entries"]] == ["Walked to the lighthouse_garden today."],
      "... and readable for it")

# ================================================================== the way back and again
rc, out = cli("decrypt-private")
check(rc == 0, f"decrypt-private runs ({out[-300:]})")
t, m, me_ = jrow(FID, D(0))
check(t == "Walked to the lighthouse_garden today." and m == 4 and not me_, f"decrypt-private: the journal plain again ({str(t)[:20]}, {m})")
check(jrow(BOB, D(2)) == ("", 5, None), f"decrypt-private: a mood-only entry plain again {jrow(BOB, D(2))}")
mf = mrow(MF) or {}
check(mf.get("subject") == "Private appointment confirmation" and mf.get("body", "").startswith("Your appointment"), "decrypt-private: the private mail plain again")
check(sealed((mrow(MB) or {}).get("subject")), "decrypt-private: the organisation mail stays sealed")
# the private spaces are not encrypted now: everything new stays plain, the privacy line says so
Fr.put(B + f"/api/life/journal/{D(3)}", json={"text": "Written while plain.", "mood": 1})
check(jrow(FID, D(3)) == ("Written while plain.", 1, None), f"private_encrypt=0: a new entry is stored as before {jrow(FID, D(3))}")
check(Fr.get(B + "/api/life/journal").json().get("sealed") is False and Fr.get(B + "/api/life/review").json().get("journal_sealed") is False,
      "private_encrypt=0: the history and the review say: not sealed")
MF2 = mid_of(file_mail(IN_F, "Plain while off", "Stays plain."))
check((mrow(MF2) or {}).get("subject") == "Plain while off", "private_encrypt=0: a new private mail stays plain")
check(sealed((mrow(mid_of(file_mail(IN_B, "Alpha second", "Org mail."))) or {}).get("subject")), "private_encrypt=0: an organisation mail is still sealed")
rc, out = cli("encrypt-private")
check(rc == 0, f"encrypt-private runs ({out[-300:]})")
check(sealed(jrow(FID, D(3))[0]) and sealed(jrow(FID, D(0))[0]) and sealed(jrow(BOB, D(2))[2]), "encrypt-private: the journal sealed again")
check(sealed((mrow(MF) or {}).get("subject")) and sealed((mrow(MF2) or {}).get("body")), "encrypt-private: the private mails sealed again")
check([x["text"] for x in Fr.get(B + "/api/life/journal", params={"q": "while plain"}).json()["entries"]] == ["Written while plain."], "... and read plain")
check(Fr.get(B + "/api/life/journal").json().get("sealed") is True, "encrypt-private: the history says sealed again")

# ================================================================== 2.306.0 Fix-2a (#2885): the way back says what stays sealed
GARB = "kenc1:" + "A" * 40  # a sealed value no key opens
sql("INSERT INTO journal(user_id, day, text, mood, updated_at) VALUES(?,?,?,?,?)", (FID, D(10), GARB, None, "2026-01-01T00:00:00.000Z"), write=True)
sql("UPDATE hub_mails SET subject=? WHERE id=?", (GARB, MF2), write=True)
rc, out = cli("decrypt-private")
m = re.search(r"still encrypted in private spaces: (-?\d+)", out)
check(rc == 1 and m and int(m.group(1)) >= 2, f"decrypt-private: rows that do not open count as still encrypted, exit 1 ({rc} {out[-300:]})")
check((jrow(FID, D(10)) or ("",))[0] == GARB and (mrow(MF2) or {}).get("subject") == GARB and (mrow(MF) or {}).get("subject") == "Private appointment confirmation",
      "decrypt-private: a row that cannot be opened is left as it is, the others are plain")
rc, out = cli("status")
try:
    prow = json.JSONDecoder().raw_decode(out[out.index("{"):])[0]["private"]["rows"]
except (ValueError, KeyError):
    prow = None
check(prow == {"journal": 1, "hub_mails": 1}, f"status: the sealed private rows {prow} ({out[-200:]})")
rc, out = cli("decrypt-all")
check(rc == 1, f"decrypt-all: exit 1 while a row stays sealed ({rc} {out[-300:]})")
sql("DELETE FROM journal WHERE user_id=? AND day=?", (FID, D(10)), write=True)
sql("UPDATE hub_mails SET subject=? WHERE id=?", ("Plain while off", MF2), write=True)
rc, out = cli("decrypt-all")
check(rc == 0 and "still encrypted: 0" in out, f"decrypt-all: everything plain, exit 0 ({rc} {out[-300:]})")
check(jrow(FID, D(0)) == ("Walked to the lighthouse_garden today.", 4, None) and (mrow(MB) or {}).get("subject") == "Alpha project update"
      and (mrow(MS) or {}).get("subject") == "Reply sent privately", "decrypt-all: journal, private and organisation mails plain")

print(f"\np2306_a_private_seal: {OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
