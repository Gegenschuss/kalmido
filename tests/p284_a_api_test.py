#!/usr/bin/env python3
"""2.84.0 part A (#1198): e-mail as an input of the hub -- mails filed with a client / project.
 - addresses: one per client (shared), per project, a hub inbox per person and workspace; only with the rights on the target
 - the mail input (the stub IMAP server of the tests, POST /api/admin/mail/poll): client / project address = fixed; the hub
   inbox matches the sender (client e-mail, contact person) inside the recipient's workspace only, a forwarded mail of the
   person themselves takes the sender of the forwarding header; no / unknown match = "Not assigned"; doubles dropped
 - texts sealed with the organisation's key; the .eml + attachments in the file store ("E-Mails / <client> / ..."), a virus
   find left out with a note, scanner gone = "unchecked"
 - visibility: client mail = who sees the client, project mail = who sees the list, not assigned = the recipient;
   another organisation, a person who left, agents: nothing (tenant-matrix: hubmail)
 - assign / delete / restore (the undo steps), search (hashed words)
usage: p284_a_api_test.py <datadir>      (a fresh container)"""
import email.message
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
MAILENV = ["-e", "KALMIDO_MAIL_ADDRESS=tasks@example.test", "-e", "KALMIDO_IMAP_HOST=127.0.0.1", "-e", "KALMIDO_IMAP_PORT=1143",
           "-e", "KALMIDO_IMAP_SSL=0", "-e", "KALMIDO_IMAP_USER=kalmido", "-e", "KALMIDO_IMAP_PASSWORD=secret", "-e", "KALMIDO_IMAP_INTERVAL=600",
           "-e", "KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
           "-e", "KALMIDO_CLAMD=127.0.0.1:3310", "-e", "KALMIDO_CLAMD_DOWN_S=1", "-e", "KALMIDO_CLAMD_TICK_S=1"]
FEAT = "cal,collab,comments,events,contacts,clients"
EICAR = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def until(fn, secs=40):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


NEXT = [0]


def mail(to, frm, subject, text, mid=None, files=(), cc=None):
    """Drop one mail into the stub mailbox; returns its Message-ID."""
    NEXT[0] += 1
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    if cc:
        m["Cc"] = cc
    m["Message-ID"] = mid or f"<hub-{NEXT[0]}@example.com>"
    m["Date"] = "Fri, 16 Oct 2026 10:00:00 +0200"
    m.set_content(text)
    for name, data, sub in files:
        if isinstance(data, str):
            m.add_attachment(data, subtype=sub, filename=name, cte="7bit")
        else:
            m.add_attachment(data, maintype="application", subtype=sub, filename=name)
    open(os.path.join(DATA, "mail", "in", f"{NEXT[0]}.eml"), "wb").write(bytes(m))
    return m["Message-ID"]


def poll(n_expected, secs=40):
    A.post(B + "/api/admin/mail/poll")
    return until(lambda: len(dbx("SELECT id FROM hub_mails")) >= n_expected, secs)


def row(mid):
    r = dbx("SELECT id, org_id, owner_id, client_id, list_id, subject, from_addr, folder_id, files, eml_id, note FROM hub_mails WHERE message_id=?", (mid,))
    return dict(zip(("id", "org_id", "owner_id", "client_id", "list_id", "subject", "from_addr", "folder_id", "files", "eml_id", "note"), r[0])) if r else None


def js(r):
    """r.json(), or the status, the text and the server's last log lines when it is no JSON (a 500)."""
    try:
        return r.json()
    except ValueError:
        log = subprocess.run(["docker", "logs", "--tail", "40", CT], capture_output=True, text=True)
        print("NO JSON:", r.status_code, r.text[:300], "\n", log.stdout[-3000:], log.stderr[-3000:], flush=True)
        return {}


def ids(s, **params):
    r = s.get(B + "/api/hubmail/mails", params=params)
    return [m["id"] for m in js(r).get("mails", [])] if r.ok else r.status_code


def addr(s, **b):
    r = s.post(B + "/api/hubmail/address", json=b)
    return r.json().get("address") if r.ok else r.status_code


# ---- setup: alice (admin), Alpha = bob (admin) + carol, Beta = dave, erin alone (freelancer, no organisation)
subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
subprocess.run(["rm", "-rf", DATA])
os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
for f in ("stub_mail.py", "fake_clamd.py"):
    subprocess.run(["cp", os.path.join(N, f), DATA])
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA],
                   env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)), capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_clamd.py"])
time.sleep(1.2)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
U = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    U[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = U["bob"], U["carol"], U["dave"], U["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
check(A.patch(B + f"/api/admin/orgs/{ORG}", json={"members": [BOB, CAROL], "admins": [BOB]}).ok, "setup: Alpha members")
A.patch(B + f"/api/admin/orgs/{ORG2}", json={"members": [DAVE], "admins": [DAVE]})
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id NOT IN (?)) OR user_id=?",
    (ORG, BOB, CAROL, ORG2, DAVE, ERIN), write=True)
r = A.post(B + "/api/admin/agents", json={"username": "bobbot", "display_name": "Bobbot"})
AGT = r.json().get("token") or ""
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})
AG = requests.Session()
AG.headers.update({"Authorization": "Bearer " + AGT})

cols = dbx("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name LIKE 'hub\\_%'")
check({x[0] for x in cols} >= {"hub_tokens", "hub_mails", "hub_words"}, f"the new tables ({sorted(x[0] for x in cols)})")

ACME = Bo.post(B + "/api/clients", json={"name": "Acme", "org_id": ORG, "email": "acme@example.com",
                                         "contacts": [{"name": "Lisa", "email": "lisa@example.com"}]}).json()["id"]
OTHER = Bo.post(B + "/api/clients", json={"name": "Other", "org_id": ORG, "email": "other@example.com"}).json()["id"]
PRIVB = Bo.post(B + "/api/clients", json={"name": "Bob private", "org_id": None, "email": "pb@example.com"}).json()["id"]
BETACO = Da.post(B + "/api/clients", json={"name": "BetaCo", "org_id": ORG2, "email": "acme@example.com"}).json()["id"]  # the same address
SOLO = Er.post(B + "/api/clients", json={"name": "Solo", "email": "solo@example.com"}).json()["id"]
r = Bo.post(B + "/api/lists", json={"name": "Launch", "org_id": ORG, "kind": "project"})
assert r.ok, r.text
P = r.json()["id"]
check(Bo.patch(B + f"/api/lists/{P}", json={"client_id": ACME}).ok, "setup: project Launch belongs to Acme")
PLAIN = Bo.post(B + "/api/lists", json={"name": "Plain", "org_id": ORG}).json()["id"]

# ---- addresses (tenant-matrix: hubmail)
r = Bo.get(B + "/api/hubmail/inbox")
check(r.ok and r.json()["enabled"] and {x["ws"] for x in r.json()["spaces"]} == {"private", f"org:{ORG}"}, f"inbox: private + Alpha ({r.text[:200]})")
check({x["ws"] for x in Er.get(B + "/api/hubmail/inbox").json()["spaces"]} == {"private"}, "freelancer: the private space only")
IN_B = addr(Bo, ws=f"org:{ORG}")
check(isinstance(IN_B, str) and IN_B.startswith("tasks+") and IN_B.endswith("@example.test"), f"bob's Alpha inbox address ({IN_B})")
check(addr(Bo, ws=f"org:{ORG}") == IN_B, "asking again keeps the address")
check(addr(Bo, ws=f"org:{ORG2}") == 404, "no inbox address in a foreign organisation")
IN_C = addr(Ca, ws=f"org:{ORG}")
IN_D = addr(Da, ws=f"org:{ORG2}")
IN_E = addr(Er, ws="private")
A_ACME = addr(Bo, client_id=ACME)
check(isinstance(A_ACME, str) and A_ACME != IN_B, "the client's address")
check(addr(Ca, client_id=ACME) == A_ACME, "one address per client: carol gets the same")
check(addr(Da, client_id=ACME) == 404, "another organisation: no address of the client")
check(addr(Ca, client_id=PRIVB) == 404, "a private client of another person: 404")
A_P = addr(Bo, list_id=P)
check(isinstance(A_P, str), "the project's address")
check(addr(Ca, list_id=P) == 404, "a project carol does not see: 404")
check(addr(Bo, list_id=PLAIN) == 409, "a plain list has no address")
check(Bo.post(B + "/api/hubmail/address", json={"client_id": "x"}).status_code == 400, "a wrong id: 400")
check(AG.get(B + "/api/hubmail/inbox").status_code in (401, 403), "agents: no hub mails")
check(AG.post(B + "/api/hubmail/address", json={"ws": "private"}).status_code in (401, 403), "agents: no address")

# ---- the mail input
M1 = mail(IN_B, "Lisa <lisa@example.com>", "Angebot Fruehjahr", "Hallo Bob, anbei das Angebot.", files=[("brief.txt", b"offer text", "octet-stream")])
FWD = ("Siehe unten.\n\n---------- Forwarded message ---------\nFrom: Acme Sales <acme@example.com>\nDate: Thu, 15 Oct 2026\n"
       "Subject: Rechnung 17\nTo: bob@example.com\n\nDie Rechnung kommt morgen.")
M2 = mail(IN_B, "Bob <bob@example.com>", "WG: Rechnung 17", FWD)
M3 = mail(IN_B, "stranger@example.org", "Unknown sender", "Wer bin ich?")
M4 = mail(A_ACME, "anyone@example.org", "Direct to Acme", "Kundenadresse.")
M5 = mail(A_P, "anyone@example.org", "Project mail", "Zum Launch.")
mail(IN_B, "anyone@example.org", "Double", "Again", mid=M4)  # the same Message-ID in the same workspace
M7 = mail(A_ACME, "x@example.org", "With a virus", "Careful", files=[("evil.txt", EICAR, "plain"), ("ok.txt", "fine", "plain")])
M8 = mail(IN_E, "Solo <solo@example.com>", "Freelance", "Privat.")
M9 = mail(IN_D, "acme@example.com", "Forged Acme", "Gefälscht?")  # dave's inbox: only Beta's clients count
M10 = mail(IN_B, "Mixed <mixed@example.org>", "Two clients", "Cc both", cc="acme@example.com")  # sender unknown -> not assigned
M11 = mail("tasks+guessedtoken0000@example.test", "a@example.org", "Guessed", "Nobody")
check(poll(9), f"the mails were filed ({len(dbx('SELECT id FROM hub_mails'))})")
time.sleep(1)
R = {k: row(v) for k, v in {"m1": M1, "m2": M2, "m3": M3, "m4": M4, "m5": M5, "m7": M7, "m8": M8, "m9": M9, "m10": M10, "m11": M11}.items()}
check(R["m1"] and R["m1"]["client_id"] == ACME and R["m1"]["org_id"] == ORG and R["m1"]["owner_id"] == BOB, f"inbox: a contact person's mail -> Acme ({R['m1']})")
check(R["m2"] and R["m2"]["client_id"] == ACME, f"a forwarded mail of bob himself: the original sender counts ({R['m2']})")
check(R["m3"] and R["m3"]["client_id"] is None and R["m3"]["list_id"] is None, "an unknown sender: not assigned")
check(R["m4"] and R["m4"]["client_id"] == ACME, "the client's address: filed with the client")
check(R["m5"] and R["m5"]["list_id"] == P and R["m5"]["client_id"] == ACME, "the project's address: the project and its client")
check(len(dbx("SELECT id FROM hub_mails WHERE message_id=?", (M4,))) == 1, "a double is dropped")
check(R["m8"] and R["m8"]["client_id"] == SOLO and R["m8"]["org_id"] is None, "freelancer: the private client")
check(R["m9"] and R["m9"]["client_id"] == BETACO and R["m9"]["org_id"] == ORG2, "a forged sender only finds a client of the recipient's workspace")
check(R["m11"] is None, "a guessed token files nothing")
check(not dbx("SELECT id FROM tasks WHERE tt_id LIKE 'mail:%'"), "no task from a hub mail")
check(str(R["m1"]["subject"]).startswith("kenc1:") and str(R["m1"]["from_addr"]).startswith("kenc1:"), "texts sealed with the organisation's key")
check(not str(R["m8"]["subject"]).startswith("kenc1:"), "a private mail stays like the private texts")
d = Bo.get(B + f"/api/hubmail/mails/{R['m2']['id']}").json()
check(d.get("subject") == "Rechnung 17" and d.get("from_addr") == "acme@example.com", f"forwarded: subject without WG:, original sender ({d.get('subject')}, {d.get('from_addr')})")

# attachments in the file store
d = Bo.get(B + f"/api/hubmail/mails/{R['m1']['id']}").json()
names = {a["name"] for a in d.get("attachments", [])}
check("brief.txt" in names and any(n.endswith(".eml") for n in names), f"the .eml and the attachment ({names})")
chain = dbx("SELECT f.name, p.name, r.name FROM fs_nodes f JOIN fs_nodes p ON p.id=f.parent_id JOIN fs_nodes r ON r.id=p.parent_id WHERE f.id=?", (R["m1"]["folder_id"],))
check(chain and chain[0][1] == "Acme" and chain[0][2] == "E-Mails" and chain[0][0].startswith("2026-10-16 "), f"the folder E-Mails / Acme / <date> <subject> ({chain})")
check(d.get("folder_id") == R["m1"]["folder_id"], "bob sees the folder in the file store")
att = next(a for a in d["attachments"] if a["name"] == "brief.txt")
r = Ca.get(B + f"/api/hubmail/mails/{R['m1']['id']}/files/{att['id']}", params={"dl": 1})
check(r.ok and r.content == b"offer text", f"carol (sees the client) downloads the attachment ({r.status_code})")
check(Da.get(B + f"/api/hubmail/mails/{R['m1']['id']}/files/{att['id']}").status_code == 404, "dave: 404 on the attachment")
other = dbx("SELECT id FROM fs_nodes WHERE kind='file' AND id<>? ORDER BY id LIMIT 1", (att["id"],))[0][0]
check(Bo.get(B + f"/api/hubmail/mails/{R['m1']['id']}/files/{R['m8']['eml_id'] or other}").status_code == 404, "a file of another mail: 404")
d7 = Bo.get(B + f"/api/hubmail/mails/{R['m7']['id']}").json()
n7 = {a["name"] for a in d7.get("attachments", [])}
check("ok.txt" in n7 and "evil.txt" not in n7, f"a virus find is left out, the rest stays ({n7})")
check("virus" in (d7.get("note") or ""), f"the note names the find ({d7.get('note')})")
# scanner gone: the attachment comes in "unchecked"
open(os.path.join(DATA, "clamd.off"), "w").close()
time.sleep(1.5)
M12 = mail(A_ACME, "x@example.org", "Unchecked", "Scanner down", files=[("later.txt", b"later", "octet-stream")])
check(poll(10), "the mail with the scanner gone was filed")
time.sleep(0.5)
d12 = Bo.get(B + f"/api/hubmail/mails/{row(M12)['id']}").json()
check(any(a["name"] == "later.txt" and a["scan"] == "unchecked" for a in d12.get("attachments", [])), f"scanner gone: unchecked ({d12.get('attachments')})")

# ---- visibility (tenant-matrix: hubmail)
acme_b = ids(Bo, client_id=ACME)
check(set(acme_b) >= {R[k]["id"] for k in ("m1", "m2", "m4", "m7")} and R["m5"]["id"] in acme_b, "bob sees Acme's mails incl. the project mail")
acme_c = ids(Ca, client_id=ACME)
check(R["m1"]["id"] in acme_c and R["m5"]["id"] not in acme_c, "carol sees the client's mails, not the project's (list not shared)")
check(Ca.get(B + f"/api/hubmail/mails/{R['m5']['id']}").status_code == 404, "carol: 404 on the project mail")
check(ids(Da, client_id=ACME) == 404, "dave: 404 on Acme's mails")
check(Da.get(B + f"/api/hubmail/mails/{R['m1']['id']}").status_code == 404, "dave: 404 on a mail of Alpha")
check(ids(Ca, list_id=P) == 404, "carol: 404 on the project's mails")
check(ids(Bo, list_id=P) == [R["m5"]["id"]], "bob: the project's mails")
inb = [m["id"] for m in Bo.get(B + "/api/hubmail/inbox").json()["mails"]]
check(R["m3"]["id"] in inb and R["m10"]["id"] in inb, "not assigned: in bob's inbox")
check(R["m3"]["id"] not in [m["id"] for m in Ca.get(B + "/api/hubmail/inbox").json()["mails"]], "not assigned: never in carol's")
check(Ca.get(B + f"/api/hubmail/mails/{R['m3']['id']}").status_code == 404, "carol: 404 on bob's unassigned mail")
check(ids(Er, client_id=SOLO) == [R["m8"]["id"]] and ids(Bo, client_id=SOLO) == 404, "a private client's mails: only its creator")
check(R["m9"]["id"] in ids(Da, client_id=BETACO), "dave sees the mail at BetaCo")
check(AG.get(B + f"/api/hubmail/mails/{R['m1']['id']}").status_code in (401, 403), "agents: no mail")

# ---- search
check(ids(Bo, client_id=ACME, q="Angebot") == [R["m1"]["id"]], "search: a word of the subject")
check(ids(Bo, client_id=ACME, q="lisa") == [R["m1"]["id"]], "search: the sender")
check(ids(Bo, client_id=ACME, q="Rechn") == [R["m2"]["id"]], "search: a prefix of the text")
check(ids(Bo, client_id=ACME, q="nothingsuch") == [], "search: no hit")
check(ids(Da, client_id=BETACO, q="Angebot") == [], "search: never another workspace's mail")

# ---- assign / undo, delete / restore
m3 = R["m3"]["id"]
r = Bo.post(B + f"/api/hubmail/mails/{m3}/assign", json={"client_id": ACME})
check(r.ok and r.json()["prev"] == {"client_id": None, "list_id": None} and r.json()["mail"]["client_id"] == ACME, f"assign to Acme ({r.text[:200]})")
check(m3 in ids(Ca, client_id=ACME), "carol sees the assigned mail")
fold = dbx("SELECT p.name FROM fs_nodes f JOIN fs_nodes p ON p.id=f.parent_id WHERE f.id=?", (R["m3"]["folder_id"],))
check(fold and fold[0][0] == "Acme", f"the folder moved along ({fold})")
check(Ca.post(B + f"/api/hubmail/mails/{m3}/assign", json={}).status_code == 403, "only the recipient takes it back to Not assigned")
check(Bo.post(B + f"/api/hubmail/mails/{m3}/assign", json={}).ok, "undo: back to Not assigned")
check(m3 not in ids(Ca, client_id=ACME), "carol no longer sees it")
check(Bo.post(B + f"/api/hubmail/mails/{m3}/assign", json={"client_id": BETACO}).status_code == 404, "a client of another organisation: 404")
check(Bo.post(B + f"/api/hubmail/mails/{m3}/assign", json={"client_id": PRIVB}).status_code == 409, "a private client for an Alpha mail: 409")
check(Bo.post(B + f"/api/hubmail/mails/{m3}/assign", json={"list_id": PLAIN}).status_code == 409, "a plain list: 409")
check(Ca.post(B + f"/api/hubmail/mails/{R['m1']['id']}/assign", json={"list_id": P}).status_code == 404, "a project carol does not see: 404")
r = Bo.post(B + f"/api/hubmail/mails/{m3}/assign", json={"list_id": P})
check(r.ok and r.json()["mail"]["client_id"] == ACME, "a project brings its client")
t = js(Bo.get(B + "/api/hubmail/targets", params={"mail": R["m1"]["id"]}))
check({x["id"] for x in t.get("clients", [])} == {ACME, OTHER} and [x["id"] for x in t.get("projects", [])] == [P], f"targets: Alpha's clients + projects only ({t})")
check(Da.get(B + "/api/hubmail/targets", params={"mail": R["m1"]["id"]}).status_code == 404, "targets of a foreign mail: 404")
m4 = R["m4"]["id"]
check(Da.delete(B + f"/api/hubmail/mails/{m4}").status_code == 404, "dave cannot delete")
check(Ca.delete(B + f"/api/hubmail/mails/{m4}").ok, "carol deletes a client mail")
check(m4 not in ids(Bo, client_id=ACME), "deleted: gone for bob too")
check(Ca.post(B + f"/api/hubmail/mails/{m4}/restore").ok and m4 in ids(Bo, client_id=ACME), "undo: restored")

# ---- the boundary: a mail bound to a client of another workspace is shown nowhere and repaired
dbx("UPDATE hub_mails SET client_id=? WHERE id=?", (BETACO, m4), write=True)
check(m4 not in ids(Da, client_id=BETACO) and m4 not in ids(Bo, client_id=ACME), "a cross-workspace binding is shown nowhere")
r = A.post(B + "/api/admin/orgs/boundary/repair")
check(r.ok and not dbx("SELECT client_id FROM hub_mails WHERE id=?", (m4,))[0][0], f"repair takes the binding off ({r.status_code} {r.text[:200]})")
dbx("UPDATE hub_mails SET client_id=? WHERE id=?", (ACME, m4), write=True)

# ---- leaving the organisation: carol sees nothing, her Alpha inbox files nothing
check(A.patch(B + f"/api/admin/orgs/{ORG}", json={"members": [BOB], "admins": [BOB]}).ok, "carol leaves Alpha")
time.sleep(2.2)  # the access context cache of background work (2 s)
check(ids(Ca, client_id=ACME) == 404, "after leaving: no client mails")
check(Ca.get(B + f"/api/hubmail/mails/{R['m1']['id']}").status_code == 404, "after leaving: 404 on a mail")
n0 = len(dbx("SELECT id FROM hub_mails"))
mail(IN_C, "lisa@example.com", "After leaving", "Nothing")
A.post(B + "/api/admin/mail/poll")
time.sleep(4)
check(len(dbx("SELECT id FROM hub_mails")) == n0, "the inbox of a person who left files nothing")

# ---- a new address: the old one stops
NEW = Bo.post(B + "/api/hubmail/address", json={"client_id": ACME, "renew": True}).json()["address"]
check(NEW != A_ACME, "renew: a new address")
OLD = mail(A_ACME, "a@example.org", "Old address", "x")
A.post(B + "/api/admin/mail/poll")
time.sleep(4)
check(row(OLD) is None, "the old address files nothing")
check(Bo.delete(B + "/api/hubmail/address", params={"client_id": ACME}).ok and not dbx("SELECT 1 FROM hub_tokens WHERE client_id=?", (ACME,)), "turn the address off")

# ---- deleting an account: its private filed mails go, an organisation's client mails stay
r = A.delete(B + f"/api/users/{ERIN}")
check(r.ok and not dbx("SELECT 1 FROM hub_mails WHERE id=?", (R["m8"]["id"],)), f"erin deleted: her private mail is gone ({r.status_code})")
check(dbx("SELECT 1 FROM hub_mails WHERE id=?", (R["m1"]["id"],)), "an organisation's client mail is untouched")

print(f"p284_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
