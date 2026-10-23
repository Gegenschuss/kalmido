#!/usr/bin/env python3
"""2.152.0 API tests, part A (#2164 deleting an account, #2167 deleting an organisation), own container (start.sh, mode
workspaces). Invented people, companies and addresses only (example.com).
tenant-matrix: org
freelancer-matrix: orgadmin
 - a person without an organisation (freelancer) whose personal office keeps nothing by law: the account's deletion removes
   the office row, its folder (logo) and the files of the own file store from the disk
 - a freelancer with a finalised invoice in the personal office: the deletion retires the office (kept until the end of the
   tenth year), the account goes; the document stays, nobody sees the office in the app, the instance admin sees "kept
   until" in the organisations list and may export it, never change or delete it before the date
 - a member of an organisation: time entries in the organisation's projects stay (no person), the organisation calendar goes
   to an admin of the organisation, the own agent goes with its token (401), the direct conversation stays for the
   partner, mentions become "@Deleted user", log rows lose the id; the delete dialog's info names all of it
 - an organisation with a knowledge page: 409 with the numbers, gone with ?confirm=1
 - an organisation with a finalised invoice: retired with ?confirm=1 (members out, the document stays); the retention run
   after the period only counts while the switch is off and deletes it (with the office folder) when it is on
usage: p2103_a_api_test.py <datadir>      (P2103A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import io
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,fields,events,files,docs,time,office,wiki,clients"  # 2.152.0 review A2: + docs (receipts)
O = "/api/office"
KEYENV = " -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY=" + "A" * 43 + "="


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


def app_log():
    out = subprocess.run(["docker", "logs", "--tail", "400", CT], capture_output=True, text=True)
    text = out.stdout + out.stderr
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


def picture():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (300, 100), (47, 93, 138)).save(out, "PNG")
    return out.getvalue()


def office_dir(oid):
    return os.path.join(DATA, "office", str(oid))


def lock_doc(did, day="2026-03-02", number="RE-2026-001"):
    """A finalised document (the state the finalising leaves; finalising itself is tested in the office suites)."""
    sql("UPDATE office_docs SET locked_at=?, status='issued', number=?, date=? WHERE id=?",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), number, day, did), write=True)


def run_prune(purge):
    env = ["-e", "KALMIDO_RETENTION_PURGE=1"] if purge else []
    out = subprocess.run(["docker", "exec", *env, CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nfrom kalmido.accounts.orgretain import odl_retired_prune\n"
                          "c = connect()\nprint('purged', odl_retired_prune(c, True))\nc.close()"], capture_output=True, text=True)
    return out.stdout + out.stderr


if os.environ.get("P2103A_NOSTART") != "1":
    # 2.152.0 (#2167, review A4): with the server key (the organisation export needs it)
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces" + KEYENV)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Owner"), ("carol", "Carol Member")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/me").json()["id"]
Bo, Ca = sess("bob"), sess("carol")
BOB, CAROL = Bo.get(B + "/api/me").json()["id"], Ca.get(B + "/api/me").json()["id"]
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ALICE}).json()["id"]
for e in ("bob@example.com", "carol@example.com"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": e, "role": "member"}).ok
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2})

# ================================================================== #2164 a freelancer: the personal office goes with its files
FIO, Fi = freelancer(B, A, "fiona")
r = Fi.get(B + O + "/settings")
PF = r.json().get("org_id") if r.ok else None
check(r.ok and r.json().get("personal") == 1 and PF, "fiona: the own personal office " + r.text[:160])
r = Fi.post(B + O + "/logo", files={"file": ("logo.png", picture(), "image/png")})
check(r.ok and os.path.isdir(office_dir(PF)), "fiona: the office logo lies in the office folder " + r.text[:160])
r = Fi.post(B + O + "/docs", json={"project_title": "Imagefilm draft"})
check(r.status_code == 201, "fiona: a draft quotation " + r.text[:160])
r = Fi.post(B + "/api/files/upload", files={"file": ("notes.txt", b"call the client\n" * 20)})
check(r.ok, "fiona: a file in the own file store " + r.text[:160])
FPATHS = [os.path.join(DATA, "attachments", p[0]) for p in sql(
    "SELECT v.path FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id WHERE n.owner_id=?", (FIO,))]
check(FPATHS and all(os.path.exists(p) for p in FPATHS), f"fiona: the stored file is on the disk {FPATHS}")
info = A.get(B + f"/api/users/{FIO}/delete-info").json()
p = info.get("purge") or {}
check(p.get("office") == "delete" and p.get("office_counts", {}).get("office_documents") == 1 and not p.get("kept_until"),
      f"delete-info: the personal office goes with 1 document {p}")
r = A.delete(B + f"/api/users/{FIO}")
check(r.ok, "fiona deleted " + r.text[:200])
if not r.ok:
    app_log()
check(not sql("SELECT 1 FROM orgs WHERE id=?", (PF,)) and not sql("SELECT 1 FROM office_docs WHERE org_id=?", (PF,)), "fiona: the personal office row and its documents are gone")
check(not os.path.exists(office_dir(PF)), "fiona: the office folder (logo) is gone from the disk")
check(not any(os.path.exists(p) for p in FPATHS), "fiona: the file store's file is gone from the disk")

# ================================================================== #2164 P4: a freelancer with a finalised invoice -> retired
FRI, Fr = freelancer(B, A, "frida")
PR = Fr.get(B + O + "/settings").json().get("org_id")
Fr.post(B + O + "/logo", files={"file": ("logo.png", picture(), "image/png")})
r = Fr.post(B + O + "/docs", json={"project_title": "Corporate film"})
DOC = r.json().get("id") if r.status_code == 201 else None
check(DOC, "frida: a document " + r.text[:160])
lock_doc(DOC)
info = A.get(B + f"/api/users/{FRI}/delete-info").json()
p = info.get("purge") or {}
check(p.get("office") == "keep" and p.get("kept_until") == "2036-12-31" and p.get("kept", {}).get("documents") == 1,
      f"delete-info: the personal office keeps 1 document until 2036-12-31 {p}")
# 2.186.0 A (#2599): the office is retired (its records stay): no retention step, no waiver noted
check(info.get("retention", {}).get("state") == "retire", f"delete-info: the records are retired {info.get('retention')}")
r = A.delete(B + f"/api/users/{FRI}")
check(r.ok, "frida deleted " + r.text[:200])
check(not sql("SELECT 1 FROM retention_log WHERE subject=?", (f"user:{FRI}",)), "frida: no waiver noted (retired)")
if not r.ok:
    app_log()
row = sql("SELECT personal_of, retired_at IS NOT NULL, retain_until, retired_personal, name FROM orgs WHERE id=?", (PR,))
check(row and row[0][0] is None and row[0][1] and row[0][2] == "2036-12-31" and row[0][3] == 1 and row[0][4] == "Frida",
      f"frida: the personal office is retired until 2036-12-31 {row}")
check(not sql("SELECT 1 FROM users WHERE id=?", (FRI,)), "frida: the account itself is gone")
check(sql("SELECT number FROM office_docs WHERE id=?", (DOC,)) == [("RE-2026-001",)], "frida: the finalised invoice is kept")
check(os.path.isdir(office_dir(PR)), "frida: the office folder (logo) is kept")
check(not sql("SELECT 1 FROM org_members WHERE org_id=?", (PR,)), "retired: nobody is a member")
orgs = {o["id"]: o for o in A.get(B + "/api/admin/orgs").json()["orgs"]}
check(PR in orgs and orgs[PR]["retain_until"] == "2036-12-31" and orgs[PR]["retired_personal"] is True and orgs[PR]["retired_at"],
      f"instance admin: the organisations list shows it with 'kept until' {orgs.get(PR)}")
check(all(w.get("id") != PR for w in (Bo.get(B + "/api/me").json().get("workspaces") or [])), "bob: not among his workspaces")
check(Bo.get(B + f"/api/orgs/{PR}/export").status_code in (403, 404), "bob: no export of it")
check(Bo.get(B + "/api/admin/orgs").status_code == 403, "bob: no admin list")
# 2.152.0 (#2164, review A4): the retired office of a deleted person is private: no instance admin exports it
check(A.get(B + f"/api/orgs/{PR}/export").status_code in (403, 404) and A.post(B + f"/api/orgs/{PR}/export").status_code in (403, 404),
      "instance admin: no export of the retired office of a deleted person")
r = A.delete(B + f"/api/admin/orgs/{PR}?confirm=1")
check(r.status_code == 409 and "2036-12-31" in r.text, "retired: not deleted before the period ends " + r.text[:160])
check(A.patch(B + f"/api/admin/orgs/{PR}", json={"name": "Taken over"}).status_code == 409, "retired: no change (read only)")
di = A.get(B + f"/api/admin/orgs/{PR}/delete-info").json()
check(di.get("retired") is True and di.get("kept_until") == "2036-12-31" and di.get("can_export") is False, f"delete-info of the retired office {di}")  # 2.152.0 (#2164): review A4
r = A.put(B + f"/api/orgs/{PR}/members", json={"email": "bob@example.com", "role": "member"})
check(r.status_code in (403, 404), "retired: nobody can be added as a member " + str(r.status_code))

# ================================================================== #2164 an organisation member: what stays, what goes
PL = Bo.post(B + "/api/lists", json={"name": "Spring campaign", "org_id": ORG, "kind": "project"}).json()["id"]
check(Bo.put(B + f"/api/lists/{PL}/members", json={"user_id": CAROL, "role": "edit"}).ok, "setup: carol in bob's project")
day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
CINBOX = sql("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (CAROL,))[0][0]
sql("UPDATE lists SET time_tracking=1 WHERE id IN (?, ?)", (PL, CINBOX), write=True)  # the list setting (tested in the time suites)
r = Ca.post(B + "/api/time/entries", json={"list_id": PL, "start": day + "T09:00", "minutes": 45})
check(r.ok or r.status_code == 201, "carol: 45 minutes in the organisation's project " + r.text[:160])
Ca.post(B + "/api/time/entries", json={"list_id": CINBOX, "start": day + "T11:00", "minutes": 10})
CAL = Ca.post(B + "/api/evcals", json={"name": "Studio bookings", "org_id": ORG}).json()
CAL = CAL.get("id") or CAL.get("cal", {}).get("id")
check(CAL and sql("SELECT owner_id FROM ev_cals WHERE id=?", (CAL,)) == [(CAROL,)], "carol: an organisation calendar")
r = Ca.post(B + "/api/my/agents", json={"username": "carolbot", "scopes": ["read"]})
check(r.status_code == 201 and r.json().get("token"), "carol: a personal agent with a token " + r.text[:160])
CAG, CTOK = (r.json().get("id"), r.json().get("token")) if r.status_code == 201 else (None, "")
AGH = {"Authorization": "Bearer " + CTOK}
# 2.152.0 (#2164, review A5): the agent owns a private list and a list of the organisation (owner set here, made by carol)
APL = Ca.post(B + "/api/lists", json={"name": "Bot scratch"}).json()["id"]
AOL = Ca.post(B + "/api/lists", json={"name": "Bot studio list", "org_id": ORG}).json()["id"]
ATK = Ca.post(B + "/api/tasks", json={"title": "Private bot note", "list_id": APL}).json().get("id")
sql("UPDATE lists SET owner_id=? WHERE id IN (?, ?)", (CAG, APL, AOL), write=True)
sql("UPDATE lists SET org_id=NULL WHERE id=?", (APL,), write=True)  # private (carol's workspace is the organisation)
check(requests.get(B + "/api/v1/me", headers=AGH).ok, "the agent's token works")
DM = Bo.post(B + "/api/team/dm", json={"user_id": CAROL}).json().get("id")
Ca.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "The cut is ready"})
Bo.post(B + f"/api/team/rooms/{DM}/messages", json={"body": f"Thanks <@{CAROL}>"})
TK = Bo.post(B + "/api/tasks", json={"title": "Colour grading", "list_id": PL}).json()["id"]
Ca.patch(B + f"/api/tasks/{TK}", json={"title": "Colour grading v2"})
r = Bo.post(B + f"/api/tasks/{TK}/comments", json={"body": f"<@{CAROL}> please check the grading"})
CM = r.json().get("id") if r.ok else None
check(CM and sql("SELECT mentions FROM comments WHERE id=?", (CM,)) == [(str(CAROL),)], "bob mentions carol in a comment " + r.text[:120])
info = A.get(B + f"/api/users/{CAROL}/delete-info").json()
p = info.get("purge") or {}
check(p.get("agents") == 1 and p.get("calendars") == 1 and p.get("time_kept") == 1 and p.get("dms") == 1 and p.get("office") is None,
      f"delete-info: 1 agent, 1 calendar, 1 time entry kept, 1 conversation {p}")
r = A.delete(B + f"/api/users/{CAROL}")
check(r.ok, "carol deleted " + r.text[:200])
if not r.ok:
    app_log()
te = sql("SELECT user_id, seconds FROM time_entries WHERE list_id=?", (PL,))
check(te == [(None, 2700)], f"the organisation project's time entry stays, without the person {te}")
check(not sql("SELECT 1 FROM time_entries WHERE list_id=?", (CINBOX,)), "the private time entry is gone")
check(sql("SELECT owner_id, org_id FROM ev_cals WHERE id=?", (CAL,)) == [(ALICE, ORG)], "the organisation calendar went to the organisation's admin")
check(CAG and not sql("SELECT 1 FROM users WHERE id=?", (CAG,)) and requests.get(B + "/api/v1/me", headers=AGH).status_code == 401,
      "the own agent is deleted, its token refused (401)")
check(not sql("SELECT 1 FROM lists WHERE id=?", (APL,)) and not sql("SELECT 1 FROM tasks WHERE id=?", (ATK,)),
      "review A5: the agent's private list goes with its tasks (never to the deleting admin)")
check(sql("SELECT owner_id, org_id FROM lists WHERE id=?", (AOL,)) == [(ALICE, ORG)], "review A5: the agent's organisation list goes to a person of the organisation")
check(sql("SELECT a IS NULL OR b IS NULL FROM tchat_rooms WHERE id=?", (DM,)) == [(True,)], "the direct conversation stays")
msgs = Bo.get(B + f"/api/team/rooms/{DM}/messages")
bodies = [m.get("body") for m in (msgs.json().get("messages") or [])] if msgs.ok else []
check(msgs.ok and "The cut is ready" in bodies, f"bob still reads it {msgs.status_code} {bodies}")
check(any(b and "@Deleted user" in b and f"<@{CAROL}>" not in b for b in bodies), f"the mention in the chat is rewritten {bodies}")
cb = sql("SELECT body, mentions FROM comments WHERE id=?", (CM,))
check(cb and cb[0][0] == "@Deleted user please check the grading" and cb[0][1] == "", f"the mention in the comment is rewritten {cb}")
check(not sql("SELECT 1 FROM activity WHERE user_id=?", (CAROL,)), "the task history keeps no id of the account")
check(Bo.get(B + "/api/team").ok, "bob's chat overview still loads")

# ================================================================== #2167 an organisation with a knowledge page: 409 + numbers
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta Films", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{BETA}"})
r = A.post(B + "/api/wiki/pages", json={"space": f"org:{BETA}", "path": "Shoot day checklist"})
check(r.ok or r.status_code == 201, "Beta: a knowledge page " + r.text[:160])
r = A.delete(B + f"/api/admin/orgs/{BETA}")
check(r.status_code == 409 and r.json().get("content", {}).get("wiki_pages") == 1 and "1 knowledge page" in r.json().get("error", ""),
      "Beta: 409 with the numbers " + r.text[:200])
di = A.get(B + f"/api/admin/orgs/{BETA}/delete-info").json()
check(di.get("content", {}).get("wiki_pages") == 1 and not di.get("retain_until") and di.get("can_export") is True, f"Beta: delete-info {di}")
check(Bo.get(B + f"/api/admin/orgs/{BETA}/delete-info").status_code == 403, "delete-info: instance admins only")
check(sql("SELECT COUNT(*) FROM wiki_pages WHERE org_id=?", (BETA,)) == [(1,)], "Beta: nothing deleted yet")
r = A.delete(B + f"/api/admin/orgs/{BETA}?confirm=1")
check(r.ok and not sql("SELECT 1 FROM orgs WHERE id=?", (BETA,)) and not sql("SELECT 1 FROM wiki_pages WHERE org_id=?", (BETA,)),
      "Beta: deleted with confirm=1, the page with it " + r.text[:160])

# 2.152.0 (#2167, review A6): an organisation with only a cash book entry keeps it (books, 10 years)
DEL = A.post(B + "/api/admin/orgs", json={"name": "Delta Kiosk", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{DEL}"})
A.get(B + O + "/settings")
j = A.get(B + O + "/cashbooks").json()
r = A.post(B + O + f"/cashbooks/{j['books'][0]['id']}/entries", json={"day": j["today"], "dir": "in", "amount": "15", "text": "Kiosk sale", "vat_pct": "7"})
check(r.status_code == 201, "Delta: a cash book entry " + r.text[:160])
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.delete(B + f"/api/admin/orgs/{DEL}")
check(r.status_code == 409 and r.json().get("kept", {}).get("cash") == 1 and r.json().get("retain_until") == f"{int(j['today'][:4]) + 10}-12-31"
      and "1 cash book entry" in r.json().get("error", ""), "review A6: the cash book is kept by law (retired, not deleted) " + r.text[:200])

# 2.152.0 (#2167, review A8): an invoice of 2014 (period over at the end of 2024) keeps nothing: deleted, not retired
OLD = A.post(B + "/api/admin/orgs", json={"name": "Epsilon Archive", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{OLD}"})
A.get(B + O + "/settings")
r = A.post(B + O + "/docs", json={"project_title": "Old film"})
ODOC = r.json().get("id") if r.status_code == 201 else None
lock_doc(ODOC, "2014-06-02", "RE-2014-007")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
di = A.get(B + f"/api/admin/orgs/{OLD}/delete-info").json()
check(not di.get("retain_until") and not di.get("kept"), f"review A8: an expired period keeps nothing {di}")
r = A.delete(B + f"/api/admin/orgs/{OLD}", params={"confirm": "1", "retention": "waived"})
check(r.ok and not r.json().get("retired") and not sql("SELECT 1 FROM orgs WHERE id=?", (OLD,)), "review A8: deleted, not retired " + r.text[:200])

# ================================================================== #2167 an organisation with a finalised invoice: retired
GAM = A.post(B + "/api/admin/orgs", json={"name": "Gamma Media", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{GAM}/members", json={"email": "bob@example.com", "role": "member"}).ok
A.patch(B + "/api/settings", json={"workspace": f"org:{GAM}"})
A.get(B + O + "/settings")
r = A.post(B + O + "/docs", json={"project_title": "Event film"})
GDOC = r.json().get("id") if r.status_code == 201 else None
check(GDOC and sql("SELECT org_id FROM office_docs WHERE id=?", (GDOC,)) == [(GAM,)], "Gamma: a document " + r.text[:160])
lock_doc(GDOC, "2025-11-20", "RE-2025-042")
A.post(B + O + "/logo", files={"file": ("logo.png", picture(), "image/png")})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.delete(B + f"/api/admin/orgs/{GAM}")
check(r.status_code == 409 and r.json().get("retain_until") == "2035-12-31" and r.json().get("kept", {}).get("documents") == 1,
      "Gamma: 409, kept by law until 2035-12-31 " + r.text[:200])
# 2.152.0 (#2167, review A7): a mailbox and a newsletter connection of Gamma (rows only, the services are tested elsewhere)
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
sql("INSERT INTO hub_mailboxes(org_id, owner_id, ws, active, created_at, updated_at) VALUES(?,?,?,1,?,?)", (GAM, ALICE, f"org:{GAM}", NOW, NOW), write=True)
sql("INSERT INTO nl_conns(org_id, owner_id, ws, kind, auto, created_at, updated_at) VALUES(?,?,?,'listmonk',1,?,?)", (GAM, ALICE, f"org:{GAM}", NOW, NOW), write=True)
r = A.delete(B + f"/api/admin/orgs/{GAM}?confirm=1")
check(r.ok and r.json().get("retired") is True and r.json().get("retain_until") == "2035-12-31", "Gamma: retired " + r.text[:160])
check(not sql("SELECT 1 FROM org_members WHERE org_id=?", (GAM,)) and sql("SELECT 1 FROM office_docs WHERE id=?", (GDOC,)),
      "Gamma: members out, the invoice stays")
check(sql("SELECT active FROM hub_mailboxes WHERE org_id=?", (GAM,)) == [(0,)] and sql("SELECT auto FROM nl_conns WHERE org_id=?", (GAM,)) == [(0,)],
      "review A7: retired Gamma polls no mailbox and syncs no newsletter any more")
check(all(w.get("id") != GAM for w in (Bo.get(B + "/api/me").json().get("workspaces") or [])), "bob no longer sees Gamma")
check(Bo.patch(B + "/api/settings", json={"workspace": f"org:{GAM}"}).status_code in (200, 400, 403, 404)
      and Bo.get(B + O + "/settings").json().get("org_id") != GAM, "bob cannot open Gamma's office")

# 2.152.0 (#2167, review A4): the instance admin (no member) exports the retired organisation and downloads the file
check(A.get(B + f"/api/admin/orgs/{GAM}/delete-info").json().get("can_export") is True, "Gamma retired: delete-info offers the export")
r = A.post(B + f"/api/orgs/{GAM}/export")
check(r.status_code == 202, f"Gamma retired: the instance admin starts the export {r.status_code} {r.text[:160]}")
for _ in range(480):
    if A.get(B + f"/api/orgs/{GAM}/export").json().get("state") != "running":
        break
    time.sleep(0.25)
r = A.get(B + f"/api/orgs/{GAM}/export/file")
check(r.ok and r.content[:8] == b"KALMIDO-", f"Gamma retired: the download works (logged in the office log) {r.status_code} {r.content[:80]}")
if not r.ok:
    app_log()

# ---- the retention run after the period (backdated): counts with the switch off, deletes with it on
sql("UPDATE orgs SET retain_until='2020-12-31' WHERE id=?", (GAM,), write=True)
sql("UPDATE office_docs SET date='2010-05-01' WHERE id=?", (GDOC,), write=True)
out = run_prune(False)
check("purged 0" in out and sql("SELECT 1 FROM orgs WHERE id=?", (GAM,)), "switch off: Gamma stays " + out[-300:])
rt = A.get(B + "/api/admin/retention")
check(rt.ok and '"retired_orgs": 1' in rt.text.replace('":1', '": 1'), f"switch off: the count is in /api/admin/retention {rt.text[:400]}")
out = run_prune(True)
check("purged 1" in out and not sql("SELECT 1 FROM orgs WHERE id=?", (GAM,)) and not sql("SELECT 1 FROM office_docs WHERE id=?", (GDOC,)),
      "switch on: Gamma deleted for good with its documents " + out[-300:])
check(not os.path.exists(office_dir(GAM)), "switch on: its office folder is gone from the disk")
check(sql("SELECT 1 FROM orgs WHERE id=?", (PR,)), "frida's office (period not over) stays")

# ================================================================== hosted (KALMIDO_HOSTED=1): nothing is kept for others
def booked(s, ws, name):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, b"Beleg 0815 Material", "text/plain")})
    nid = r.json()["ids"][0] if r.status_code == 201 else 0
    s.patch(B + f"/api/docs/{nid}", json={"amount": "11.90", "date": "2026-03-06"})
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Material", "vat_pct": "19", "keep": True})
    check(nid and r.ok, f"hosted setup: a booked receipt in {ws} " + r.text[:160])
    return nid


if os.environ.get("P2103A_NOSTART") != "1":
    env = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_HOSTED=1" + KEYENV)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
    A, Bo = sess("alice"), sess("bob")
    # 2.152.0 (#2167, review A2): an organisation with a booked receipt in its trash goes after the waiver (no 409 of the lock)
    HO = A.post(B + "/api/admin/orgs", json={"name": "Hosted Studio", "admin_id": ALICE}).json()["id"]
    A.patch(B + "/api/settings", json={"workspace": f"org:{HO}"})
    HN = booked(A, f"org:{HO}", "beleg-org.txt")
    live = [x[0] for x in sql("SELECT id FROM fs_nodes WHERE org_id=? AND deleted_at IS NULL ORDER BY (id=?) DESC, id DESC", (HO, HN))]
    check(HN and live and all(A.delete(B + f"/api/files/nodes/{x}").ok for x in live), "hosted: the receipt (and its folder) into the organisation's trash")
    A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
    r = A.delete(B + f"/api/admin/orgs/{HO}", params={"confirm": "1", "retention": "waived"})
    check(r.ok and not r.json().get("retired") and not sql("SELECT 1 FROM orgs WHERE id=?", (HO,)) and not sql("SELECT 1 FROM fs_nodes WHERE id=?", (HN,)),
          "hosted A2: the organisation goes with the booked receipt in its trash after the waiver " + r.text[:200])
    if not r.ok:
        app_log()
    # 2.152.0 (#2164, review A3): a person with a booked private receipt: no retired office, the account goes with it
    HID, Hr = freelancer(B, A, "hanna")
    HR = booked(Hr, "private", "beleg-privat.txt")
    p = A.get(B + f"/api/users/{HID}/delete-info").json().get("purge") or {}
    check(p.get("office") != "keep" and not p.get("kept_until") and not p.get("kept"), f"hosted A3: delete-info keeps nothing {p}")
    r = A.delete(B + f"/api/users/{HID}", params={"retention": "waived"})
    check(r.ok and not sql("SELECT 1 FROM users WHERE id=?", (HID,)) and not sql("SELECT 1 FROM fs_nodes WHERE id=?", (HR,))
          and not sql("SELECT 1 FROM orgs WHERE retired_personal=1 AND name=?", ("Hanna",)),
          "hosted A3: the account goes with its booked receipt, no office is retired " + r.text[:200])
    if not r.ok:
        app_log()

print(f"p2103_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
