#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.560.0 part A (#4697, #4698): rights at retiring an organisation, leaving it and a role going down. Own container
(mode workspaces, server key). Invented names only.  tenant-matrix: org
 - #4697: an organisation with a finalised invoice is retired / one without is deleted: a former colleague and the
   organisation's agent lose its calendars and address books (app routes + API v1, member rows and event invitations
   gone); the owner keeps them privately, with their own personal agent
 - #4698 a: leaving and joining again the same day (as a member, as a guest): no old closed channel, no old folder share of
   the knowledge base (also not for the person's agent)
 - #4698 b: made a guest: out of the open channels joined, a closed one stays
 - #4698 c: a public knowledge link and a public project link of a maker made guest end (and work again once member)
 - a person without an organisation: their own public links of a private page / project keep working
usage: p2560_a_orgrights_test.py <datadir>"""
import os
import sys
from datetime import datetime, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
import requests  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, FAILS, OKS, check, sess  # noqa: E402,F401
# 2.924.0 (#5069): tchat_members is no member table any more -- a room's members are the shares of its node in the shared core
TCHAT_M = ("(SELECT n.ref_id AS room_id, COALESCE(s.user_id, s.agent_id) AS user_id FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id "
           "WHERE n.kind='ref' AND n.ref_kind='tchat_room') tm")

FEAT = "cal,events,contacts,comments,collab,files,wiki,docs,office,clients"
V = B + "/api/v1"

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": "A" * 43 + "="}, prefix="P2560A")


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


def ids(r):
    j = r.json() if r.ok else {}
    rows = j if isinstance(j, list) else (j.get("items") or j.get("data") or [])
    return {x.get("id") for x in rows}


def no(r, what):
    check(r.status_code in (403, 404), f"{what}: refused ({r.status_code} {r.text[:120]})")


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
uid, S = {}, {}
for u in ("bob", "gina", "rita"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    S[u] = sess(u)
    S[u].patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Bo, Gi, Ri = S["bob"], S["gina"], S["rita"]
BOB, GINA, RITA = uid["bob"], uid["gina"], uid["rita"]


def org(name):
    r = A.post(B + "/api/admin/orgs", json={"name": name})
    assert r.status_code in (200, 201), r.text
    oid = r.json()["id"]
    sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT (org_id,user_id) DO UPDATE SET role='admin'", (oid, ALICE), write=True)
    return oid


def member(oid, who, role="member"):
    """Alice (instance + organisation admin) adds who directly / changes their role (by e-mail address: no visibility needed)."""
    mail = sql("SELECT email FROM users WHERE id=?", (who,))[0][0]
    r = A.put(B + f"/api/orgs/{oid}/members", json={"email": mail, "role": role})
    check(r.ok and sql("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (oid, who)) == [(role,)],
          f"setup: {who} is {role} of {oid} {r.text[:160]}")


def agent(name, oid, owner=None):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "calendar", "contacts"], "username": name, "display_name": name.title(),
                                             **({"owner_id": owner} if owner else {})})
    assert r.ok, r.text
    aid = r.json()["id"]
    check(A.patch(B + f"/api/admin/agents/{aid}", json={"org_id": oid}).ok, f"setup: agent {name} in organisation {oid}")
    return aid, {"Authorization": "Bearer " + r.json()["token"]}


def lock_doc(did, day="2025-11-20", number="RE-2025-042"):
    """A finalised document (the state the finalising leaves; finalising itself is tested in the office suites)."""
    sql("UPDATE office_docs SET locked_at=?, status='issued', number=?, date=? WHERE id=?",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), number, day, did), write=True)


def cal_book(oid, tag, ags):
    """Alice's calendar + address book of organisation oid with bob (edit) and the agents ags as members, an event bob is
    invited to -> (calendar, book, event)."""
    A.patch(B + "/api/settings", json={"workspace": f"org:{oid}"})
    r = A.post(B + "/api/evcals", json={"name": f"{tag} calendar", "org_id": oid})
    check(r.status_code == 201 and r.json().get("org_id") == oid, f"{tag}: a calendar of the organisation {r.text[:160]}")
    k = r.json()["id"]
    r = A.post(B + "/api/books", json={"name": f"{tag} contacts", "org_id": oid})
    check(r.status_code == 201 and r.json().get("org_id") == oid, f"{tag}: an address book of the organisation {r.text[:160]}")
    bk = r.json()["id"]
    for who, role in ((BOB, "edit"), *((a, "view") for a in ags)):
        check(A.put(B + f"/api/evcals/{k}/members", json={"user_id": who, "role": role}).ok, f"{tag}: {who} in the calendar")
        check(A.put(B + f"/api/books/{bk}/members", json={"user_id": who, "role": role}).ok, f"{tag}: {who} in the address book")
    r = A.post(B + "/api/events", json={"title": f"{tag} meeting", "start": "2026-10-21T10:00", "end": "2026-10-21T11:00", "cal_id": k})
    check(r.status_code in (200, 201), f"{tag}: an event {r.text[:160]}")
    ev = r.json().get("id")
    check(A.patch(B + f"/api/events/{ev}", json={"attendees": [{"user_id": BOB}]}).ok, f"{tag}: bob invited to the event")
    check(sql("SELECT 1 FROM event_attendees WHERE event_id=? AND user_id=?", (ev, BOB)) != [], f"{tag}: bob is invited")
    check(k in ids(Bo.get(B + "/api/evcals")) and bk in ids(Bo.get(B + "/api/books")), f"{tag}: bob sees both before")
    return k, bk, ev


def gone_for(k, bk, ev, tag, agh=None):
    check(k not in ids(Bo.get(B + "/api/evcals")), f"{tag}: the former colleague no longer has the calendar")
    no(Bo.get(B + f"/api/evcals/{k}/export.ics"), f"{tag}: former colleague calendar export")
    no(Bo.patch(B + f"/api/evcals/{k}", json={"name": "x"}), f"{tag}: former colleague changes the calendar")
    check(bk not in ids(Bo.get(B + "/api/books")), f"{tag}: the former colleague no longer has the address book")
    no(Bo.get(B + f"/api/books/{bk}/export.vcf"), f"{tag}: former colleague address book export")
    check(not sql("SELECT 1 FROM ev_cal_members WHERE cal_id=? AND user_id=?", (k, BOB))
          and not sql("SELECT 1 FROM book_members WHERE book_id=? AND user_id=?", (bk, BOB)), f"{tag}: bob's member rows are gone")
    check(not sql("SELECT 1 FROM event_attendees WHERE event_id=? AND user_id=?", (ev, BOB)), f"{tag}: bob's invitation is gone")
    if agh:
        check(k not in ids(requests.get(V + "/event-calendars", headers=agh)), f"{tag}: the former agent lists no calendar (API v1)")
        no(requests.get(V + f"/event-calendars/{k}/export", headers=agh), f"{tag}: former agent calendar export (API v1)")
        check(bk not in ids(requests.get(V + "/address-books", headers=agh)), f"{tag}: the former agent lists no address book (API v1)")
        no(requests.get(V + f"/address-books/{bk}/export", headers=agh), f"{tag}: former agent address book export (API v1)")
    mine = {x["id"]: x for x in (A.get(B + "/api/evcals").json().get("items") or [])}
    check(k in mine and mine[k].get("org_id") is None, f"{tag}: the owner keeps the calendar, private")
    check(bk in ids(A.get(B + "/api/books")), f"{tag}: the owner keeps the address book")


# ================================================================== #4697 retire
R1 = org("Retire One")
member(R1, BOB)
AG, AGH = agent("retirebot", R1)
PA, _ = agent("alicebot", R1, owner=ALICE)
K1, BK1, EV1 = cal_book(R1, "retire", (AG, PA))
check(K1 in ids(requests.get(V + "/event-calendars", headers=AGH)), "retire: the agent lists the calendar before (API v1)")
r = A.post(B + "/api/office/docs", json={"project_title": "Event film"})
check(r.status_code == 201, "retire: a document " + r.text[:160])
lock_doc(r.json().get("id"))
r = A.delete(B + f"/api/admin/orgs/{R1}", params={"confirm": "1"})
check(r.ok and r.json().get("retired") is True, "retire: the organisation is retired " + r.text[:200])
gone_for(K1, BK1, EV1, "retire", AGH)
check(not sql("SELECT 1 FROM ev_cal_members WHERE cal_id=? AND user_id=?", (K1, AG)), "retire: the organisation's agent's row is gone")
check(sql("SELECT 1 FROM ev_cal_members WHERE cal_id=? AND user_id=?", (K1, PA)) != []
      and sql("SELECT 1 FROM book_members WHERE book_id=? AND user_id=?", (BK1, PA)) != [], "retire: the owner's own agent stays")

# ================================================================== #4697 delete (no retention)
D1 = org("Delete One")
member(D1, BOB)
AG2, AG2H = agent("deletebot", D1)
K2, BK2, EV2 = cal_book(D1, "delete", (AG2,))
A.patch(B + "/api/settings", json={"workspace": "private"})
r = A.delete(B + f"/api/admin/orgs/{D1}", params={"confirm": "1"})
check(r.ok and not r.json().get("retired") and not sql("SELECT 1 FROM orgs WHERE id=?", (D1,)), "delete: the organisation is gone " + r.text[:200])
gone_for(K2, BK2, EV2, "delete", AG2H)

# ================================================================== #4698 a: leave and join again the same day
K = org("Kappa")
SP = f"org:{K}"
for who in (BOB, GINA):
    member(K, who)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "bobbot", "display_name": "Bob bot", "owner_id": BOB})
BAG = r.json()["id"]  # somebody else's personal agent: only its owner may move it - set here as bob's agent of Kappa
sql("UPDATE agents SET org_id=? WHERE user_id=?", (K, BAG), write=True)
sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (K, BAG), write=True)
A.patch(B + "/api/settings", json={"workspace": SP})
r = A.post(B + "/api/team/channels", json={"name": "Closed room", "org_id": K, "members": [BOB, GINA]})
check(r.status_code in (200, 201), "a: a closed channel " + r.text[:160])
CC = r.json().get("id")
r = A.post(B + "/api/team/channels", json={"name": "Open room", "org_id": K, "open": True})
check(r.status_code in (200, 201), "a: an open channel " + r.text[:160])
OC = r.json().get("id")
check(Bo.post(B + f"/api/team/rooms/{OC}/members", json={"user_id": BOB}).ok, "a: bob joins the open channel")
r = A.post(B + "/api/wiki/pages", json={"space": SP, "path": "Internal/Plan", "body": "secret plan"})
check(r.status_code == 201, "a: a knowledge page " + r.text[:160])
PID = r.json().get("id")
FI = next((f["id"] for f in A.get(B + "/api/wiki", params={"space": SP}).json().get("folders", []) if f["path"] == "Internal"), None)
for who in (BOB, GINA):
    r = A.post(B + f"/api/files/nodes/{FI}/shares", json={"user_id": who, "role": "view"})
    check(r.status_code == 201, f"a: the folder shared with {who} {r.text[:160]}")
now = datetime.now(timezone.utc).isoformat(timespec="seconds")
sql("INSERT INTO fs_shares(node_id,agent_id,role,created_by,created_at) SELECT id, ?, 'edit', ?, ? FROM fs_nodes WHERE kind='ref' "
    "AND ref_kind='tchat_room' AND ref_id=? AND NOT EXISTS (SELECT 1 FROM fs_shares x WHERE x.node_id=fs_nodes.id AND x.agent_id=?)",
    (BAG, BOB, now, CC, BAG), write=True)  # 2.924.0 (#5069): bob's agent as a share of the room's node
sql("INSERT INTO fs_shares(node_id,agent_id,role,created_by,created_at) VALUES(?,?,'view',?,?)", (FI, BAG, ALICE, now), write=True)
check(Gi.get(B + f"/api/team/rooms/{CC}/messages").ok, "a: gina reads the closed channel before")
for who in (BOB, GINA):
    check(A.delete(B + f"/api/orgs/{K}/members/{who}").ok, f"a: {who} leaves Kappa")
check(not sql("SELECT 1 FROM " + TCHAT_M + " WHERE user_id IN (?,?,?) AND room_id IN (?,?)", (BOB, GINA, BAG, CC, OC)),
      "a: no channel member rows of the leavers (nor bob's agent)")
check(not sql("SELECT 1 FROM fs_shares WHERE user_id IN (?,?) OR agent_id=?", (BOB, GINA, BAG)), "a: no folder shares of the leavers (nor bob's agent)")
check(not sql("SELECT 1 FROM agents WHERE user_id=? AND org_id IS NOT NULL", (BAG,)), "a: bob's agent left with him")
check(sql("SELECT 1 FROM " + TCHAT_M + " WHERE room_id=? AND user_id=?", (CC, ALICE)) != [], "a: the channel's other member stays")
member(K, BOB, "member")
member(K, GINA, "guest")
for s, who in ((Bo, "bob (member again)"), (Gi, "gina (guest)")):
    no(s.get(B + f"/api/team/rooms/{CC}/messages"), f"a: {who} reads no old closed channel")
    r = s.get(B + "/api/team/channels")
    check(not r.ok or CC not in {x.get("id") for x in r.json().get("channels") or []}, f"a: {who} does not list the old closed channel")
no(Gi.get(B + f"/api/wiki/pages/{PID}"), "a: gina (guest) reads no page of the old folder share")
sh = Gi.get(B + "/api/wiki/shared").json()
check(not sh.get("pages") and not sh.get("folders"), f"a: gina (guest) has no old shared folders {str(sh)[:160]}")

# ================================================================== #4698 b: made a guest
check(Bo.post(B + f"/api/team/rooms/{OC}/members", json={"user_id": BOB}).ok, "b: bob joins the open channel again")
r = A.post(B + "/api/team/channels", json={"name": "Closed two", "org_id": K, "members": [BOB]})
CC2 = r.json().get("id") if r.status_code in (200, 201) else None
check(CC2, "b: a closed channel with bob " + r.text[:160])
check(Bo.get(B + f"/api/team/rooms/{OC}/messages").ok and Bo.post(B + f"/api/team/rooms/{OC}/messages", json={"body": "hello"}).status_code in (200, 201),
      "b: bob reads and writes in the open channel as a member")
member(K, BOB, "guest")
check(not sql("SELECT 1 FROM " + TCHAT_M + " WHERE room_id=? AND user_id=?", (OC, BOB)), "b: the guest's row in the open channel is gone")
check(sql("SELECT 1 FROM " + TCHAT_M + " WHERE room_id=? AND user_id=?", (CC2, BOB)) != [], "b: the closed channel stays (personal invitation)")
no(Bo.get(B + f"/api/team/rooms/{OC}/messages"), "b: the guest reads the open channel no more")
no(Bo.post(B + f"/api/team/rooms/{OC}/messages", json={"body": "still here"}), "b: the guest writes in the open channel no more")
check(Bo.get(B + f"/api/team/rooms/{CC2}/messages").ok, "b: the guest still reads the closed channel")

# ================================================================== #4698 c: links of a maker made guest
member(K, RITA)
Ri.patch(B + "/api/settings", json={"workspace": SP})
r = Ri.post(B + "/api/wiki/pages", json={"space": SP, "path": "Rita/Note", "body": "rita's note"})
check(r.status_code == 201, "c: rita writes a page " + r.text[:160])
r = Ri.post(B + "/api/wiki/shares", json={"page_id": r.json().get("id"), "kind": "link"})
check(r.status_code == 201 and "/s/w/" in r.json().get("url", ""), "c: rita makes a public link of the page " + r.text[:160])
WL = "/s/w/" + r.json().get("url", "/s/w/x").split("/s/w/", 1)[1]
r = Ri.post(B + "/api/lists", json={"name": "Rita plan", "org_id": K})
RL = r.json()["id"]
r = Ri.put(B + f"/api/lists/{RL}/public-link", json={"mode": "view"})
check(r.ok, "c: rita makes a public link of her project " + r.text[:160])
PL = "/s/" + ((r.json().get("link") or {}).get("url") or "/s/x").split("/s/", 1)[1]
anon = requests.Session()
check(anon.get(B + WL).status_code == 200 and anon.get(B + PL).status_code == 200, "c: both links open before")
member(K, RITA, "guest")
check(anon.get(B + WL).status_code in (404, 410), "c: the knowledge link of a maker made guest ends")
check(anon.get(B + PL).status_code in (404, 410), "c: the project link of a maker made guest ends")
member(K, RITA, "member")
check(anon.get(B + WL).status_code == 200 and anon.get(B + PL).status_code == 200, "c: member again: both links open again")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Notes/Own", "body": "own note"})
r = Fr.post(B + "/api/wiki/shares", json={"page_id": r.json().get("id"), "kind": "link"}) if r.status_code == 201 else r
check(r.status_code == 201, "freelancer: a public link of a private page " + r.text[:160])
FWL = "/s/w/" + r.json().get("url", "/s/w/x").split("/s/w/", 1)[1] if r.status_code == 201 else "/s/w/x"
FL = Fr.post(B + "/api/lists", json={"name": "Own plan"}).json()["id"]
r = Fr.put(B + f"/api/lists/{FL}/public-link", json={"mode": "view"})
FPL = "/s/" + ((r.json().get("link") or {}).get("url") or "/s/x").split("/s/", 1)[1] if r.ok else "/s/x"
check(anon.get(B + FWL).status_code == 200 and anon.get(B + FPL).status_code == 200, "freelancer: the own public links open")

sys.exit(kt.done("p2560_a_orgrights"))
