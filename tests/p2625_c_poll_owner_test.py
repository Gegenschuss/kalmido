#!/usr/bin/env python3
"""2.625.0 C (#3961): a personal agent changes hands -> its private scheduling polls go into the trash of its former owner
(sched_polls.trash_owner, agents/admin.py agent_polls_retire). Invented names only, addresses @example.com.
 - owner changed (person -> person): the new owner neither lists nor reads the old polls (also not in the trash ?deleted=1),
   their links answer 404, the agent itself no longer sees them; the former owner finds them in her trash, read-only (no
   change, restore 409, no voters' addresses); a poll she had deleted before goes along
 - the agent's new polls after the change: the new owner's, not the former owner's
 - owner -> team: the new owner's polls go into his trash; the former owner's kept polls stay with her
 - the owner deleted: her personal agent goes with its polls, their links 404; the kept polls in her trash go along
 - a person without an organisation (freelancer-matrix: polls) with a personal agent alike
 - 2.755.0 (#4978): the repair of an old database (core/fkeys.py) finds an agent whose owner is gone: its private polls go into
   the trash (kept by the agent), their links 404
usage: p2625_c_poll_owner_test.py"""
# kalmido-suite: fresh
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, H, check, sess  # noqa: E402

V = B + "/api/v1"
MODS = "cal,comments,collab,events,contacts,files,agents,team"
SCOPES = ["read", "tasks:write", "calendar"]
TIMES = [{"start": "2031-05-05T10:00"}, {"start": "2031-05-06T14:00"}]


def ahead(tok):
    return {"Authorization": "Bearer " + tok, **H}


def person(a, name, orgs):
    r = a.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": kt.PASSWORD,
                                       "email": f"{name}@example.com", "orgs": orgs})
    assert r.ok, r.text
    s = sess(name)
    assert s.patch(B + "/api/settings", json={"lang": "en", "features": MODS}).ok
    return r.json()["id"], s


def agent(s, name):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": SCOPES, "org_id": "private"})
    assert r.ok, r.text
    aid = r.json()["id"]
    kt.dbx("INSERT INTO user_settings(user_id,key,value) VALUES(?,'features',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
           (aid, MODS))
    return aid, ahead(r.json()["token"])


def v1_poll(h, title):
    r = requests.post(V + "/polls", headers=h, json={"title": title, "options": TIMES, "tz": "Europe/Berlin"})
    assert r.status_code == 201, r.text
    d = r.json()
    return d["id"], "/s/v/" + d["url"].rsplit("/s/v/", 1)[1]


def v1_ids(h):
    r = requests.get(V + "/polls", headers=h)
    check(r.status_code == 200, f"GET /polls 200, not {r.status_code}: {r.text[:200]}")
    return [x["id"] for x in r.json().get("data", [])]


def ids(s, trash=False):
    r = s.get(B + "/api/polls", params={"deleted": "1"} if trash else {})
    assert r.ok, r.text
    return [x["id"] for x in r.json()["items"]]


def link(path):
    return requests.get(B + path, headers={"Accept-Language": "en"}).status_code


def owner_set(aid, owner):
    r = A.patch(B + f"/api/admin/agents/{aid}", json={"owner_id": owner})
    check(r.ok, f"admin sets the owner of agent {aid} to {owner}: {r.status_code} {r.text[:200]}")


def rows(pid):
    return kt.dbx("SELECT id FROM sched_polls WHERE id=?", (pid,))


kt.fresh()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "anna", "display_name": "Anna Admin", "password": kt.PASSWORD}).ok
A = sess("anna")
assert A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "org_name": "Testorg", "modules": MODS.split(",")}).ok
assert A.patch(B + "/api/settings", json={"lang": "en", "features": MODS}).ok
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 3}).ok
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
CLARA, Cl = person(A, "clara", [{"id": ORG, "role": "member"}])
BERT, Be = person(A, "bert", [{"id": ORG, "role": "member"}])
FRIDA, Fr = freelancer(B, A, features=MODS)
OTTO, Ot = freelancer(B, A, "otto", features=MODS)

# ---- Clara's personal agent: two private polls (one with a voter's address), one she deleted herself
P, PH = agent(Cl, "clarabot")
PP, PL = v1_poll(PH, "Doctor slots")
PD, _ = v1_poll(PH, "Old idea")
o1 = Cl.get(B + f"/api/polls/{PP}").json()["poll"]["options"][0]["id"]
kt.dbx("INSERT INTO sched_poll_votes(poll_id,name,email,answers,edit_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
       (PP, "Vera Voter", "vera@example.com", json.dumps({str(o1): "y"}), "x" * 64, "2031-01-01T00:00:00Z", "2031-01-01T00:00:00Z"))
check(Cl.delete(B + f"/api/polls/{PD}").ok, "Clara deletes one poll of her agent (trash)")
check(PP in ids(Cl) and link(PL) == 200, "before the change: Clara lists her agent's poll, the link opens")

# ---- the owner changes: Clara -> Bert
owner_set(P, BERT)
check(link(PL) == 404, "after the change: the link of the old poll answers 404")
check(PP not in ids(Be) and PP not in ids(Be, trash=True) and PD not in ids(Be, trash=True), "the new owner lists none of the old polls (nor in the trash)")
check(Be.get(B + f"/api/polls/{PP}").status_code == 404, "the new owner cannot read the old poll (404)")
check(Be.post(B + f"/api/polls/{PP}/restore").status_code == 404, "the new owner cannot restore it (404)")
check(PP not in v1_ids(PH) and requests.get(V + f"/polls/{PP}", headers=PH).status_code == 404, "the agent itself no longer sees it")
tr_ = Cl.get(B + "/api/polls", params={"deleted": "1"}).json()["items"]
mine = {x["id"]: x for x in tr_}
check(PP in mine and PD in mine, f"the former owner finds both in her trash {sorted(mine)}")
check(PP not in ids(Cl), "and no longer among her open polls")
check(PP in mine and mine[PP]["can_edit"] is False and mine[PP]["url"] is None, "read-only there: no change, no link")
r = Cl.post(B + f"/api/polls/{PP}/restore")
check(r.status_code == 409, f"restore by the former owner: 409 ({r.status_code} {r.text[:200]})")
check(link(PL) == 404, "the link stays closed after the refused restore")
check(Cl.patch(B + f"/api/polls/{PP}", json={"title": "x"}).status_code == 404, "no change of a poll in the trash")

# ---- new polls after the change are the new owner's
NP, NL = v1_poll(PH, "Bert's slots")
check(NP in ids(Be) and Be.get(B + f"/api/polls/{NP}").json()["poll"]["can_edit"] is True, "the new owner sees and may change the agent's new poll")
check(NP not in ids(Cl) and NP not in ids(Cl, trash=True) and Cl.get(B + f"/api/polls/{NP}").status_code == 404, "the former owner does not see it")
check(link(NL) == 200, "its link opens")

# ---- Bert -> team: his polls go into his trash, Clara's kept ones stay with her
owner_set(P, None)
check(link(NL) == 404 and NP in ids(Be, trash=True) and NP not in ids(Be), "owner -> team: the new poll goes into Bert's trash, link 404")
check(PP in ids(Cl, trash=True) and PP not in ids(Be, trash=True), "Clara's kept polls stay hers")
check(Be.post(B + f"/api/polls/{NP}/restore").status_code == 409, "Bert cannot restore it either (409)")

# ---- a person without an organisation: her personal agent changes hands
FP, FPH = agent(Fr, "fridabot")
FPP, FPL = v1_poll(FPH, "Client call")
check(FPP in ids(Fr) and link(FPL) == 200, "the freelancer's agent poll: hers, the link opens")
owner_set(FP, OTTO)
check(link(FPL) == 404 and FPP not in ids(Ot) and FPP not in ids(Ot, trash=True) and Ot.get(B + f"/api/polls/{FPP}").status_code == 404,
      "the new owner (also without an organisation) sees nothing, link 404")
check(FPP in ids(Fr, trash=True) and Fr.post(B + f"/api/polls/{FPP}/restore").status_code == 409, "the freelancer keeps it in her trash, no restore")

# ---- the owner deleted: her agent's polls and the kept ones go along
r = A.delete(B + f"/api/users/{FRIDA}")
check(r.ok, f"the freelancer deleted: {r.status_code} {r.text[:200]}")
check(not rows(FPP), "the polls kept in her trash went with her account")
check(PP in ids(Cl, trash=True), "Clara's kept polls are untouched by that")
OP, OPH = agent(Ot, "ottobot")
OPP, OPL = v1_poll(OPH, "Otto's slots")
check(link(OPL) == 200, "the link of Otto's agent poll opens")
r = A.delete(B + f"/api/users/{OTTO}")
check(r.ok, f"Otto deleted: {r.status_code} {r.text[:200]}")
check(link(OPL) == 404 and not rows(OPP), "his personal agent's poll went with him, its link 404")
r = A.delete(B + f"/api/users/{CLARA}")
check(r.ok, f"Clara deleted: {r.status_code} {r.text[:200]}")
check(not rows(PP) and not rows(PD) and link(PL) == 404, "the polls kept in Clara's trash went with her account")

# ---- 2.755.0 (#4978): the repair of an old database (core/fkeys.py fk_ensure) finds an agent whose owner is gone: its
# private polls go into the trash like at a change of owner (the agent keeps them), their links 404
import subprocess  # noqa: E402
GUS, Gu = freelancer(B, A, "gus", features=MODS)
GP, GPH = agent(Gu, "gusbot")
GPP, GPL = v1_poll(GPH, "Gus slots")
check(link(GPL) == 200, "#4978: the link of the agent's poll opens")
FKN = kt.dbx("SELECT con.conname FROM pg_constraint con JOIN pg_class cl ON cl.oid=con.conrelid JOIN pg_attribute a "
             "ON a.attrelid=con.conrelid AND a.attnum=con.conkey[1] WHERE con.contype='f' AND cl.relname='agents' AND a.attname='owner_id'")
for (n,) in FKN:  # an old database: the key is not there yet, the owner's row is gone
    kt.dbx(f"ALTER TABLE agents DROP CONSTRAINT {n}")
kt.dbx("UPDATE agents SET owner_id=? WHERE user_id=?", (987654321, GP))
out = subprocess.run(["docker", "exec", kt.CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\n"
                      "from kalmido.core.fkeys import fk_ensure\nc = connect()\nprint(fk_ensure(c))\nc.commit()\nc.close()"],
                     capture_output=True, text=True)
check(out.returncode == 0, f"#4978: the repair runs {out.stdout[-300:]} {out.stderr[-800:]}")
check(kt.dbx("SELECT owner_id, admin_paused FROM agents WHERE user_id=?", (GP,)) == [(None, 1)], "#4978: the agent is ownerless and paused")
pr = kt.dbx("SELECT deleted_at IS NOT NULL, trash_owner FROM sched_polls WHERE id=?", (GPP,))
check(pr == [(True, GP)], f"#4978: its private poll lies in the trash, kept by the agent itself {pr}")
check(link(GPL) == 404, "#4978: the poll's link answers 404")
check(kt.dbx("SELECT 1 FROM pg_constraint WHERE conname='fk2103_agents_owner_id'"), "#4978: the key is in place again")

print(f"p2625_c_poll_owner: {kt.OKS[0]} ok, {len(kt.FAILS)} failed")
sys.exit(1 if kt.FAILS else 0)
