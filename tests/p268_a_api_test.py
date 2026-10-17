#!/usr/bin/env python3
"""2.68.0 API tests, part A (#1839: old data into the office with the person's own agent, kind "import", fixed costs first),
own container (start.sh, org encryption on). Invented names and figures only.
 - the right: scope import (off for new agents, not part of the legacy "write"); without it 403 naming the right; OpenAPI
 - the agent never writes or reads the office: office routes 403 for its token; the answer, the job and its events carry no
   office data (no "already there", no rows of the office)
 - bad proposals: no rows, more than 500 rows, another area, a row that is no object, a body over 256 KB, the office module
   off for the person; another person / an agent of another organisation 404
 - the card (the person only): every row new / dup (against the office and earlier rows, not ticked) / error with a reason;
   the office it goes into; another person 404
 - accepting: the ticked rows with a changed VAT rate, exactly these written (org_id / id / created_by of a row ignored), an
   error row ticked = 400 and nothing written; a member (no office admin) 403, nothing written; an agent of organisation A
   while the person works in B: 409, nothing written; the agent hears counts only
 - discarding writes nothing; undo removes exactly the made rows (not one changed since), redo makes them again
 - a freelancer without an organisation: the personal office
 - limits: 5 open import cards per agent (429), an expired card 409, replacing needs the scope
tenant-matrix: agent, office
usage: p268_a_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]


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


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def dbx(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def agent(name, scopes, org=None, owner=None):
    r = A.post(B + "/api/admin/agents", json={"username": name, "display_name": name.title(), "scopes": scopes})
    assert r.status_code == 201, r.text
    aid, t = r.json()["id"], r.json().get("token") or ""
    dbx("DELETE FROM org_members WHERE user_id=? AND org_id IS DISTINCT FROM ?", (aid, org), write=True)
    if org:
        dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (org, aid), write=True)
    dbx("UPDATE agents SET org_id=?, owner_id=? WHERE user_id=?", (org, owner, aid), write=True)
    return aid, tok(t)


def events(aid):
    return [json.loads(r[0]).get("data") or {} for r in dbx("SELECT payload FROM agent_events WHERE agent_id=? AND event='job' ORDER BY id", (aid,))]


def fixed(s):
    return s.get(B + "/api/office/fixed-costs").json()["items"]


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Second"), ("erin", "Erin Free")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "dave@example.com", "role": "admin"}).ok
BOB, CAROL, DAVE, ERIN = (s.get(B + "/api/state").json()["me"]["id"] for s in (Bo, Ca, Da, Er))
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT DO NOTHING", (ORG2, ALICE), write=True)  # alice works in both
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2), (Da, ORG)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
AG, AGS = agent("importbot", ["read", "comments", "import"], org=ORG)
AG0, AG0S = agent("plainbot", ["read", "comments"], org=ORG)
AGB, AGBS = agent("betabot", ["read", "comments", "import"], org=ORG2)
PAG, PAGS = agent("erinbot", ["read", "comments", "import"], owner=ERIN)
IMP = V + "/agent/proposals/import"
F = B + "/api/office/fixed-costs"

# ---- rollback: nothing new in the schema (the card is an agent job of kind import)
check(not dbx("SELECT 1 FROM information_schema.tables WHERE table_name LIKE 'import_prop%'"), "no new table")

# ---- the right: off by default, not in the legacy write, named in the 403
r = A.post(B + "/api/admin/agents", json={"username": "newbot", "display_name": "Newbot"})
sc = dbx("SELECT scopes FROM api_tokens WHERE user_id=?", (r.json()["id"],))
check(r.status_code == 201 and sc and "import" not in sc[0][0], f"a new agent has no import right ({sc})")
spec = AGS.get(V + "/openapi.json").json()["paths"]
check(spec.get("/agent/proposals/import", {}).get("post", {}).get("x-kalmido-scope") == "import", "OpenAPI: the route needs import")
ROW = {"label": "Office rent", "amount": 950, "repeat": "monthly", "start": "2026-01-01", "category": "Rooms"}
r = AG0S.post(IMP, json={"items": [ROW], "user_id": ALICE})
check(r.status_code == 403 and "Propose imports" in r.text, f"without the right: 403 with the name of the right ({r.status_code} {r.text[:120]})")
offered = {x["scope"] for x in A.get(B + "/api/admin/agents").json().get("scopes", [])}
check("import" in offered, f"the right is offered in the agent settings ({sorted(offered)})")

# ---- the agent stays out of the office
for what, rr in (("list", AGS.get(F)), ("create", AGS.post(F, json=ROW)), ("import", AGS.post(F + "/import", json={"items": [ROW]})),
                 ("delete", AGS.post(F + "/delete", json={"ids": [1]}))):
    check(rr.status_code == 403, f"the agent token: 403 on the office route {what} ({rr.status_code})")

# ---- what is there already
r = A.post(F, json=ROW)
check(r.status_code == 201, "setup: one fixed cost " + r.text[:200])
n0 = len(fixed(A))

# ---- bad proposals
for what, body, code in (("no rows", {"items": []}, 400), ("too many rows", {"items": [ROW] * 501}, 400), ("another area", {"area": "clients", "items": [ROW]}, 400),
                         ("a row that is no object", {"items": ["Office rent 950"]}, 400), ("an unknown field", {"items": [ROW], "office": 1}, 400)):
    rr = AGS.post(IMP, json={**body, "user_id": ALICE})
    check(rr.status_code == code, f"{what}: {code} ({rr.status_code} {rr.text[:120]})")
rr = AGS.post(IMP, data=b"{" + b" " * (300 * 1024) + b"}", headers={"Content-Type": "application/json"})
check(rr.status_code == 413, f"a body over 256 KB: 413 ({rr.status_code})")
check(AGS.post(IMP, json={"items": [ROW], "user_id": CAROL}).status_code == 404, "a person outside the agent's organisation: 404")
check(AGBS.post(IMP, json={"items": [ROW], "user_id": BOB}).status_code == 404, "an agent of Beta for a person of Alpha only: 404")
Da.patch(B + "/api/settings", json={"features": "cal,comments,collab"})
rr = AGS.post(IMP, json={"items": [ROW], "user_id": DAVE})
check(rr.status_code == 400 and "office" in rr.text, f"the office module off for the person: 400 with a reason ({rr.status_code} {rr.text[:120]})")
Da.patch(B + "/api/settings", json={"features": FEAT})
check(not dbx("SELECT 1 FROM agent_jobs WHERE kind='import'"), "nothing of that made a card")

# ---- the card
ITEMS = [ROW,  # 0: already there
         {"label": "Liability insurance", "amount": "240,00", "repeat": "yearly", "start": "2026-03-01", "category": "Insurances"},  # 1: new, 0 %
         {"label": "Software subscription", "amount": 29.9, "start": "2026-01-01", "vat_rate": 19, "org_id": ORG2, "id": 999999, "created_by": CAROL},  # 2
         {"label": "Software subscription", "amount": "29.90", "repeat": "monthly", "start": "2026-01-01"},  # 3: dup of 2
         {"label": "", "amount": 10, "start": "2026-01-01"},  # 4: no name
         {"label": "Zero cost", "amount": 0, "start": "2026-01-01"},  # 5: 0
         {"label": "<script>alert(1)</script> Cleaning", "amount": "1.200,50", "repeat": "quarterly", "start": "2026-02-01"}]  # 6: new, 1200.50
r = AGS.post(IMP, json={"items": ITEMS, "user_id": ALICE, "summary": "From the old sheet", "note": "Row 9 had no amount"})
check(r.status_code == 201 and r.json().get("kind") == "import" and r.json().get("rows") == 7, f"a card for alice ({r.status_code} {r.text[:200]})")
J1 = r.json()["id"]
check("dup" not in r.text and "Already there" not in r.text and "status" not in r.text, "the answer carries no judgement against the office")
check(bool(dbx("SELECT 1 FROM notifications WHERE user_id=? AND kind='proposal' AND data->>'job' = ?", (ALICE, str(J1)))), "News for alice")
g = AGS.get(V + f"/agent/jobs/{J1}")
check(g.ok and "Already there" not in g.text and '"status"' not in g.text and "Alpha" not in g.text, "the job for the agent: no office data")
check(len(fixed(A)) == n0, "a card writes nothing")
v = A.get(B + f"/api/proposals/{J1}").json()
im = v.get("import") or {}
st = [x["status"] for x in im.get("rows") or []]
check(st == ["dup", "new", "new", "dup", "error", "error", "new"], f"new / dup / error per row {st}")
rows = im.get("rows") or [{}] * 7
check([x["sel"] for x in rows] == [False, True, True, False, False, False, True], "dups and errors not ticked")
check(rows[1]["vat_rate"] == 0 and rows[2]["vat_rate"] == 19 and rows[6]["vat_rate"] == 19 and rows[6]["amount"] == "1200.50"
      and rows[1]["amount"] == "240.00" and rows[2]["gross"] == "35.58", f"VAT defaults, amounts read like the spreadsheet {rows[1:3]} {rows[6]}")
check(rows[4]["reason"] and rows[5]["reason"], "error rows carry a reason")
check((im.get("office") or {}).get("id") == ORG and (im.get("office") or {}).get("name") == "Alpha" and im.get("counts") == {"new": 3, "dup": 2, "error": 2},
      f"the target office and the counts ({im.get('office')} {im.get('counts')})")
check(Bo.get(B + f"/api/proposals/{J1}").status_code == 404 and Da.get(B + f"/api/proposals/{J1}").status_code == 404, "another person: 404 on the card")
check(Da.post(B + f"/api/proposals/{J1}/apply", json={"select": ["1"]}).status_code == 404, "another admin cannot accept alice's card")
check(not AGS.post(B + f"/api/proposals/{J1}/apply", json={"select": ["1"]}).ok, "the agent's token cannot accept")

# ---- accepting
r = A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["1", "4"]})
check(r.status_code == 400 and "Row 5" in r.text, f"an error row ticked: 400 with its row ({r.status_code} {r.text[:120]})")
check(len(fixed(A)) == n0, "nothing written")
r = A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["1"], "edits": {"1": {"vat_rate": 16}}})
check(r.status_code == 400, "a VAT rate other than 0 / 7 / 19: 400")
r = A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["1"], "edits": {"1": {"label": "Other"}}})
check(r.status_code == 400, "only the VAT rate can be changed")
r = A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["1", "2", "6"], "edits": {"2": {"vat_rate": 7}}})
check(r.ok and r.json().get("created") == 3 and r.json().get("skipped") == 4, f"three rows taken over ({r.status_code} {r.text[:200]})")
fx = fixed(A)
new = [x for x in fx if x["label"] in ("Liability insurance", "Software subscription", "<script>alert(1)</script> Cleaning")]
check(len(fx) == n0 + 3 and len(new) == 3, f"exactly the three rows {[x['label'] for x in fx]}")
sw = next((x for x in new if x["label"] == "Software subscription"), {})
check(sw.get("vat_rate") == 7 and sw.get("amount") == "29.90" and sw.get("gross") == "31.99", f"the changed VAT rate {sw}")
cl = next((x for x in new if x["label"].endswith("Cleaning")), {})
check(cl.get("repeat") == "quarterly" and cl.get("amount") == "1200.50" and cl.get("start") == "2026-02-01", f"quarterly as sent {cl}")
NEW_IDS = sorted(x["id"] for x in new)
dbrows = dbx(f"SELECT org_id, created_by FROM office_fixed_costs WHERE id IN ({','.join(str(i) for i in NEW_IDS)})")
check(all(x[0] == ORG and x[1] == ALICE for x in dbrows) and 999999 not in NEW_IDS, f"the office of alice, created by alice; a row's org_id / id / created_by ignored {dbrows}")
check(str(dbx("SELECT label FROM office_fixed_costs WHERE id=?", (NEW_IDS[0],))[0][0]).startswith("kenc1:"), "stored encrypted like every fixed cost")
check(bool(dbx("SELECT 1 FROM office_doc_log WHERE org_id=? AND action='import' AND target='fixed_costs' AND user_id=?", (ORG, ALICE))), "the office log: import by alice")
ev = [e for e in events(AG) if (e.get("job") or {}).get("id") == J1]
check(ev and ev[-1].get("action") == "approve" and ev[-1]["proposal"].get("created") == 3 and ev[-1]["proposal"].get("skipped") == 4,
      f"the agent hears approve with counts {ev[-1] if ev else None}")
check(ev and "Office rent" not in json.dumps(ev[-1]) and "Already there" not in json.dumps(ev[-1]), "the event carries no office rows")
check(A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["1"]}).status_code == 409, "a decided card: 409")

# ---- undo / redo
time.sleep(1.1)
check(A.patch(F + f"/{NEW_IDS[0]}", json={"category": "Changed"}).ok, "setup: one row changed since")  # stays on undo
r = A.post(B + f"/api/proposals/{J1}/undo")
check(r.ok and r.json().get("undone") == 2 and r.json().get("skipped"), f"undo removes the made rows, not the changed one ({r.text[:200]})")
left = {x["id"] for x in fixed(A)}
check(len(left) == n0 + 1 and NEW_IDS[0] in left and not (set(NEW_IDS[1:]) & left), f"exactly those of this card {sorted(left)}")
r = A.post(B + f"/api/proposals/{J1}/redo")
check(r.ok and r.json().get("redone") == 2, f"redo makes them again ({r.text[:200]})")
check(len(fixed(A)) == n0 + 3, "three again after redo")

# ---- a member is no office admin; another workspace; discard
r = AGS.post(IMP, json={"items": [ITEMS[1]], "user_id": BOB})
check(r.status_code == 201, "a card for a member " + r.text[:120])
JB = r.json()["id"]
nb = len(dbx("SELECT id FROM office_fixed_costs WHERE org_id=?", (ORG,)))
check(Bo.get(B + f"/api/proposals/{JB}").json().get("import", {}).get("office") is None, "the member's card says it cannot be taken over")
r = Bo.post(B + f"/api/proposals/{JB}/apply", json={"select": ["0"]})
check(r.status_code == 403 and len(dbx("SELECT id FROM office_fixed_costs WHERE org_id=?", (ORG,))) == nb, f"a member: 403, nothing written ({r.status_code})")
r = AGS.post(IMP, json={"items": [{"label": "Storage", "amount": 80, "start": "2026-01-01"}], "user_id": ALICE})
J3 = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
v = A.get(B + f"/api/proposals/{J3}").json().get("import") or {}
check(v.get("office") is None and "Alpha" in (v.get("problem") or ""), f"the card asks to switch to Alpha ({v.get('problem')})")
n2 = len(dbx("SELECT id FROM office_fixed_costs WHERE org_id=?", (ORG2,)))
r = A.post(B + f"/api/proposals/{J3}/apply", json={"select": ["0"]})
check(r.status_code == 409 and len(dbx("SELECT id FROM office_fixed_costs WHERE org_id=?", (ORG2,))) == n2, f"an agent of Alpha, the person in Beta: 409, nothing written ({r.status_code})")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.post(B + f"/api/proposals/{J3}/apply", json={"select": ["0"]}).ok, "back in Alpha: taken over")
r = AGS.post(IMP, json={"items": [{"label": "Parking", "amount": 60, "start": "2026-01-01"}], "user_id": ALICE})
J4 = r.json()["id"]
n4 = len(fixed(A))
check(A.post(B + f"/api/proposals/{J4}/discard").ok and len(fixed(A)) == n4, "discarding writes nothing")
ev = [e for e in events(AG) if (e.get("job") or {}).get("id") == J4]
check(ev and ev[-1].get("action") == "reject", "the agent hears reject")

# ---- a freelancer without an organisation: the personal office
r = PAGS.post(IMP, json={"items": [{"label": "Coworking desk", "amount": 199, "start": "2026-01-01", "category": "Rooms"}]})
check(r.status_code == 201 and r.json().get("user_id") == ERIN, f"the personal agent's card goes to its owner ({r.status_code} {r.text[:120]})")
JE = r.json()["id"]
v = Er.get(B + f"/api/proposals/{JE}").json().get("import") or {}
check((v.get("office") or {}).get("personal") is True, f"the personal office {v.get('office')}")
r = Er.post(B + f"/api/proposals/{JE}/apply", json={"select": ["0"]})
check(r.ok and r.json().get("created") == 1 and [x["label"] for x in fixed(Er)] == ["Coworking desk"], f"in erin's personal office ({r.text[:120]})")
check("Coworking desk" not in [x["label"] for x in fixed(A)], "not in alice's office")

# ---- limits
open_n = len(dbx("SELECT id FROM agent_jobs WHERE agent_id=? AND kind='import' AND prop_state='ready'", (AG,)))
codes = [AGS.post(IMP, json={"items": [ROW], "user_id": ALICE}).status_code for _ in range(6 - open_n)]
check(codes[:5 - open_n] == [201] * (5 - open_n) and codes[-1] == 429, f"at most 5 open import cards per agent {open_n} {codes}")
JX = dbx("SELECT id FROM agent_jobs WHERE agent_id=? AND kind='import' AND prop_state='ready' ORDER BY id DESC LIMIT 1", (AG,))[0][0]
check(AG0S.post(V + f"/agent/jobs/{JX}/proposal", json={"items": [ROW]}).status_code == 404, "another agent cannot replace it")
r = AGS.post(V + f"/agent/jobs/{JX}/proposal", json={"kind": "import", "items": [ROW, ITEMS[1]]})
check(r.status_code == 201 and len(r.json()["proposal"]["items"]) == 2, f"the agent replaces its open card ({r.status_code} {r.text[:120]})")
dbx("UPDATE agent_jobs SET created_at='2020-01-01T00:00:00Z' WHERE id=?", (JX,), write=True)
check(A.post(B + f"/api/proposals/{JX}/apply", json={"select": ["1"]}).status_code == 409, "an expired card: 409")
check(A.post(B + "/api/proposals", json={"agent_id": AG, "kind": "import"}).status_code == 400, "a person cannot request the kind")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
