#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.360.4 (#3243 #3248): retention and account-move remains. Invented names only, addresses @example.com.
 #3243 (1) a retired organisation's calendar subscription and booking page close (also when the page is switched on again);
       the task and absence feeds of a former member show nothing of it; a page of somebody else stays open
 #3243 (2) a restore deletes organisations and entries deleted for good after the backup again; deleted in the last days
       they stay and are counted; a row made after the deletion with the same id stays; a row that came back leaves the list
 #3243 (3) a file locked on its own retires the organisation instead of a 409; an account with such a private file is
       deleted, the file moves into the retired office; such a file of an organisation goes to an instance admin
 #3243 (4) delete-info names the missing heir before the deletion
 #3248 the preview of an account move names every part; dl_sig goes on a step back, so the next upgrade answers full
usage: p2360_4_reste_test.py <datadir>   (P23604_NOSTART=1: against a running instance on KALMIDO_TEST_PORT)
freelancer-matrix: own"""
import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
PW = kt.PASSWORD
FEAT = "cal,comments,collab,events,files,docs,office,clients,hub,tasks"
kt.fresh(env={"KALMIDO_SECRET_KEY": base64.b64encode(os.urandom(32)).decode(), "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_INSTANCE_MODE": "workspaces",
              "KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none", "KALMIDO_MAIL_FROM": "kalmido@example.test"},
         prefix="P23604")
A = kt.setup()
A.patch(B + "/api/settings", json={"features": FEAT})
ME = A.get(B + "/api/me").json()["id"]
NOW = datetime.now(timezone.utc)


def ago(days):
    return (NOW - timedelta(days=days)).isoformat(timespec="seconds")


def sql(q, args=(), write=False):
    c = dbxm.connect(DATA)
    try:
        r = c.execute(q, args)
        rows = None if write else r.fetchall()
        c.commit()
        return rows
    finally:
        c.close()


def py(code):
    """Lines inside the container (app loaded, c = a connection in the system context) -> the last JSON line printed."""
    body = "\n".join("    " + x for x in code.strip().split("\n"))
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", "import app, json\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\n"
                        "c = connect()\nwith system_ctx(c):\n" + body + "\n    c.commit()\nc.close()"], capture_output=True, text=True, timeout=300)
    for line in reversed((r.stdout or "").strip().splitlines()):
        if line.startswith(("{", "[")):
            return json.loads(line)
    print("container python:", r.returncode, (r.stdout or "")[-500:], (r.stderr or "")[-1500:], flush=True)
    return {}


def user(name, orgs=()):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": PW, "email": f"{name}@example.com", "orgs": list(orgs)})
    assert r.ok, r.text
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
    return r.json()["id"], s


def org(name, admin=ME):
    return A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": admin}).json()["id"]


def node(owner, oid, kept=None, name="beleg.pdf"):
    """A file-store row with document data; kept = doc_meta.kept_until (a lock of its own)."""
    nid = sql("INSERT INTO fs_nodes(kind, name, owner_id, org_id, created_at, updated_at) VALUES('file',?,?,?,?,?) RETURNING id",
              (name, owner, oid, ago(400), ago(400)))
    return nid


def path(url):
    return url[url.index("/ical/"):]


# ================================================================== #3243 (1) the public ways of a retired organisation
OR1 = org("Retired Studio")
CARL, Ca = user("carl", [{"id": OR1, "role": "admin"}])
PAUL, Pa = user("paul")
Ca.patch(B + "/api/settings", json={"workspace": f"org:{OR1}"})
CAL = Ca.post(B + "/api/evcals", json={"name": "Studio bookings", "org_id": OR1}).json().get("id")
FEED = path(Ca.post(B + f"/api/evcals/{CAL}/feed", json={"action": "create"}).json().get("url") or "/ical/none")
ABS = path(Ca.post(B + "/api/team/absences/feed", json={"action": "create"}).json().get("url") or "/ical/none")
TF = path(Ca.post(B + "/api/ical", json={"action": "create"}).json().get("url") or "/ical/none")
LID = Ca.post(B + "/api/lists", json={"name": "Studio project", "org_id": OR1}).json().get("id")
Ca.post(B + "/api/tasks", json={"title": "Studio deadline", "list_id": LID, "due": "2031-03-04"})
DAY = NOW.date().isoformat()
sql("INSERT INTO hub_absences(org_id, user_id, kind, start_date, end_date, created_by, created_at) VALUES(?,?,'vacation',?,?,?,?)",
    (OR1, CARL, DAY, DAY, CARL, ago(1)), write=True)
ALL = {d: [["08:00", "18:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
r = Ca.put(B + "/api/appt/page", json={"slug": "carl-termine", "enabled": True, "cal_id": CAL, "office_org_id": OR1, "hours": ALL})
r2 = Pa.put(B + "/api/appt/page", json={"slug": "paul-termine", "enabled": True})
check(r.ok and r2.ok, f"setup: booking pages {r.status_code} {r.text[:200]} {r2.status_code}")
pub = requests.Session()
check(pub.get(B + FEED).status_code == 200 and "Studio deadline" in pub.get(B + TF).text, "setup: the feeds answer, the task feed has the organisation's task")
check("UID:absence-" in pub.get(B + ABS).text, "setup: the absence feed has the absence")
check(pub.get(B + "/s/b/carl-termine").status_code == 200, "setup: the booking page is open")
py(f"from kalmido.accounts.orgretain import odl_retire\nodl_retire(c, {OR1}, '2035-12-31')\nprint(json.dumps({{}}))")
check(pub.get(B + FEED).status_code == 404, "(1) the calendar's subscription link is gone")
check(not sql("SELECT 1 FROM ev_cal_feeds WHERE cal_id=?", (CAL,)), "(1) its row went")
check(pub.get(B + "/s/b/carl-termine").status_code == 404, "(1) the booking page is closed")
check(sql("SELECT enabled, office_org_id FROM appt_pages WHERE user_id=?", (CARL,)) == [(0, OR1)], "(1) switched off, the export still finds it through its organisation")
sql("UPDATE appt_pages SET enabled=true WHERE user_id=?", (CARL,), write=True)
check(pub.get(B + "/s/b/carl-termine").status_code == 404, "(1) switched on again it stays closed for a retired office")
t = pub.get(B + TF)
check(t.status_code == 200 and "Studio deadline" not in t.text, "(1) the task feed of the former member has nothing of the organisation")
check("UID:absence-" not in pub.get(B + ABS).text, "(1) the absence feed of the former member has nothing of the organisation")
check(pub.get(B + "/s/b/paul-termine").status_code == 200, "(1) a page of somebody else stays open")

# ================================================================== #3243 (2) the restore deletes again what went for good
OLD, RECENT = ago(40), ago(2)
OR2 = org("Gone Studio")
OR3 = org("Recent Studio")
FR, Fr = freelancer(B, A, "frieda")  # a person without an organisation: their entries as everybody's
L2 = Fr.post(B + "/api/lists", json={"name": "Old project"}).json()["id"]
T1 = Fr.post(B + "/api/tasks", json={"title": "Old task", "list_id": L2}).json()["id"]
T2 = Fr.post(B + "/api/tasks", json={"title": "Recent task", "list_id": L2}).json()["id"]
T3 = Fr.post(B + "/api/tasks", json={"title": "Same id later", "list_id": L2}).json()["id"]
T4 = Fr.post(B + "/api/tasks", json={"title": "Came back", "list_id": L2}).json()["id"]
N1 = node(FR, None)[0][0]
L3 = Fr.post(B + "/api/lists", json={"name": "Deleted project"}).json()["id"]
T5 = Fr.post(B + "/api/tasks", json={"title": "Task of the deleted project", "list_id": L3}).json()["id"]
sql("UPDATE lists SET created_at=? WHERE id=?", (ago(100), L3), write=True)
F1 = sql("INSERT INTO fs_nodes(kind, name, owner_id, created_at, updated_at) VALUES('folder','Merged',?,?,?) RETURNING id", (FR, ago(100), ago(100)))[0][0]
sql("UPDATE orgs SET created_at=? WHERE id IN (?,?)", (ago(100), OR2, OR3), write=True)
sql("UPDATE tasks SET created_at=? WHERE id IN (?,?,?,?)", (ago(100), T1, T2, T3, T4), write=True)
BK = py("from kalmido.admin import backup as bk\nprint(json.dumps({'name': bk.bk_create('manual')}))").get("name")
check(bool(BK), f"setup: a backup {BK}")
for t_, i in (("orgs", OR2), ("orgs", OR3), ("tasks", T1), ("tasks", T2), ("tasks", T3), ("fs_nodes", N1), ("fs_nodes", F1), ("lists", L3)):
    sql(f"DELETE FROM {t_} WHERE id=?", (i,), write=True)
rows = dict(((a, b), c) for a, b, c in sql("SELECT tbl, ref_id, at FROM purged_rows"))
check(("orgs", OR2) in rows and ("tasks", T1) in rows and ("fs_nodes", N1) in rows, "(2) the trigger notes what went")
check(("fs_nodes", F1) not in rows, "(2) a folder is not noted: it also goes when it is merged or dissolved")
sql("DELETE FROM tasks WHERE id=?", (T4,), write=True)
sql("INSERT INTO tasks(id, list_id, title, created_by, created_at, updated_at) VALUES(?,?,'Came back',?,?,?)", (T4, L2, FR, ago(100), ago(100)), write=True)
check(("tasks", T4) not in dict(((a, b), c) for a, b, c in sql("SELECT tbl, ref_id, at FROM purged_rows")), "(2) a row that came back with its id leaves the list")
for t_, i, at in (("orgs", OR2, OLD), ("orgs", OR3, RECENT), ("tasks", T1, OLD), ("tasks", T2, RECENT), ("tasks", T3, OLD), ("fs_nodes", N1, OLD), ("lists", L3, OLD)):
    sql("UPDATE purged_rows SET at=? WHERE tbl=? AND ref_id=?", (at, t_, i), write=True)
sql("DELETE FROM purged_rows WHERE tbl='tasks' AND ref_id=?", (T5,), write=True)  # the app moves a project's tasks to the trash first
sql("UPDATE purged_rows SET made='2001-01-01T00:00:00+00:00' WHERE tbl='tasks' AND ref_id=?", (T3,), write=True)  # another row with this id went
r = A.post(B + "/api/admin/backups/restore", json={"name": BK, "confirm": "RESTORE", "password": PW})
check(r.ok, f"(2) restore {r.status_code} {r.text[:200]}")
A = sess("alice")
ag = r.json().get("deleted_again") or {}
check(ag.get("entries") == 4 and ag.get("entries_recent") == 2 and not ag.get("entries_failed"), f"(2) the numbers of the result {ag}")
check(not sql("SELECT 1 FROM orgs WHERE id=?", (OR2,)), "(2) an organisation deleted earlier is gone again")
check(bool(sql("SELECT 1 FROM orgs WHERE id=?", (OR3,))), "(2) one deleted in the last days stays")
check(not sql("SELECT 1 FROM tasks WHERE id=?", (T1,)) and bool(sql("SELECT 1 FROM tasks WHERE id=?", (T2,))), "(2) the same for tasks")
check(not sql("SELECT 1 FROM fs_nodes WHERE id=?", (N1,)), "(2) a file-store node deleted earlier is gone again")
check(bool(sql("SELECT 1 FROM tasks WHERE id=?", (T3,))), "(2) another row with the same id stays")
check(not sql("SELECT 1 FROM lists WHERE id=?", (L3,)), "(2) a project deleted earlier is gone again")
check(sql("SELECT deleted_at IS NOT NULL FROM tasks WHERE id=?", (T5,)) == [(True,)], "(2) its tasks lie in the trash, as after the owner's delete")
check(bool(sql("SELECT 1 FROM fs_nodes WHERE id=?", (F1,))), "(2) the folder stays")
check(bool(sql("SELECT 1 FROM tasks WHERE id=?", (T4,))), "(2) a row that came back stays")
check(sql("SELECT at FROM purged_rows WHERE tbl='orgs' AND ref_id=?", (OR2,)) == [(OLD,)], "(2) the list keeps the first time")
log = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
check("restore: entries deleted earlier: 4 deleted again, 2 kept" in log.stdout + log.stderr, "(2) the numbers are in the log (and the alert, sent when alerts are on)")

Fr = sess("frieda")  # the restore ended every session
r = Fr.post(B + "/api/books", json={"name": "Mine", "org_id": None})
check(r.ok, f"(2) setup: an address book {r.status_code} {r.text[:160]}")
BID = r.json().get("id")
C1, C2 = (Fr.post(B + "/api/contacts", json={"book_id": BID, "given": "Eva", "family": "Muster"}).json().get("id") for _ in range(2))
r = Fr.post(B + "/api/contacts/merge", json={"target": C1, "ids": [C1, C2], "pick": {}})
check(r.ok and not sql("SELECT 1 FROM contacts WHERE id=?", (C2,)), f"(2) setup: contacts merged {r.status_code} {r.text[:160]}")
check(not sql("SELECT 1 FROM purged_rows WHERE tbl='contacts' AND ref_id=?", (C2,)), "(2) a merged contact is not noted as deleted")

# ================================================================== #3243 (3) a lock of its own never stops a deletion
OR4 = org("Locked Studio")
N4 = node(ME, OR4)[0][0]
sql("INSERT INTO doc_meta(node_id, org_id, ws, kept_until, created_at, updated_at) VALUES(?,?,?,?,?,?)", (N4, OR4, f"o{OR4}", "2036-12-31", ago(1), ago(1)), write=True)
sql("UPDATE fs_nodes SET deleted_at=? WHERE id=?", (ago(1), N4), write=True)
r = A.delete(B + f"/api/admin/orgs/{OR4}", params={"confirm": "1"})
check(r.ok and r.json().get("retired") is True and r.json().get("retain_until") == "2036-12-31", f"(3) the organisation is retired until the lock ends {r.status_code} {r.text[:200]}")
check(bool(sql("SELECT 1 FROM fs_nodes WHERE id=?", (N4,))), "(3) the file stays")
GRETA, _ = user("greta")
N5 = node(GRETA, None)[0][0]
sql("INSERT INTO doc_meta(node_id, org_id, ws, kept_until, created_at, updated_at) VALUES(?,NULL,?,?,?,?)", (N5, "p", "2036-12-31", ago(1), ago(1)), write=True)
FOLD = sql("INSERT INTO fs_nodes(kind, name, owner_id, created_at, updated_at) VALUES('folder','Mine',?,?,?) RETURNING id", (GRETA, ago(1), ago(1)))[0][0]
r = A.get(B + f"/api/users/{GRETA}/delete-info")
check(r.ok and r.json()["purge"].get("office") == "keep", f"(3) the dialog says the office stays {r.text[:200]}")
r = A.delete(B + f"/api/users/{GRETA}")
check(r.ok, f"(3) the account goes although a private file is locked {r.status_code} {r.text[:200]}")
n5 = sql("SELECT org_id, owner_id FROM fs_nodes WHERE id=?", (N5,))
check(n5 and n5[0][0] and n5[0][1] == ME and bool(sql("SELECT 1 FROM orgs WHERE id=? AND retired_at IS NOT NULL", (n5[0][0],))), f"(3) the file moved into the retired office {n5}")
check(not sql("SELECT 1 FROM fs_nodes WHERE id=?", (FOLD,)), "(3) the rest of the tree went")
OR5 = org("Heirless Studio")
OR7 = org("Shared Studio")  # alice manages hans through this one; nobody else is in OR5
HANS, _ = user("hans", [{"id": OR5, "role": "admin"}, {"id": OR7, "role": "member"}])
sql("DELETE FROM org_members WHERE org_id=? AND user_id=?", (OR5, ME), write=True)
N6 = node(HANS, OR5)[0][0]
sql("INSERT INTO doc_meta(node_id, org_id, ws, kept_until, created_at, updated_at) VALUES(?,?,?,?,?,?)", (N6, OR5, f"o{OR5}", "2036-12-31", ago(1), ago(1)), write=True)
r = A.delete(B + f"/api/users/{HANS}")
check(r.ok, f"(3) a locked file of an organisation does not stop the account {r.status_code} {r.text[:200]}")
n6 = sql("SELECT owner_id, deleted_at IS NOT NULL FROM fs_nodes WHERE id=?", (N6,))
check(n6 and n6[0] == (ME, True), f"(3) it stays with an instance admin, in the trash {n6}")

# ================================================================== #3243 (4) the missing heir in the dialog
OR6 = org("Guest Studio")
IDA, Id = user("ida", [{"id": OR6, "role": "member"}])
sql("UPDATE org_members SET role='guest' WHERE org_id=? AND user_id=?", (OR6, ME), write=True)
Id.patch(B + "/api/settings", json={"workspace": f"org:{OR6}"})
c6 = Id.post(B + "/api/evcals", json={"name": "Guest calendar", "org_id": OR6})
JO, _ = user("jo", [{"id": OR6, "role": "guest"}])
j = A.get(B + f"/api/users/{IDA}/delete-info").json()
check(c6.ok and "another admin or member" in ((j.get("purge") or {}).get("no_heir") or ""), f"(4) delete-info names the missing heir {c6.text[:120]} {json.dumps(j)[:300]}")
check(A.delete(B + f"/api/users/{IDA}").status_code == 409, "(4) the deletion is refused as before")
j = A.get(B + f"/api/users/{JO}/delete-info").json()
check(not (j.get("purge") or {}).get("no_heir"), "(4) nothing to say for an account without calendars")
j = A.get(B + f"/api/users/{FR}/delete-info").json()
check(j.get("can_delete") and not (j.get("purge") or {}).get("no_heir"), "(4) a person without an organisation has no heir to name")

# ================================================================== #3248
out = py("""
from kalmido.admin.acctimport import umz_left
parts = ["written_comments", "channel_messages", "other_tasks", "task_people", "reactions", "kid_stars", "notifications", "sessions", "push_devices", "agent_chat_prefs"]
print(json.dumps([x["what"] for x in umz_left({p: [{}] for p in parts})]))
""")
check(len(out) == 10 and not ({"written_comments", "channel_messages", "other_tasks", "task_people", "reactions", "kid_stars", "notifications", "sessions", "push_devices", "agent_chat_prefs"} & set(out)),
      f"#3248: the preview names every part {out}")
out = py("""
from kalmido.core.db import gsetting, gset
from kalmido.tasks.delta import dl_floor_check as dl
real = c.execute("SELECT value FROM kalmido_meta WHERE key='app_version'").fetchone()[0]
sig = gsetting(c, "dl_sig")
gset(c, "version", int(gsetting(c, "version") or 0) + 5)
f0 = gsetting(c, "dl_floor")
dl(c, sig)
same = gsetting(c, "dl_floor") == f0
c.execute("UPDATE kalmido_meta SET value='99.0.0' WHERE key='app_version'")
dl(c, sig)
back = gsetting(c, "dl_sig")
f1 = gsetting(c, "dl_floor")
gset(c, "version", int(gsetting(c, "version") or 0) + 5)
c.execute("UPDATE kalmido_meta SET value=? WHERE key='app_version'", (real,))
dl(c, sig)
print(json.dumps({"sig": bool(sig), "same": same, "back": back, "moved": f1 != f0, "again": gsetting(c, "dl_sig") == sig, "up": gsetting(c, "dl_floor") != f1}))
""")
check(out.get("sig") and out.get("same"), f"#3248: a start without a step back keeps the deltas {out}")
check(out.get("back") == "" and out.get("moved"), f"#3248: a step back answers full and forgets the signature {out}")
check(out.get("again") and out.get("up"), f"#3248: the upgrade after it answers full too {out}")

print(f"p2360_4_reste: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
