#!/usr/bin/env python3
"""2.103.0 API test (leader, #2165): the switch of the retention runs and GET /api/admin/retention.
Invented accounts only (example.com).
 - instance admins only (an organisation member, a person without an organisation and nobody get 401 / 403)
 - every kind (trash, logs, backups, files, chat) with its period, its env names and the switch; the test server runs
   without KALMIDO_RETENTION_PURGE, so every kind is off (count only) -- the safe default of an update
 - numbers only: no user names or mail addresses in the answer
 - #2166 (built in 2.102.0 A): a deleted list keeps fields + values and its chat in the trash; the purge after the period
   takes them along (no orphan rows of list_fields, task_field_values, tchat_rooms / tchat_msgs)
 - #2164 review F1: a person without an organisation is deleted while a booked receipt sits in the private document store:
   the receipt moves into the retired office and stays READABLE (re-sealed for the office before the account key goes)
 - #2167: a retired organisation opens no public link any more (acx_anon_bind, the bind of every org-bound public path:
   shared lists, forms, sign-offs, the customer portal, hooks) -> 404; an active one still binds
usage: p2103_r_api_test.py <datadir>      (a fresh server on KALMIDO_TEST_PORT)
freelancer-matrix: admin"""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".data")
FAILS, OKS = [], [0]


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


s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
assert A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123",
                                      "email": "bob@example.com"}).ok
Bo = sess("bob")
FID, Fr = freelancer(B, A)

r = A.get(B + "/api/admin/retention")
check(r.ok, f"#2165: the instance admin reads the retention runs {r.status_code} {r.text[:200]}")
j = r.json() if r.ok else {}
kinds = j.get("kinds") or {}
check(set(kinds) == {"trash", "logs", "backups", "files", "chat"}, f"#2165: every kind is listed {sorted(kinds)}")
check(j.get("general_switch") == "KALMIDO_RETENTION_PURGE", "#2165: the general switch is named")
check(all(k.get("on") is False for k in kinds.values()), f"#2165: without the switch every run only counts {kinds}")
check((kinds.get("trash") or {}).get("days") == 30 and (kinds.get("trash") or {}).get("env_days") == "KALMIDO_TRASH_DAYS",
      f"#2165: the trash period 30 days, KALMIDO_TRASH_DAYS {kinds.get('trash')}")
check((kinds.get("logs") or {}).get("days") == 400, f"#2171: the log period 400 days {kinds.get('logs')}")
check((kinds.get("backups") or {}).get("env_switch") == "KALMIDO_PURGE_BACKUPS", "#2172: the switch of one kind")
check((j.get("legal_years") or {}).get("receipt") == 8 and (j.get("legal_years") or {}).get("book") == 10,
      f"#2168: legal retention receipts 8, books 10 years {j.get('legal_years')}")
check("alice" not in r.text and "example.com" not in r.text, "#2165: numbers only, no account names")
check(Bo.get(B + "/api/admin/retention").status_code == 403, "#2165: a member who is no instance admin: 403")
check(Fr.get(B + "/api/admin/retention").status_code == 403, "#2165: a person without an organisation: 403")
check(requests.get(B + "/api/admin/retention", headers=H).status_code in (401, 403), "#2165: nobody signed in: 401 / 403")

# ---- #2166: fields, values and the list chat stay in the trash and go with the purge
BOB = sql("SELECT id FROM users WHERE username='bob'")[0][0]
L = A.post(B + "/api/lists", json={"name": "Shared shoot", "org_id": None}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"})
F = A.post(B + f"/api/lists/{L}/fields", json={"name": "Budget", "type": "number"}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Book the studio", "list_id": L}).json()["id"]
A.patch(B + f"/api/tasks/{T}", json={"fields": {str(F): "1200"}})
room = next((x for x in A.get(B + "/api/team").json().get("rooms", []) if x["kind"] == "list" and x["list_id"] == L), None)
if room:
    A.post(B + f"/api/team/rooms/{room['id']}/messages", json={"body": "Studio is booked"})
check(room is not None, "#2166 setup: the shared list has its chat")
A.patch(B + f"/api/lists/{L}", json={"archived": True})
check(A.delete(B + f"/api/lists/{L}").ok, "#2166: the list goes to the trash")
kept = (sql("SELECT COUNT(*) FROM list_fields WHERE list_id=?", (L,))[0][0], sql("SELECT COUNT(*) FROM task_field_values WHERE task_id=?", (T,))[0][0],
        sql("SELECT COUNT(*) FROM tchat_rooms WHERE list_id=?", (L,))[0][0])
check(kept == (1, 1, 1 if room else 0), f"#2166: field, value and chat stay in the trash {kept}")
old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="seconds")
sql("UPDATE lists SET deleted_at=? WHERE id=?", (old, L), write=True)
out = subprocess.run(["docker", "exec", CT, "python", "-c",
                      "import app\nfrom kalmido.core.db import connect\nfrom kalmido.lists.listtrash import otr_prune\n"
                      "c = connect()\nprint('purged', otr_prune(c, True))\nc.close()"], capture_output=True, text=True)
check("purged 1" in out.stdout, "#2166: the purge after the period " + (out.stdout + out.stderr)[-300:])
gone = (sql("SELECT COUNT(*) FROM list_fields WHERE list_id=?", (L,))[0][0], sql("SELECT COUNT(*) FROM task_field_values WHERE task_id=?", (T,))[0][0],
        sql("SELECT COUNT(*) FROM tchat_rooms WHERE list_id=?", (L,))[0][0],
        sql("SELECT COUNT(*) FROM tchat_msgs WHERE room_id=?", (room["id"],))[0][0] if room else 0)
check(gone == (0, 0, 0, 0), f"#2166: field, value, chat room and messages are gone with the purge {gone}")

# ---- #2167: public links of a retired organisation
ALICE = sql("SELECT id FROM users WHERE username='alice'")[0][0]
OA = A.post(B + "/api/admin/orgs", json={"name": "Retired Ltd", "admin_id": ALICE}).json().get("id")
check(OA, "#2167 setup: an organisation")
code = ("import app\nfrom kalmido.core.config import app as fa\nfrom kalmido.core.db import connect\n"
        "from kalmido.core.access import acx_anon_bind, Denied\nc = connect()\n"
        "with fa.test_request_context('/s/x'):\n"
        "    try:\n        acx_anon_bind(c, %d)\n        print('bound')\n"
        "    except Denied as e:\n        print('denied', e.args[0] if e.args else '')\nc.close()" % (OA or 0))
run = lambda: subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True)  # noqa: E731
out = run()
check("bound" in out.stdout, "#2167: an active organisation binds its public link " + (out.stdout + out.stderr)[-300:])
sql("UPDATE orgs SET retired_at=?, retain_until=? WHERE id=?", ("2026-10-19T07:00:00+00:00", "2036-12-31", OA), write=True)
out = run()
check("denied 404" in out.stdout, "#2167: a retired organisation's public link: 404 " + (out.stdout + out.stderr)[-300:])

# ---- #2164 review F1: a booked private receipt of a deleted person stays readable in the retired office
G, Gr = freelancer(B, A, name="greta")
r = Gr.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("beleg.txt", b"Beleg 4711 Software", "text/plain")})
check(r.status_code == 201, "#2164 setup: a private receipt " + r.text[:200])
RN = r.json()["ids"][0] if r.status_code == 201 else 0
Gr.patch(B + f"/api/docs/{RN}", json={"amount": "119.00", "date": "2026-10-01"})
r = Gr.put(B + f"/api/docs/{RN}/receipt", json={"category": "Software", "vat_pct": "19", "keep": True})
check(r.ok, "#2164 setup: booked (VAT rate) " + r.text[:200])
r = A.delete(B + f"/api/users/{G}")
check(r.ok, f"#2164: the person with a booked private receipt is deleted {r.status_code} {r.text[:300]}")
row = sql("SELECT n.org_id, o.retired_at FROM fs_nodes n JOIN orgs o ON o.id=n.org_id WHERE n.id=?", (RN,))
check(row and row[0][1], f"#2164: the receipt sits in the retired office {row}")
out = subprocess.run(["docker", "exec", CT, "python", "-c",
                      "import app, os\nfrom kalmido.core.db import connect\nfrom kalmido.core.config import ATT_DIR\n"
                      "from kalmido.core.orgcrypt import oc_read_file\nfrom kalmido.core.pg import system_ctx\nc = connect()\n"
                      "with system_ctx(c):\n"
                      "    ps = [p for (p,) in c.execute('SELECT path FROM fs_versions WHERE node_id=%d', ()).fetchall()]\n"
                      "    print('versions', len(ps))\n"
                      "    for p in ps:\n        print(oc_read_file(c, os.path.join(ATT_DIR, p))[:40])\nc.close()" % RN],
                     capture_output=True, text=True)
check("versions 1" in out.stdout and "Beleg 4711" in out.stdout, "#2164 F1: the receipt is readable after the account key went "
      + (out.stdout + out.stderr)[-400:])

print(f"p2103_r_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
