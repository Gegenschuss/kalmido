#!/usr/bin/env python3
"""2.223.7 C API tests (#2921 the agents' disposition shows nothing unshared, #2670 the event offer_accepted). Invented names only.
 - #2921: an organisation's agent (scope calendar, only L1 shared) reads GET /api/v1/dispo: a booking of L2 (not shared) and one
   without a project only as "Booked" (no title, job, list_id, event_id), the L1 booking in full; people only of shared
   projects, a booked person it does not know without rid / label, absences only of those people; /dispo/free alike;
   the shoot proposal's warnings name only titles of projects it reads
 - #2921: a personal agent in an organisation and a freelancer's agent: GET /dispo and /dispo/free 404, no personal office row
   made by the read; the freelancer's agent still proposes shoots in her project (warnings masked)
 - #2670: offer_accepted only for agents whose office groups give them offers; list_id null when the project is not shared;
   an agent whose list restriction leaves the project out gets nothing; a freelancer's agent with offers hears it (list_id)
freelancer-matrix: agents
tenant-matrix: agent, hub, office
usage: p22237_c_dispo_test.py <datadir>      (a fresh container; the suite restarts it in mode workspaces)"""
import json
import os
import subprocess
import sys
from datetime import date, timedelta

import requests
from freelancer_fixture import org_join

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402
FEAT = "cal,collab,comments,time,events,dispo,office,clients"
SECRET = "GEHEIM"


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
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


def agent(name, scopes, org=None, owner=None):
    r = A.post(B + "/api/admin/agents", json={"username": name, "display_name": name.title(), "scopes": scopes})
    assert r.status_code == 201, r.text
    aid, t = r.json()["id"], r.json().get("token") or ""
    dbx("DELETE FROM org_members WHERE user_id=? AND org_id IS DISTINCT FROM ?", (aid, org), write=True)
    if org:  # an organisation's agent is a member of it (as agents/admin.py makes it)
        dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (org, aid), write=True)
    dbx("UPDATE agents SET org_id=?, owner_id=? WHERE user_id=?", (org, owner, aid), write=True)
    return aid, tok(t)


e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bert", "carl", "frida"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BERT, CARL, FRIDA = ids["bert"], ids["carl"], ids["frida"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BERT})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Be = sess("bert")
check(Be.put(B + f"/api/orgs/{ORG}/members", json={"email": "carl@example.com"}).ok and org_join(B, "carl", ORG), "setup: carl joins Alpha")
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR user_id=?", (ORG, BERT, CARL, FRIDA), write=True)
SC = ["read", "tasks:write", "calendar", "office"]
G, GS = agent("dispobot", SC, org=ORG)
GN, GNS = agent("staffbot", SC, org=ORG)          # office group without offers
GL, GLS = agent("limitbot", SC, org=ORG)          # list restriction L1
P, PS = agent("bertbot", SC, owner=BERT)          # bert's personal agent in the organisation
F, FS = agent("fridabot", SC, owner=FRIDA)        # the freelancer's agent
for s in (A, Be):
    s.post(B + "/api/auth/logout")
A, Be, Ca, Fr = sess("alice"), sess("bert"), sess("carl"), sess("frida")
for s in (A, Be, Ca, Fr):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
for s in (Be, Ca):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})


def mklist(sess_, name, org=None, members=()):
    lid = sess_.post(B + "/api/lists", json={"name": name, "kind": "project"}).json()["id"]
    if org:
        dbx("UPDATE lists SET org_id=? WHERE id=?", (org, lid), write=True)
    for uid in members:
        check(sess_.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": "edit"}).ok, f"setup: share {name} with {uid}")
    return lid


L1 = mklist(Be, "Film One", ORG, (G,))  # one agent per list
L2 = mklist(Be, "Film Two", ORG, (CARL,))
L3 = mklist(Be, "Film Three", ORG, (GL,))
LF = mklist(Fr, "Frida film", None, (F,))
DAY = date.today() + timedelta(days=35 - date.today().weekday())  # a Monday a few weeks ahead


def book(sess_, title, lid, rid, org=ORG):
    b = {"title": title, "start": str(DAY), "end": str(DAY), "status": "firm", "resources": [{"kind": "user", "id": rid}]}
    if org:
        b["org"] = org
    r = sess_.post(B + "/api/team/dispo/bookings", json=b)
    check(r.status_code == 201, f"setup: booking {title} ({r.status_code} {r.text[:150]})")
    if lid:
        dbx("UPDATE hub_bookings SET list_id=? WHERE title=?", (lid, title), write=True)


book(Be, "Shoot One", L1, BERT)
book(Be, f"Dreh {SECRET} Two", L2, CARL)
book(Be, f"Studio {SECRET} free", None, BERT)
book(Fr, f"Frida {SECRET} day", None, FRIDA, org=None)
check(Ca.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": str(DAY), "end_date": str(DAY)}).status_code == 201,
      "setup: carl is away")

# =================================================================== #2921 an organisation's agent
r = GS.get(V + "/dispo", params={"start": str(DAY), "days": 2})
j = r.json() if r.ok else {}
bk = {b["id"]: b for b in j.get("bookings", [])}
vis = [b for b in bk.values() if not b.get("hidden")]
hid = [b for b in bk.values() if b.get("hidden")]
check(r.ok and SECRET not in r.text and [b["title"] for b in vis] == ["Shoot One"] and vis[0]["list_id"] == L1,
      f"#2921: the L1 booking in full, nothing secret ({r.status_code} {r.text[:300]})")
check(len(hid) == 2 and all(b["title"] == "Booked" and b["list_id"] is None and b["event_id"] is None and not b["job"] for b in hid),
      f"#2921: the L2 booking and the one without a project only as Booked ({hid})")
check([p["id"] for p in j.get("resources", {}).get("people", [])] == [BERT], f"#2921: people only of shared projects ({j.get('resources')})")
carl_b = [b for b in hid if b["kind"] == "user" and b["rid"] is None]
check(len(carl_b) == 1 and not carl_b[0]["label"] and "Carl" not in r.text, f"#2921: carl's booking without rid / label ({hid})")
check(str(CARL) not in (j.get("away") or {}), f"#2921: carl's absence not shown ({j.get('away')})")
fr = GS.get(V + "/dispo/free", params={"date": str(DAY)})
check(fr.ok and "Carl" not in fr.text and CARL not in fr.json()["away"], f"#2921: free without carl ({fr.text[:200]})")
r = GS.post(V + "/agent/proposals/shoot", json={"list_id": L1, "days": [{"date": str(DAY), "title": "New shoot"}],
                                                "crew": [{"kind": "user", "id": BERT}]})
p = r.json().get("proposal", {}) if r.status_code == 201 else {}
check(r.status_code == 201 and SECRET not in r.text, f"#2921: shoot proposal without secret titles ({r.status_code} {r.text[:300]})")
check(p and p["days"][0]["warnings"] == [{"kind": "other_projects", "titles": ["Booked"]}]
      and p["crew"][0]["warnings"][0]["titles"] == ["Booked", "Shoot One"], f"#2921: warnings masked by list_role ({p})")
check(GS.post(V + "/agent/proposals/shoot", json={"list_id": L1, "days": [{"date": str(DAY), "title": "x"}],
                                                  "crew": [{"kind": "user", "id": CARL}]}).status_code == 400,
      "#2921: a person the agent does not know is no crew (400)")

# =================================================================== #2921 personal agents: 404, no office row made
before = dbx("SELECT count(*) FROM orgs WHERE personal_of IN (?,?)", (BERT, FRIDA))[0][0]
for name, s in (("personal agent", PS), ("freelancer agent", FS)):
    check(s.get(V + "/dispo", params={"start": str(DAY)}).status_code == 404 and s.get(V + "/dispo/free", params={"date": str(DAY)}).status_code == 404,
          f"#2921: {name}: the owner's private disposition 404")
check(dbx("SELECT count(*) FROM orgs WHERE personal_of IN (?,?)", (BERT, FRIDA))[0][0] == before, "#2921: the reads made no personal office row")
r = FS.post(V + "/agent/proposals/shoot", json={"list_id": LF, "days": [{"date": str(DAY), "title": "Frida shoot"}], "crew": []})
check(r.status_code == 201 and SECRET not in r.text and r.json()["proposal"]["days"][0]["warnings"][0]["titles"] == ["Booked"],
      f"#2921: freelancer: the shoot proposal still works, titles masked ({r.status_code} {r.text[:200]})")

# =================================================================== #2670 offer_accepted
CF = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
      "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
for s in (Be, Fr):
    s.get(B + "/api/office/settings")
    check(s.put(B + "/api/office/settings", json={"company_fields": CF, "agents_read": 1}).ok, "setup: office + agents may read")
dbx("UPDATE agents SET office_drafts=1 WHERE user_id IN (?,?,?,?)", (G, GN, GL, F), write=True)
OAREA = ORG
for aid, tpl in ((G, "projects"), (GN, "staff")):
    dbx("INSERT INTO office_rgroup_members(org_id,user_id,tpl,created_at) VALUES(?,?,?,?)", (OAREA, aid, tpl, "2026-10-25T10:00:00Z"), write=True)
dbx("UPDATE agents SET list_ids=? WHERE user_id=?", (str(L3), GL), write=True)
dbx("UPDATE api_tokens SET list_ids=? WHERE user_id=?", (str(L3), GL), write=True)


def accepted_offer(s, lid, name):
    cl = s.post(B + "/api/clients", json={"name": f"{name} Kunde", "address": "Weg 2\n10115 Berlin"}).json()["id"]
    did = s.post(B + "/api/office/docs", json={"client_id": cl, "project_title": name}).json()["id"]
    dbx("UPDATE office_docs SET list_id=? WHERE id=?", (lid, did), write=True)
    s.put(B + f"/api/office/docs/{did}", json={"items": [{"kind": "service", "title": "Camera day", "qty": 1, "unit": "day", "rate": 900}]})
    for st in ("sent", "accepted"):
        r = s.post(B + f"/api/office/docs/{did}/status", json={"status": st})
        check(r.ok, f"setup: {name} {st} ({r.status_code} {r.text[:150]})")
    return did


def heard(s, did):
    r = s.get(V + "/agent/events")
    check(r.ok, f"setup: the agent reads its events ({r.status_code})")
    ev = r.json() if r.ok else {}
    return [x["data"] for x in ev.get("events", ev.get("data", [])) if x["event"] == "offer_accepted" and x["data"].get("doc_id") == did]


def queued(aid, did):
    """The stored events of agent aid for document did (also when the polling route would not show them)."""
    return [d for d in (json.loads(x[0]).get("data") or {} for x in dbx("SELECT payload FROM agent_events WHERE agent_id=? AND event='offer_accepted'", (aid,)))
            if d.get("doc_id") == did]


Q1, Q2, Q3 = accepted_offer(Be, L1, "Offer One"), accepted_offer(Be, L2, "Offer Two"), accepted_offer(Be, L3, "Offer Three")
h1, h2 = heard(GS, Q1), heard(GS, Q2)
check(len(h1) == 1 and h1[0]["list_id"] == L1, f"#2670: offers group, shared project: list_id ({h1})")
check(len(h2) == 1 and h2[0]["list_id"] is None, f"#2670: offers group, project not shared: list_id null ({h2})")
check(not heard(GNS, Q1) and not queued(GN, Q1) and not queued(GN, Q2), "#2670: an office group without offers: no event")
h3 = heard(GLS, Q3)
check(len(h3) == 1 and h3[0]["list_id"] == L3 and not queued(GL, Q1) and not queued(GL, Q2), f"#2670: list restriction L3: only the L3 quotation ({h3})")
QF = accepted_offer(Fr, LF, "Frida offer")
hf = heard(FS, QF)
check(len(hf) == 1 and hf[0]["list_id"] == LF, f"#2670: freelancer: her agent hears it with the shared project ({hf})")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
