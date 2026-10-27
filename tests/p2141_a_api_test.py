#!/usr/bin/env python3
"""2.141.0 part A (#2141, #2138): the own mailbox of a workspace and sending from the e-mail filing, own container (start.sh)
with two stub mail servers inside (stub_mail.py: IMAP 1143 + SMTP 1025 = the server's fallback; a copy on IMAP 1144 + SMTP 1026).
The server has NO mailbox of its own here (no KALMIDO_IMAP_*): the workspace mailboxes work alone.
 - set up: an organisation's admins (members 403, others 404, agents 403), a person for the own private space; passwords
   sealed, never sent back ("set"), an empty field keeps them, another server needs them again; check = IMAP + SMTP login
   (wrong password = "auth", an internal port that is not allowed = "blocked"), errors as codes without the server's words
 - fetching: the mails of Alpha's mailbox land in Alpha only (client by sender, "Not assigned" with the admin who set it up,
   a hub token of another workspace counts as none, Alpha's own token files with its client, an answer to a sent mail joins
   its client), each Message-ID once, \\Seen; the freelancer's private mailbox files into the private space
 - sending: Reply (to the sender, "Re: ...", In-Reply-To / References) and a new mail from a client (suggested recipients),
   through the workspace's SMTP; filed with direction out; no SMTP in the workspace = the server's (sender = the server,
   Reply-To = the person); an SMTP that fails = 502 and the filed mail "failed"; bad recipients 400; other workspaces 404;
   agents 403 (tenant-matrix: hubmail)
usage: p2141_a_api_test.py <datadir>      (P2141A_NOSTART=1: the container runs already, only the stubs are started)"""
import email
import email.message
import email.policy
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess, until  # 2.192.0 (#2514): shared helpers (tests/kt.py)
ENV = ["-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none",
       "-e", "KALMIDO_MAIL_FROM=kalmido@example.test", "-e", "KALMIDO_IMAP_INTERVAL=600",
       "-e", "KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:1143,127.0.0.1:1144,127.0.0.1:1026,127.0.0.1:1027",
       "-e", "KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="]
FEAT = "cal,collab,comments,events,contacts,clients"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def js(r):
    try:
        return r.json()
    except ValueError:
        log = subprocess.run(["docker", "logs", "--tail", "40", CT], capture_output=True, text=True)
        print("NO JSON:", r.status_code, r.text[:300], "\n", log.stdout[-3000:], log.stderr[-3000:], flush=True)
        return {}


NEXT = {"mail": 0, "mail2": 0}


def mail(box, to, frm, subject, text, mid=None, reply_to_mid=None):
    """Drop one mail into the stub mailbox box ('mail' = Alpha's, 'mail2' = the freelancer's); returns its Message-ID."""
    NEXT[box] += 1
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m["Message-ID"] = mid or f"<p2141a-{box}-{NEXT[box]}@example.org>"
    if reply_to_mid:
        m["In-Reply-To"] = reply_to_mid
        m["References"] = reply_to_mid
    m["Date"] = "Tue, 20 Oct 2026 10:00:00 +0200"
    m.set_content(text)
    open(os.path.join(DATA, box, "in", f"{NEXT[box]}.eml"), "wb").write(bytes(m))
    return m["Message-ID"]


def row(mid):
    r = dbx("SELECT id, org_id, owner_id, client_id, list_id, ws, direction, send_state, eml_id FROM hub_mails WHERE message_id=?", (mid,))
    return dict(zip(("id", "org_id", "owner_id", "client_id", "list_id", "ws", "direction", "send_state", "eml_id"), r[0])) if r else None


def sent(box):
    """The mails the SMTP stub of box received (raw text parsed)."""
    p = os.path.join(DATA, box, "out.jsonl")
    out = []
    if os.path.exists(p):
        for ln in open(p):
            if ln.strip():
                x = json.loads(ln)
                out.append((x, email.message_from_string(x["raw"], policy=email.policy.default)))
    return out


# ---- setup: alice (instance admin), Alpha = bob (admin) + carol, Beta = dave, erin without an organisation (freelancer)
if not os.environ.get("P2141A_NOSTART"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
for d in ("mail", "mail2"):
    os.makedirs(os.path.join(DATA, d, "in"), exist_ok=True)
subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
src = open(os.path.join(N, "stub_mail.py")).read()
open(os.path.join(DATA, "stub_mail2.py"), "w").write(src.replace('"/data/mail"', '"/data/mail2"').replace("1143", "1144").replace("1025", "1026"))
if not os.environ.get("P2141A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(ENV)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail2.py"])
time.sleep(1.2)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
U = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    U[u] = r.json()["id"]
BOB, CAROL, DAVE = U["bob"], U["carol"], U["dave"]
ERIN, Er = freelancer(B, A, "erin")
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
ORG2 = r.json()["id"]
A.patch(B + f"/api/admin/orgs/{ORG}", json={"members": [BOB, CAROL], "admins": [BOB]})
A.patch(B + f"/api/admin/orgs/{ORG2}", json={"members": [DAVE], "admins": [DAVE]})
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id NOT IN (?)) OR user_id=?",
    (ORG, BOB, CAROL, ORG2, DAVE, ERIN), write=True)
r = A.post(B + "/api/admin/agents", json={"username": "bobbot", "display_name": "Bobbot"})
AG = requests.Session()
AG.headers.update({"Authorization": "Bearer " + (r.json().get("token") or "")})
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})

cols = {x[0] for x in dbx("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='hub_mails'")}
tabs = {x[0] for x in dbx("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='hub_mailboxes'")}
check(tabs == {"hub_mailboxes"} and {"direction", "send_state"} <= cols, f"the new table and columns ({tabs}, {sorted(cols)[:3]}...)")

ACME = Bo.post(B + "/api/clients", json={"name": "Acme", "org_id": ORG, "email": "acme@example.com",
                                         "contacts": [{"name": "Lisa", "email": "lisa@example.com"}]}).json()["id"]
OTHER = Bo.post(B + "/api/clients", json={"name": "Other", "org_id": ORG, "email": "other@example.com"}).json()["id"]
BETACO = Da.post(B + "/api/clients", json={"name": "BetaCo", "org_id": ORG2, "email": "betaco@example.com"}).json()["id"]
SOLO = Er.post(B + "/api/clients", json={"name": "Solo", "email": "solo@example.com"}).json()["id"]
r = Bo.post(B + "/api/lists", json={"name": "Launch", "org_id": ORG, "kind": "project"})
P = r.json()["id"]
Bo.patch(B + f"/api/lists/{P}", json={"client_id": ACME})

# ---- the settings (tenant-matrix: hubmail)
j = js(Bo.get(B + "/api/hubmail/mailboxes"))
sp = {x["ws"]: x for x in j.get("spaces", [])}
check(set(sp) == {"private", f"org:{ORG}"} and sp[f"org:{ORG}"]["manage"] and sp["private"]["manage"] and not sp[f"org:{ORG}"]["set"]
      and j.get("server_send") is True, f"bob: private + Alpha, both his to manage, nothing set ({j})")
j = js(Ca.get(B + "/api/hubmail/mailboxes"))
check({x["ws"]: x["manage"] for x in j.get("spaces", [])} == {"private": True, f"org:{ORG}": False}, f"carol: Alpha not hers to manage ({j})")
BOX = {"ws": f"org:{ORG}", "imap_host": "127.0.0.1", "imap_port": 1143, "imap_ssl": False, "imap_user": "kalmido", "imap_password": "secret",
       "smtp_host": "127.0.0.1", "smtp_port": 1026, "smtp_tls": "none", "from_addr": "office@example.test", "from_name": "Alpha Office"}
check(Ca.put(B + "/api/hubmail/mailbox", json=BOX).status_code == 403, "a member of Alpha (no admin): 403")
check(Da.put(B + "/api/hubmail/mailbox", json=BOX).status_code == 404, "an admin of another organisation: 404")
check(Da.get(B + f"/api/hubmail/mailbox?ws=org:{ORG}").status_code == 404, "another organisation cannot read it: 404")
check(AG.get(B + "/api/hubmail/mailboxes").status_code in (401, 403), "agents: no mailboxes")
check(AG.put(B + "/api/hubmail/mailbox", json={**BOX, "ws": "private"}).status_code in (401, 403), "agents: cannot set one up")
check(Bo.put(B + "/api/hubmail/mailbox", json={**BOX, "imap_password": ""}).status_code == 400, "a new IMAP mailbox needs its password")
check(Bo.put(B + "/api/hubmail/mailbox", json={**BOX, "from_addr": "nope"}).status_code == 400, "a sender address that is none: 400")
check(Bo.put(B + "/api/hubmail/mailbox", json={**BOX, "from_name": "A\r\nBcc: x@example.org"}).status_code == 400, "a line break in the sender name: 400")
check(Bo.put(B + "/api/hubmail/mailbox", json={**BOX, "imap_host": "bad host/"}).status_code == 400, "a server name that is none: 400")
check(Bo.put(B + "/api/hubmail/mailbox", json={**BOX, "smtp_tls": "maybe"}).status_code == 400, "an unknown TLS mode: 400")
check(Bo.put(B + "/api/hubmail/mailbox", json={**BOX, "evil": 1}).status_code == 400, "an unknown field: 400")
r = Bo.put(B + "/api/hubmail/mailbox", json={**BOX, "check": True})
j = js(r)
ch = j.get("check") or {}
check(r.ok and ch.get("imap", {}).get("ok") and ch.get("smtp", {}).get("ok"), f"Alpha's mailbox saved and checked: IMAP + SMTP log in ({r.status_code} {ch})")
b = j.get("box") or {}
check(b.get("imap_password_set") is True and b.get("from_addr") == "office@example.test" and "secret" not in r.text, f"the password is never sent back, only 'set' ({b})")
sec = dbx("SELECT secret FROM hub_mailboxes WHERE ws=?", (f"o{ORG}",))
check(sec and sec[0][0].startswith("v1.") and "secret" not in sec[0][0], "the passwords are sealed in the database")
check(not sent("mail2"), "the check sends no mail")
# an empty password keeps the stored one; another server needs it again; a wrong one = "auth" without the server's words
r = Bo.put(B + "/api/hubmail/mailbox", json={"ws": f"org:{ORG}", "from_name": "Alpha Team", "check": True})
check(r.ok and js(r)["check"]["imap"]["ok"] and js(r)["box"]["from_name"] == "Alpha Team", f"changed without the password: it stays and works ({r.text[:200]})")
check(Bo.put(B + "/api/hubmail/mailbox", json={"ws": f"org:{ORG}", "imap_port": 1144}).status_code == 400, "another port without the password again: 400 (the password only goes where it was entered)")
r = Bo.put(B + "/api/hubmail/mailbox", json={"ws": f"org:{ORG}", "imap_password": "wrong-pass", "check": True})
c1 = (js(r).get("check") or {}).get("imap") or {}
check(r.ok and c1.get("code") == "auth" and "wrong-pass" not in r.text and c1.get("text"), f"a wrong password: code auth with a text, no secret ({c1})")
check(dbx("SELECT error FROM hub_mailboxes WHERE ws=?", (f"o{ORG}",))[0][0] == "auth", "the error is stored as a code")
r = Bo.put(B + "/api/hubmail/mailbox", json={"ws": f"org:{ORG}", "imap_password": "secret", "check": True})
check(r.ok and js(r)["check"]["imap"]["ok"] and not js(r)["box"]["error"], "the right password again: works, the error is gone")
r = Bo.put(B + "/api/hubmail/mailbox", json={"ws": "private", "imap_host": "127.0.0.1", "imap_port": 22, "imap_ssl": False, "imap_user": "x",
                                              "imap_password": "y", "check": True})
check(r.ok and (js(r).get("check") or {}).get("imap", {}).get("code") == "blocked", f"an internal port nobody allowed: blocked ({r.text[:200]})")
check(Bo.delete(B + "/api/hubmail/mailbox?ws=private").ok and not dbx("SELECT 1 FROM hub_mailboxes WHERE ws=?", (f"u{BOB}",)), "bob removes his private mailbox")
# the freelancer: her own private mailbox (freelancer-matrix: hub)
r = Er.put(B + "/api/hubmail/mailbox", json={"ws": "private", "imap_host": "127.0.0.1", "imap_port": 1144, "imap_ssl": False, "imap_user": "kalmido",
                                              "imap_password": "secret", "smtp_host": "127.0.0.1", "smtp_port": 1026, "smtp_tls": "none",
                                              "from_addr": "erin@example.test", "check": True})
check(r.ok and js(r)["check"]["imap"]["ok"] and js(r)["check"]["smtp"]["ok"], f"freelancer: her own mailbox works ({r.text[:200]})")
check(dbx("SELECT org_id, owner_id FROM hub_mailboxes WHERE ws=?", (f"u{ERIN}",)) == [(None, ERIN)], "freelancer: stored as her private space's")
check(Er.put(B + "/api/hubmail/mailbox", json={**BOX}).status_code == 404, "freelancer: Alpha's mailbox is not hers (404)")

# ---- fetching
TOK_B, TOK_A = "betatoken000000000001", "alphatoken00000000001"
dbx("INSERT INTO hub_tokens(token,kind,user_id,org_id,client_id,created_at) VALUES(?,?,?,?,?,'2026-10-20T10:00:00+00:00'),(?,?,?,?,?,'2026-10-20T10:00:00+00:00')",
    (TOK_B, "client", DAVE, ORG2, BETACO, TOK_A, "client", BOB, ORG, OTHER), write=True)
M1 = mail("mail", "office@example.test", "Acme <acme@example.com>", "Offer spring", "Hello Alpha, the offer.")
M2 = mail("mail", "office@example.test", "Lisa <lisa@example.com>", "From the contact person", "Lisa writes.")
M3 = mail("mail", "office@example.test", "stranger@example.org", "Unknown sender", "Who am I?")
M4 = mail("mail", f"x+{TOK_B}@example.test", "betaco@example.com", "Beta's token in Alpha's mailbox", "Never into Beta.")
M5 = mail("mail", f"office+{TOK_A}@example.test", "someone@example.org", "Alpha's own token", "To the client Other.")
mail("mail", "office@example.test", "acme@example.com", "Double", "Again", mid=M1)
M8 = mail("mail2", "erin@example.test", "Solo <solo@example.com>", "Freelance job", "Private.")
check(Ca.post(B + "/api/hubmail/mailbox/poll", json={"ws": f"org:{ORG}"}).status_code == 403, "Fetch now: not for a member")
check(Bo.post(B + "/api/hubmail/mailbox/poll", json={"ws": f"org:{ORG}"}).ok, "Fetch now: bob")
check(Er.post(B + "/api/hubmail/mailbox/poll", json={"ws": "private"}).ok, "Fetch now: the freelancer")
check(until(lambda: len(dbx("SELECT id FROM hub_mails")) >= 6, 40), f"the mails were filed ({len(dbx('SELECT id FROM hub_mails'))})")
time.sleep(1)
R = {k: row(v) for k, v in {"m1": M1, "m2": M2, "m3": M3, "m4": M4, "m5": M5, "m8": M8}.items()}
check(R["m1"] and R["m1"]["client_id"] == ACME and R["m1"]["org_id"] == ORG and R["m1"]["owner_id"] == BOB and R["m1"]["ws"] == f"o{ORG}",
      f"the client's address -> Acme in Alpha, received by bob ({R['m1']})")
check(R["m2"] and R["m2"]["client_id"] == ACME, f"the contact person's address -> Acme ({R['m2']})")
check(R["m3"] and R["m3"]["client_id"] is None and R["m3"]["owner_id"] == BOB and R["m3"]["org_id"] == ORG, f"an unknown sender: Not assigned with bob in Alpha ({R['m3']})")
check(R["m4"] and R["m4"]["org_id"] == ORG and R["m4"]["client_id"] is None and not dbx("SELECT 1 FROM hub_mails WHERE org_id=?", (ORG2,)),
      f"Beta's token in Alpha's mailbox: stays in Alpha, never Beta ({R['m4']})")
check(R["m5"] and R["m5"]["client_id"] == OTHER and R["m5"]["org_id"] == ORG, f"Alpha's own token: the client Other ({R['m5']})")
check(len(dbx("SELECT id FROM hub_mails WHERE message_id=?", (M1,))) == 1, "the same Message-ID once")
check(R["m8"] and R["m8"]["client_id"] == SOLO and R["m8"]["org_id"] is None and R["m8"]["owner_id"] == ERIN and R["m8"]["ws"] == f"u{ERIN}",
      f"freelancer: her private client Solo ({R['m8']})")
check(all(r_ and r_["direction"] == "in" and r_["eml_id"] for r_ in R.values()), "received = direction in, the .eml filed")
seen = open(os.path.join(DATA, "mail", "seen")).read().split() if os.path.exists(os.path.join(DATA, "mail", "seen")) else []
check(len(seen) == 6, f"every fetched mail is marked seen ({seen})")
st = {x["ws"]: x for x in js(Bo.get(B + "/api/hubmail/mailboxes"))["spaces"]}
check(st[f"org:{ORG}"]["set"] and st[f"org:{ORG}"]["receive"] and st[f"org:{ORG}"]["send"] and st[f"org:{ORG}"]["polled_at"]
      and not st[f"org:{ORG}"]["error"], f"the list shows Alpha's mailbox fetched ({st[f'org:{ORG}']})")
check(Ca.get(B + f"/api/hubmail/mails/{R['m3']['id']}").status_code == 404, "carol does not see bob's Not assigned mail")
check(Da.get(B + f"/api/hubmail/mails/{R['m1']['id']}").status_code == 404, "Beta does not see Alpha's mail")

# ---- reply (through Alpha's SMTP, filed with Acme)
r = Bo.get(B + f"/api/hubmail/compose?reply={R['m1']['id']}")
j = js(r)
check(r.ok and j["can_send"] and j["via"] == "workspace" and j["from"]["address"] == "office@example.test" and j["from"]["name"] == "Alpha Team"
      and [x["address"] for x in j["to"]] == ["acme@example.com"] and j["subject"] == "Re: Offer spring" and "> Hello Alpha" in j["text"],
      f"compose a reply: sender, recipient, Re:, the quote ({j})")
check(Da.get(B + f"/api/hubmail/compose?reply={R['m1']['id']}").status_code == 404, "another organisation cannot answer it: 404")
check(Ca.get(B + f"/api/hubmail/compose?reply={R['m3']['id']}").status_code == 404, "carol cannot answer bob's Not assigned mail: 404")
r = Bo.post(B + "/api/hubmail/send", json={"reply": R["m1"]["id"], "to": "acme@example.com", "subject": j["subject"], "text": "Thanks!" + j["text"]})
j2 = js(r)
mo = j2.get("mail") or {}
check(r.status_code == 201 and mo.get("dir") == "out" and mo.get("state") == "" and mo.get("client_id") == ACME and j2.get("via") == "workspace",
      f"the reply went out and is filed with Acme ({r.status_code} {mo})")
out = sent("mail2")
check(len(out) == 1 and out[0][0]["to"] == ["acme@example.com"] and out[0][0]["from"] == "office@example.test", f"the workspace's SMTP sent it ({[o[0]['to'] for o in out]})")
msg = out[0][1] if out else None
check(msg is not None and msg["In-Reply-To"] == M1 and M1 in str(msg["References"]) and "Alpha Team" in str(msg["From"]) and msg["Subject"] == "Re: Offer spring",
      "In-Reply-To / References, sender name, subject")
SENT_MID = str(msg["Message-ID"]) if msg else ""
rs = row(SENT_MID)
check(rs and rs["direction"] == "out" and rs["send_state"] == "" and rs["client_id"] == ACME and rs["ws"] == f"o{ORG}" and rs["owner_id"] == BOB and rs["eml_id"],
      f"filed: direction out, Acme, the .eml in the file store ({rs})")
lst = js(Ca.get(B + f"/api/hubmail/mails?client_id={ACME}"))
srow = [m for m in lst.get("mails", []) if m["id"] == (rs or {}).get("id")]
check(srow and srow[0]["dir"] == "out" and "acme@example.com" in srow[0].get("to_list", "") and lst.get("can_send") is True,
      f"carol sees the sent mail in Acme's list, can write too ({srow})")
# 2.360.0 (#2496): an answer to the sent mail joins Acme (In-Reply-To) only from someone who took part in it; a new
# address with the known Message-ID waits in Not assigned
M9 = mail("mail", "office@example.test", "newperson@example.org", "Re: Re: Offer spring", "Agreed.", reply_to_mid=SENT_MID)
Bo.post(B + "/api/hubmail/mailbox/poll", json={"ws": f"org:{ORG}"})
r9 = until(lambda: row(M9), 40)
check(r9 and r9["client_id"] is None and r9["list_id"] is None and r9["org_id"] == ORG, f"an answer from a new address: Not assigned ({r9})")
M9b = mail("mail", "office@example.test", "Acme <acme@example.com>", "Re: Re: Offer spring", "Agreed too.", reply_to_mid=SENT_MID)
Bo.post(B + "/api/hubmail/mailbox/poll", json={"ws": f"org:{ORG}"})
r9b = until(lambda: row(M9b), 40)
check(r9b and r9b["client_id"] == ACME and r9b["org_id"] == ORG, f"an answer of a recipient is filed with Acme ({r9b})")
# 2.360.0 R (#2496, review): a known address of the client (the contact person, not a recipient of the sent mail) counts too
M9c = mail("mail", "office@example.test", "Lisa <lisa@example.com>", "Re: Re: Offer spring", "Lisa agrees.", reply_to_mid=SENT_MID)
Bo.post(B + "/api/hubmail/mailbox/poll", json={"ws": f"org:{ORG}"})
r9c = until(lambda: row(M9c), 40)
check(r9c and r9c["client_id"] == ACME and r9c["org_id"] == ORG, f"an answer of Acme's contact person is filed with Acme ({r9c})")

# ---- a new mail from a client, by carol (a member uses the workspace's SMTP)
j = js(Ca.get(B + f"/api/hubmail/compose?client_id={ACME}"))
sug = [x["address"] for x in j.get("suggest", [])]
check(j.get("can_send") and j.get("via") == "workspace" and sug[:2] == ["acme@example.com", "lisa@example.com"] and not j.get("to"),
      f"compose a new mail: suggested recipients from the client ({j})")
r = Ca.post(B + "/api/hubmail/send", json={"client_id": ACME, "to": "Lisa <lisa@example.com>", "cc": "acme@example.com", "subject": "Hello", "text": "New mail."})
check(r.status_code == 201 and js(r)["mail"]["client_id"] == ACME and js(r)["mail"]["dir"] == "out", f"carol sends a new mail ({r.status_code} {r.text[:200]})")
out = sent("mail2")
check(len(out) == 2 and sorted(out[1][0]["to"]) == ["acme@example.com", "lisa@example.com"] and not out[1][1]["In-Reply-To"], "To + Cc reached the SMTP, no In-Reply-To")
r = Bo.post(B + "/api/hubmail/send", json={"list_id": P, "to": "acme@example.com", "subject": "Project news", "text": "Launch."})
check(r.status_code == 201 and js(r)["mail"]["list_id"] == P and js(r)["mail"]["client_id"] == ACME, f"from the project: filed with the project + its client ({r.text[:200]})")
# bad requests
for bad, what in (({"client_id": ACME, "to": "not an address", "subject": "x", "text": "y"}, "a recipient that is none"),
                  ({"client_id": ACME, "to": "a@example.com\nBcc: b@example.com", "subject": "x", "text": "y"}, "a line break in the recipients"),
                  ({"client_id": ACME, "to": ", ".join(f"p{i}@example.com" for i in range(21)), "subject": "x", "text": "y"}, "21 recipients"),
                  ({"client_id": ACME, "to": "", "subject": "x", "text": "y"}, "no recipient"),
                  ({"client_id": ACME, "to": "a@example.com", "subject": "x", "text": "y", "bcc": "z@example.com"}, "an unknown field"),
                  ({"client_id": "x", "to": "a@example.com", "subject": "x", "text": "y"}, "a wrong id")):
    check(Bo.post(B + "/api/hubmail/send", json=bad).status_code == 400, f"400: {what}")
check(Da.post(B + "/api/hubmail/send", json={"client_id": ACME, "to": "a@example.com", "subject": "x", "text": "y"}).status_code == 404, "another organisation's client: 404")
check(Da.post(B + "/api/hubmail/send", json={"reply": R["m1"]["id"], "to": "a@example.com", "subject": "x", "text": "y"}).status_code == 404, "another organisation's mail: 404")
check(AG.post(B + "/api/hubmail/send", json={"client_id": ACME, "to": "a@example.com", "subject": "x", "text": "y"}).status_code in (401, 403), "agents cannot send")
check(len(sent("mail2")) == 3, "nothing else was sent")

# ---- the server's SMTP when the workspace has none: Beta (sender = the server, Reply-To = dave)
j = js(Da.get(B + f"/api/hubmail/compose?client_id={BETACO}"))
check(j.get("can_send") and j.get("via") == "server" and j.get("reply_to") == "dave@example.com" and j["from"]["address"] == "kalmido@example.test",
      f"Beta without a mailbox: the server's SMTP ({j})")
r = Da.post(B + "/api/hubmail/send", json={"client_id": BETACO, "to": "betaco@example.com", "subject": "From Beta", "text": "Hi."})
o1 = sent("mail")
check(r.status_code == 201 and o1 and o1[-1][0]["from"] == "kalmido@example.test" and o1[-1][1]["Reply-To"] == "dave@example.com"
      and "Dave" in str(o1[-1][1]["From"]), f"sent through the server: its address, Reply-To dave ({r.status_code})")

# ---- the freelancer sends from her private client through her own SMTP (freelancer-matrix: hub)
j = js(Er.get(B + f"/api/hubmail/compose?client_id={SOLO}"))
check(j.get("via") == "workspace" and j["from"]["address"] == "erin@example.test", f"freelancer: her own mailbox sends ({j})")
r = Er.post(B + "/api/hubmail/send", json={"reply": R["m8"]["id"], "to": "solo@example.com", "subject": "Re: Freelance job", "text": "Yes."})
check(r.status_code == 201 and js(r)["mail"]["client_id"] == SOLO and js(r)["mail"]["org_id"] is None, f"freelancer: the reply is filed in her space ({r.text[:200]})")
check(sent("mail2")[-1][0]["from"] == "erin@example.test", "freelancer: through her SMTP")
check(js(Er.get(B + f"/api/hubmail/mails?client_id={SOLO}")).get("can_send") is True, "freelancer: New e-mail in her client's list")
check(Er.get(B + f"/api/hubmail/compose?client_id={ACME}").status_code == 404, "freelancer: Alpha's client is not hers (404)")

# ---- an SMTP that fails: 502, the filed mail stays "failed" (no sent mail that was not)
Bo.put(B + "/api/hubmail/mailbox", json={"ws": f"org:{ORG}", "smtp_port": 1027})
n0 = len(sent("mail2"))
r = Bo.post(B + "/api/hubmail/send", json={"client_id": ACME, "to": "acme@example.com", "subject": "Will fail", "text": "x"})
j = js(r)
check(r.status_code == 502 and j.get("mail", {}).get("state") == "failed" and j.get("error") and "1027" not in j.get("error", ""),
      f"a failing SMTP: 502, the mail marked failed ({r.status_code} {j})")
rf = dbx("SELECT send_state, direction, note FROM hub_mails WHERE id=?", (j.get("mail", {}).get("id") or 0,))
check(rf and rf[0][0] == "failed" and rf[0][1] == "out" and rf[0][2], f"in the database: failed with a note ({rf})")
check(len(sent("mail2")) == n0, "nothing went out")
lst = js(Bo.get(B + f"/api/hubmail/mails?client_id={ACME}"))
check(any(m["state"] == "failed" for m in lst.get("mails", [])), "the list shows it as not sent")

# ---- removing the mailbox: the filed mails stay, sending falls back to the server
check(Ca.delete(B + f"/api/hubmail/mailbox?ws=org:{ORG}").status_code == 403, "a member cannot remove it")
check(Bo.delete(B + f"/api/hubmail/mailbox?ws=org:{ORG}").ok and not dbx("SELECT 1 FROM hub_mailboxes WHERE ws=?", (f"o{ORG}",)), "bob removes Alpha's mailbox")
check(dbx("SELECT 1 FROM hub_mails WHERE id=?", (R["m1"]["id"],)), "the filed mails stay")
check(js(Bo.get(B + f"/api/hubmail/compose?client_id={ACME}")).get("via") == "server", "without a mailbox the server's SMTP sends")
check(Bo.post(B + "/api/hubmail/mailbox/poll", json={"ws": f"org:{ORG}"}).status_code == 404, "Fetch now without a mailbox: 404")

print(f"p2141_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
