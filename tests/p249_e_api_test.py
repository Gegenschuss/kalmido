#!/usr/bin/env python3
"""2.49.0 API tests, part E (#1106): finding people by e-mail (opt-in), the address book check, connection requests.
Invented names and example.com addresses only.
 - "Findable by e-mail" is off by default; on = a confirmation link by mail (SMTP stub), only the account itself can use it
 - find: exact address only (trim + lower case), no prefix; the answer for "no account", "not findable", "disabled",
   "agent", "kid" and "myself" is byte-identical (status + body) and takes a similar time
 - requests need the ref of a hit (user ids cannot be probed); accept / decline (the sender keeps seeing "sent") /
   reopen / withdraw; mutual requests connect at once; News items; after accepting both see each other
 - disconnect + restore (undo), block (hidden requests, no News), unblock; blocking a stranger: 404
 - limits: 30 searches a day (neutral message), the address book check counts per address and shows only findable people
 - agents (Bearer token) and kid accounts have no access; organisation members see each other as before; an admin finds
   nobody who is not findable; a changed account address ends the findability
usage: p249_e_api_test.py <datadir>      (a fresh container with the SMTP stub of stub_mail.py)"""
import email
import json
import os
import re
import statistics
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

from kt import FAILS, OKS, check, sess, until, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
MAILENV = ["-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none",
           "-e", "KALMIDO_MAIL_FROM=kalmido@example.test", "-e", "KALMIDO_INSTANCE_MODE=workspaces",
           "-e", "KALMIDO_DISC_PER_IP=200"]  # the whole suite comes from one address; the brake itself is checked at the end


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall() if not write else c.execute(sql, args)
        if write:
            c.commit()
            return None
        return r
    finally:
        c.close()


def mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def token_of(m):
    msg = email.message_from_string(m["raw"])
    for p in msg.walk():
        if p.get_content_type() == "text/plain":
            t = re.search(r"#dsc-confirm/([A-Za-z0-9_-]{20,100})", p.get_payload(decode=True).decode())
            if t:
                return t.group(1)
    return None


def make_findable(s, addr):
    """Switch on + confirm with the mailed link; returns the profile."""
    n = len(mails())
    r = s.put(B + "/api/disc", json={"on": True})
    assert r.ok, r.text
    m = until(lambda: len(mails()) > n and mails()[-1], 10)
    assert m and addr.lower() in json.dumps(m["to"]).lower(), m
    r = s.post(B + "/api/disc/confirm", json={"token": token_of(m)})
    assert r.ok, r.text
    return r.json()["profile"]


def find(s, addr):
    return s.post(B + "/api/disc/find", json={"email": addr})


def seen(s):
    return {u["username"] for u in s.get(B + "/api/users").json()["users"]}


def news(s):
    return [x["kind"] for x in s.get(B + "/api/news").json().get("items", [])]


# ---------------------------------------------------------------- set-up: a container with the SMTP stub
subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
subprocess.run(["rm", "-rf", DATA])
os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)),
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, mail in (("ann", "Ann.Example@Example.com"), ("bob", "bob@example.com"), ("cid", "cid@example.com"), ("dan", "dan@example.com"),
                ("eve", "eve@example.com"), ("kim", "kim@example.com"), ("old", "old@example.com")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": mail})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ANN, BOB, CID, DAN, EVE, KIM, OLD = (ids[x] for x in ("ann", "bob", "cid", "dan", "eve", "kim", "old"))
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "dan@example.com"}).ok, "setup: dan joins Alpha")
r = A.post(B + "/api/admin/agents", json={"username": "helperbot", "display_name": "Helper bot", "scopes": ["write"]})
assert r.status_code == 201, r.text
AGENT, AGTOK = r.json()["id"], r.json().get("token") or ""
dbx("UPDATE users SET email='bot@example.com' WHERE id=?", (AGENT,), write=True)
An, Bo, Ci, Da, Ev, Ki, Ol = (sess(x) for x in ("ann", "bob", "cid", "dan", "eve", "kim", "old"))
for s in (A, An, Bo, Ci, Da, Ev, Ki, Ol):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ---- rollback: only new tables
for t in ("disc_profiles", "disc_tokens", "disc_quota", "conn_requests", "conn_links", "conn_blocks"):
    check(dbx("SELECT 1 FROM information_schema.tables WHERE table_name=?", (t,)), f"new table {t}")

# ---- off by default; confirmation by mail, only for the account itself
d = An.get(B + "/api/disc").json()
check(d["profile"]["on"] is False and d["profile"]["confirmed"] is False, f"findable: off by default ({d['profile']})")
check(find(Bo, "ann.example@example.com").json() == {"person": None}, "not findable before switching on")
n0 = len(mails())
r = An.put(B + "/api/disc", json={"on": True})
check(r.ok and r.json().get("sent") and r.json()["profile"]["pending"], f"switching on sends a confirmation link ({r.text[:200]})")
m = until(lambda: len(mails()) > n0 and mails()[-1], 10)
tok = token_of(m) if m else None
check(tok and "ann.example@example.com" in json.dumps(m["to"]).lower(), "the link goes to the account's own address")
check(find(Bo, "ann.example@example.com").json() == {"person": None}, "not findable before the confirmation")
check(Bo.post(B + "/api/disc/confirm", json={"token": tok}).status_code == 404, "another account cannot use the link")
check(An.post(B + "/api/disc/confirm", json={"token": "x" * 40}).status_code == 404, "a wrong token: 404")
r = An.post(B + "/api/disc/confirm", json={"token": tok})
check(r.ok and r.json()["profile"]["confirmed"], f"confirmed with the link ({r.text[:200]})")
check(An.post(B + "/api/disc/confirm", json={"token": tok}).status_code == 404, "the link works once")
h = dbx("SELECT token_hash FROM disc_tokens")
check(not any(tok in (x[0] or "") for x in h), "tokens are stored as hashes only")

# ---- find: exact and normalised only
for v in ("ann.example@example.com", "  ANN.EXAMPLE@EXAMPLE.COM ", "Ann.Example@Example.com"):
    p = find(Bo, v).json().get("person")
    check(p and p["id"] == ANN and p["name"] == "Ann" and p["state"] == "none" and p.get("ref"), f"exact match found ({v!r}: {p})")
check(set(find(Bo, "ann.example@example.com").json()["person"]) == {"id", "name", "avatar", "ref", "state"},
      "a hit shows only id, name, picture, ref and state (no address, no organisation)")
for v in ("ann.example@example", "ann.example", "ann", "%@example.com", "*@example.com", "ann.example@example.co",
          "ann.example@exampIe.com", "ann.​example@example.com", "ａnn.example@example.com", ""):
    check(find(Bo, v).json() == {"person": None}, f"no match for {v!r}")

# ---- the neutral answer: byte-identical for every kind of miss
dbx("INSERT INTO disc_profiles(user_id,email,confirmed_at,created_at) VALUES(?,?,?,?)", (AGENT, "bot@example.com", "2026-01-01", "2026-01-01"), write=True)
dbx("UPDATE users SET kid=1 WHERE id=?", (KIM,), write=True)
dbx("INSERT INTO disc_profiles(user_id,email,confirmed_at,created_at) VALUES(?,?,?,?)", (KIM, "kim@example.com", "2026-01-01", "2026-01-01"), write=True)
make_findable(Ol, "old@example.com")
check(A.patch(B + f"/api/users/{OLD}", json={"disabled": True}).ok, "setup: old is disabled")
make_findable(Ev, "eve@example.com")
base = find(Bo, "nobody@example.com")
for label, v in (("not findable", "cid@example.com"), ("disabled", "old@example.com"), ("agent", "bot@example.com"),
                 ("kid account", "kim@example.com"), ("myself", "bob@example.com"), ("invalid", "not an address")):
    r = find(Bo, v)
    check(r.status_code == base.status_code and r.content == base.content, f"same bytes as 'no account' for {label} ({r.content!r} vs {base.content!r})")
# time: medians of both kinds of miss lie close together (the same queries run)
dbx("DELETE FROM disc_quota", write=True)
t_no, t_nf = [], []
for i in range(12):
    for arr, v in ((t_no, f"nobody{i}@example.com"), (t_nf, "cid@example.com")):
        t = time.perf_counter()
        find(Da, v)
        arr.append(time.perf_counter() - t)
dbx("DELETE FROM disc_quota", write=True)
mn, mf = statistics.median(t_no), statistics.median(t_nf)
check(abs(mn - mf) < 0.05 + 0.5 * min(mn, mf), f"similar time for 'no account' and 'not findable' ({mn * 1000:.1f} / {mf * 1000:.1f} ms)")

# ---- requests: only with the ref of a hit
check(Bo.post(B + "/api/disc/requests", json={"ref": "0" * 40}).status_code == 404, "a made-up ref: 404")
check(Bo.post(B + "/api/disc/requests", json={"user_id": CID}).status_code == 404, "a user id alone: 404 (no probing)")
ref = find(Bo, "ann.example@example.com").json()["person"]["ref"]
r = Bo.post(B + "/api/disc/requests", json={"ref": ref})
check(r.ok and r.json()["state"] == "sent", f"request sent ({r.text[:120]})")
RID = r.json().get("id")
r2 = Bo.post(B + "/api/disc/requests", json={"ref": ref})
check(r2.ok and r2.json() == {"id": RID, "state": "sent"}, "asking again changes nothing")
check(find(Bo, "ann.example@example.com").json()["person"]["state"] == "sent", "the hit shows 'sent'")
d = An.get(B + "/api/disc").json()
check([x["person"]["id"] for x in d["incoming"]] == [BOB] and d["incoming"][0]["person"]["name"] == "Bob", f"ann sees bob's request ({d['incoming']})")
check("connreq" in news(An), "ann gets a News item")
check("ann" not in seen(Bo) and "bob" not in seen(An), "before accepting nobody sees the other")

# decline: the sender still sees "sent"
check(An.post(B + f"/api/disc/requests/{RID}/decline").ok, "declined")
d = Bo.get(B + "/api/disc").json()
check([x["person"]["id"] for x in d["outgoing"]] == [ANN], "after declining bob still sees his request as sent")
check(find(Bo, "ann.example@example.com").json()["person"]["state"] == "sent", "declined looks like 'sent' to bob")
check(not An.get(B + "/api/disc").json()["incoming"], "a declined request leaves ann's list")
check("connreq" not in news(An), "the News item goes with it")
check(Bo.post(B + f"/api/disc/requests/{RID}/accept").status_code == 404, "the sender cannot accept his own request")
check(An.post(B + f"/api/disc/requests/{RID}/reopen").ok, "undo of declining (reopen)")
r = An.post(B + f"/api/disc/requests/{RID}/accept")
check(r.ok and r.json().get("user_id") == BOB, "accepted")
check("ann" in seen(Bo) and "bob" in seen(An), "after accepting both see each other")
check("connok" in news(Bo), "bob gets 'accepted'")
check(find(Bo, "ann.example@example.com").json()["person"]["state"] == "connected", "state connected")
d = An.get(B + "/api/disc").json()
check([x["person"]["id"] for x in d["connections"]] == [BOB], "ann's connections list bob")
check(not Bo.get(B + "/api/disc").json()["outgoing"], "an accepted request leaves the sent list")

# undo of accepting; disconnect + restore
check(An.post(B + f"/api/disc/requests/{RID}/reopen").ok and "ann" not in seen(Bo), "undo of accepting removes the connection")
check(An.post(B + f"/api/disc/requests/{RID}/accept").ok and "ann" in seen(Bo), "accepted again")
check(Bo.delete(B + f"/api/disc/connections/{ANN}").ok and "ann" not in seen(Bo) and "bob" not in seen(An), "disconnected")
check(An.post(B + f"/api/disc/connections/{BOB}/restore").status_code == 404, "only the one who disconnected can undo it")
check(Bo.post(B + f"/api/disc/connections/{ANN}/restore").ok and "ann" in seen(Bo), "undo of disconnecting")

# ---- mutual requests connect at once; withdraw
make_findable(Bo, "bob@example.com")
r = Ev.post(B + "/api/disc/requests", json={"ref": find(Ev, "bob@example.com").json()["person"]["ref"]})
check(r.ok and r.json()["state"] == "sent", "eve asks bob")
r = Bo.post(B + "/api/disc/requests", json={"ref": find(Bo, "eve@example.com").json()["person"]["ref"]})
check(r.ok and r.json()["state"] == "connected" and "eve" in seen(Bo), "bob asks eve back: connected at once")
r = Ci.post(B + "/api/disc/requests", json={"ref": find(Ci, "eve@example.com").json()["person"]["ref"]})
CRID = r.json().get("id")
check(Ev.get(B + "/api/disc").json()["incoming"][0]["person"]["id"] == CID, "eve sees cid's request")
check(Ci.delete(B + f"/api/disc/requests/{CRID}").ok, "cid withdraws")
check(not Ev.get(B + "/api/disc").json()["incoming"] and "connreq" not in news(Ev), "withdrawn: gone for eve (also the News item)")
check(Ev.delete(B + f"/api/disc/requests/{CRID}").status_code == 404, "only the sender withdraws")
# 2.49.0 review S1: withdraw + ask again is no loop: the same row comes back (no new request), a declined one stays declined
check(not [x for x in Ci.get(B + "/api/disc").json()["outgoing"] if x["id"] == CRID], "a withdrawn request leaves the sent list")
CREF = find(Ci, "eve@example.com").json()["person"]["ref"]
r = Ci.post(B + "/api/disc/requests", json={"ref": CREF})
check(r.ok and r.json().get("id") == CRID and Ev.get(B + "/api/disc").json()["incoming"][0]["id"] == CRID, "asking again restores the same request")
check(Ev.post(B + f"/api/disc/requests/{CRID}/decline").ok, "eve declines cid")
check(Ci.delete(B + f"/api/disc/requests/{CRID}").ok, "cid withdraws the declined request")
r = Ci.post(B + "/api/disc/requests", json={"ref": CREF})
check(r.ok and r.json().get("state") == "sent" and r.json().get("id") == CRID, "asking again after a withdrawal: 'sent' again")
check(not Ev.get(B + "/api/disc").json()["incoming"] and "connreq" not in news(Ev), "a declined request stays declined after withdraw + ask")
check(Ci.delete(B + f"/api/disc/requests/{CRID}").ok, "cid withdraws it again (the checks below expect no request to eve)")

# ---- block
r = Ci.post(B + "/api/disc/requests", json={"ref": find(Ci, "ann.example@example.com").json()["person"]["ref"]})
check(r.ok and r.json()["state"] == "sent", "cid asks ann")
check(An.post(B + f"/api/disc/blocks/{DAN}").status_code == 404, "blocking a stranger (no request, no connection): 404")
r = An.post(B + f"/api/disc/blocks/{CID}")
check(r.ok and r.json().get("unlinked") is False, "ann blocks cid")
d = An.get(B + "/api/disc").json()
check(not d["incoming"] and [x["person"]["id"] for x in d["blocked"]] == [CID], "the request is hidden, cid is in the blocked list")
check([x["person"]["id"] for x in Ci.get(B + "/api/disc").json()["outgoing"]] == [ANN], "cid still sees 'sent'")
n = news(An).count("connreq")
r = Ci.post(B + "/api/disc/requests", json={"ref": find(Ci, "ann.example@example.com").json()["person"]["ref"]})
check(r.ok and r.json()["state"] == "sent", "a blocked person can still 'send' (nothing tells them)")
check(news(An).count("connreq") == n and not An.get(B + "/api/disc").json()["incoming"], "but nothing reaches ann")
check(An.delete(B + f"/api/disc/blocks/{CID}").ok, "unblock")
check([x["person"]["id"] for x in An.get(B + "/api/disc").json()["incoming"]] == [CID], "after unblocking the request shows again")
check(An.post(B + f"/api/disc/blocks/{BOB}").json().get("unlinked") is True and "ann" not in seen(Bo), "blocking a connection ends it")
check(An.delete(B + f"/api/disc/blocks/{BOB}").ok and An.post(B + f"/api/disc/connections/{BOB}/restore").ok and "ann" in seen(Bo),
      "undo of that block: unblock + restore")

# ---- address book check
bk = Ci.post(B + "/api/contacts", json={"fn": "Contact Ann", "emails": [{"value": "ANN.example@example.com"}]})
check(bk.status_code == 201, f"cid adds contacts ({bk.text[:120]})")
for fn, v in (("Contact Dan", "dan@example.com"), ("Contact Nobody", "nobody@example.com"), ("Contact Kim", "kim@example.com"),
              ("Contact Bot", "bot@example.com"), ("Contact Eve", "eve@example.com")):
    Ci.post(B + "/api/contacts", json={"fn": fn, "emails": [{"value": v}]})
r = Ci.post(B + "/api/disc/check")
j = r.json()
check(r.ok and sorted(p["id"] for p in j["people"]) == sorted([ANN, EVE]) and j["checked"] == 6, f"the check finds only findable people ({j})")
check(all(set(p) == {"id", "name", "avatar", "ref", "state"} for p in j["people"]), "check hits carry no addresses")
q = dbx("SELECT checked FROM disc_quota WHERE user_id=?", (CID,))
check(q and q[0][0] == 6, f"every checked address counts ({q})")
check(Da.post(B + "/api/disc/check").json()["people"] == [], "dan has no contacts: nothing")

# ---- limits
dbx("DELETE FROM disc_quota", write=True)
for i in range(30):
    rr = find(Da, f"x{i}@example.com")
check(rr.status_code == 200, "30 searches a day are fine")
r = find(Da, "ann.example@example.com")
check(r.status_code == 429 and "enough" in r.json().get("error", ""), f"the 31st: 429 with a neutral message ({r.text[:120]})")
dbx("INSERT INTO disc_quota(user_id, day, searches, checked) VALUES(?,?,0,299)", (CID, time.strftime("%Y-%m-%d", time.gmtime())), write=True)
j = Ci.post(B + "/api/disc/check").json()
check(j["checked"] == 1 and j["skipped"] == 5, f"the check stops at the daily limit of addresses ({j})")
dbx("DELETE FROM disc_quota", write=True)

# ---- agents, kids, organisations, admins
r = requests.get(B + "/api/disc", headers={**H, "Authorization": f"Bearer {AGTOK}"})
check(r.status_code in (401, 403, 404), f"an agent token has no access ({r.status_code})")
r = requests.post(B + "/api/disc/find", headers={**H, "Authorization": f"Bearer {AGTOK}"}, json={"email": "ann.example@example.com"})
check(r.status_code in (401, 403, 404), f"an agent cannot search ({r.status_code})")
check(Ki.get(B + "/api/disc").status_code == 404 and find(Ki, "ann.example@example.com").status_code in (403, 404), "a kid account has no access")
check("dan" in seen(A) and "alice" in seen(Da) and "ann" not in seen(Da), "organisation members see each other as before, nobody else")
check(find(A, "cid@example.com").json() == {"person": None}, "an admin finds nobody who is not findable")
d = A.get(B + "/api/disc").json()
check(not d["incoming"] and not d["connections"] and not d["outgoing"], "an admin sees only their own requests")
r = A.get(B + "/api/users?all=1").json()
check(all("disc" not in json.dumps(u) for u in r["users"]), "the user management shows nothing of findability")

# ---- a changed address ends the findability; switching off removes it
check(A.patch(B + f"/api/users/{ANN}", json={"email": "ann.new@example.com"}).ok, "admin changes ann's address")
check(find(Bo, "ann.example@example.com").json() == {"person": None} and find(Bo, "ann.new@example.com").json() == {"person": None},
      "neither the old nor the new address finds ann until she confirms again")
check(An.get(B + "/api/disc").json()["profile"]["confirmed"] is False, "the profile says: not confirmed")
check(Ev.put(B + "/api/disc", json={"on": False}).ok and find(Bo, "eve@example.com").json() == {"person": None}, "switched off: not findable")
check("eve" in seen(Bo), "an existing connection stays when switching off")

# ---- the brake per client address (KALMIDO_DISC_PER_IP, here 200 per 15 minutes): searches and checks of every account
codes = [Ci.post(B + "/api/disc/check").status_code for _ in range(220)]
check(429 in codes and codes[-1] == 429, f"the brake per address stops searching from one address ({codes.count(200)} ok before)")
check(find(An, "bob@example.com").status_code == 429, "also for another account from the same address")

print(f"p249_e_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
