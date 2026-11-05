#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.566.0 part C (#4712): calendars and address books on the shared core (stage 3). Own container (mode workspaces). Invented
names only.  tenant-matrix: calendar, book   freelancer-matrix: pim
 - a calendar / an address book shared with a person gets its reference node; the trigger mirrors the member row into the
   node's share (added, role changed, deleted); the person sees it through the core
 - a share taken back in the core (the node's share gone, the old member row still there) is not reopened by the old row
   (regression: before, ev_cal_members / book_members alone gave the access); sharing again brings it back
 - an old member row of a calendar WITHOUT a node is still read (the fallback of one release)
 - a workspace move of a calendar / book: its node follows with the shares, the member keeps it
 - leaving the organisation: the core's revocation takes the member rows and the shares (restorable rows in obj_revoked) (#4697)
 - an agent with the data lock "calendar" / "contacts" sees nothing of a calendar / book shared with it through the core (#4699)
 - two writers: an event saved with an old version (expect, and the core's name expect_updated_at) -> 409 with the event as it is,
   the other's change stays; CalDAV PUT with an old If-Match -> 412, the change stays; calendar settings with an old
   expect_updated_at -> 409 with "current", one with the version -> changed, in the core's history (#4703, #4705)
 - deleting a calendar puts it into the trash with its events (gone from the lists, the range, CalDAV); only its owner restores
   it (a member 404), with exactly the events that went with it (#4707)
 - a person without an organisation: her own calendar shared with her agent, the trash and the restore as above
 - the start's one-shot (migr_kern4712, a restart on the same data): members without a node get it and their core shares
usage: p2566_c_kern_cal_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
import requests  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check, sess  # noqa: E402

FEAT = "cal,events,contacts,comments,collab,files"
V = B + "/api/v1"
D = "2026-11-17"

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_API_RATE": "100000"}, prefix="P2566C")


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


def node(kind, rid):
    r = sql("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (kind, rid))
    return r[0][0] if r else None


def share(kind, rid, who):
    """The role of the core share of account who on the object's node (None: none)."""
    r = sql("SELECT s.role FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=? "
            "AND (s.user_id=? OR s.agent_id=?)", (kind, rid, who, who))
    return r[0][0] if r else None


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
ALICE = A.get(B + "/api/me").json()["id"]
uid, S = {}, {}
for u in ("bob", "gina"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    S[u] = sess(u)
    S[u].patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Bo, Gi = S["bob"], S["gina"]
BOB, GINA = uid["bob"], uid["gina"]

r = A.post(B + "/api/admin/orgs", json={"name": "Northwind Studio"})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT (org_id,user_id) DO UPDATE SET role='admin'", (ORG, ALICE), write=True)
for who in (BOB, GINA):
    mail = sql("SELECT email FROM users WHERE id=?", (who,))[0][0]
    r = A.put(B + f"/api/orgs/{ORG}/members", json={"email": mail, "role": "member"})
    check(r.ok and sql("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (ORG, who)) == [("member",)], f"setup: {who} member {r.text[:160]}")

# ================================================================== the calendar's share is the core's
K = A.post(B + "/api/evcals", json={"name": "Studio plan", "org_id": ORG}).json()["id"]
check(node("evcal", K) is None, "a calendar without members has no node yet")
check(A.put(B + f"/api/evcals/{K}/members", json={"user_id": BOB, "role": "edit"}).ok, "the calendar shared with bob")
check(node("evcal", K) is not None and share("evcal", K, BOB) == "edit", "#4712: its node and bob's core share (mirrored by the trigger)")
check(K in ids(Bo.get(B + "/api/evcals")), "bob sees the calendar")
E1 = A.post(B + "/api/events", json={"cal_id": K, "title": "Kick-off", "start": f"{D}T09:00", "end": f"{D}T10:00"}).json()
check(bool(E1.get("id")) and E1.get("updated_at"), f"an event in it {str(E1)[:120]}")
m = {x["user_id"]: x["role"] for x in {c["id"]: c for c in A.get(B + "/api/evcals").json()["items"]}[K]["members"]}
check(m == {BOB: "edit"}, f"the owner's member list comes from the core {m}")

sql("UPDATE ev_cal_members SET role='view' WHERE cal_id=? AND user_id=?", (K, BOB), write=True)
check(share("evcal", K, BOB) == "view", "#4712: a role changed in the old table follows into the core share (any code path)")
check(Bo.patch(B + f"/api/events/{E1['id']}", json={"title": "x"}).status_code == 403, "bob, now view, cannot change the event")
check(A.put(B + f"/api/evcals/{K}/members", json={"user_id": BOB, "role": "edit"}).ok, "bob back to edit")

# a share taken back in the core: the old row must not reopen it (regression of the fallback)
sql("DELETE FROM fs_shares WHERE node_id=? AND user_id=?", (node("evcal", K), BOB), write=True)
check(sql("SELECT role FROM ev_cal_members WHERE cal_id=? AND user_id=?", (K, BOB)) == [("edit",)], "the old member row is still there")
check(K not in ids(Bo.get(B + "/api/evcals")), "#4712: the core share is gone -> bob no longer sees the calendar (old row not read)")
check(Bo.get(B + f"/api/events/{E1['id']}").status_code == 404, "#4712: nor its event")
check(Bo.get(B + "/api/events", params={"from": D, "to": D, "calendar_id": K}).status_code == 404, "#4712: nor its range")
check(A.put(B + f"/api/evcals/{K}/members", json={"user_id": BOB, "role": "edit"}).ok and share("evcal", K, BOB) == "edit",
      "sharing again puts the core share back")
check(K in ids(Bo.get(B + "/api/evcals")), "bob sees it again")
check(A.delete(B + f"/api/evcals/{K}/members/{GINA}").status_code == 404, "removing someone who is no member: 404")

# the fallback: an old member row of a calendar without a node is read
K2 = A.post(B + "/api/evcals", json={"name": "Old style", "org_id": ORG}).json()["id"]
sql("INSERT INTO ev_cal_members(cal_id,user_id,role,added_at) VALUES(?,?,'view','2026-11-01T00:00:00+00:00')", (K2, GINA), write=True)
check(node("evcal", K2) is None and K2 in ids(Gi.get(B + "/api/evcals")), "#4712: without a node the old member row still counts")
sql("DELETE FROM ev_cal_members WHERE cal_id=? AND user_id=?", (K2, GINA), write=True)
check(K2 not in ids(Gi.get(B + "/api/evcals")), "and without it nothing")

# ================================================================== the address book's share is the core's
BK = A.post(B + "/api/books", json={"name": "Studio contacts", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/books/{BK}/members", json={"user_id": GINA, "role": "edit"}).ok, "the book shared with gina")
check(node("address_book", BK) is not None and share("address_book", BK, GINA) == "edit", "#4712: the book's node and gina's core share")
check(BK in ids(Gi.get(B + "/api/books")), "gina sees the book")
C1 = A.post(B + "/api/contacts", json={"book_id": BK, "given": "Mara", "family": "Lind"}).json()
sql("DELETE FROM fs_shares WHERE node_id=? AND user_id=?", (node("address_book", BK), GINA), write=True)
check(BK not in ids(Gi.get(B + "/api/books")) and Gi.get(B + f"/api/contacts/{C1['id']}").status_code == 404,
      "#4712: the book's core share gone -> gina no longer sees it nor its contact (old row not read)")
check(A.put(B + f"/api/books/{BK}/members", json={"user_id": GINA, "role": "edit"}).ok and BK in ids(Gi.get(B + "/api/books")),
      "sharing the book again")
sql("DELETE FROM book_members WHERE book_id=? AND user_id=?", (BK, GINA), write=True)
check(share("address_book", BK, GINA) is None and BK not in ids(Gi.get(B + "/api/books")), "#4712: the old row deleted -> the core share goes too")
check(A.put(B + f"/api/books/{BK}/members", json={"user_id": GINA, "role": "edit"}).ok, "gina back in the book")

# a workspace move: the node follows with its shares (the members keep the object)
for kind, url, rid, who, sx in (("evcal", "evcals", K, BOB, Bo), ("address_book", "books", BK, GINA, Gi)):
    check(A.patch(B + f"/api/{url}/{rid}", json={"org_id": None}).ok, f"{kind}: moved into alice's private space")
    check(sql("SELECT org_id FROM fs_nodes WHERE id=?", (node(kind, rid),)) == [(None,)] and share(kind, rid, who) == "edit",
          f"#4712: {kind}: its node followed into the private tree with the share")
    check(rid in ids(sx.get(B + f"/api/{url}")), f"#4712: {kind}: the member keeps it after the move")
    check(A.patch(B + f"/api/{url}/{rid}", json={"org_id": ORG}).ok and sql("SELECT org_id FROM fs_nodes WHERE id=?", (node(kind, rid),)) == [(ORG,)]
          and rid in ids(sx.get(B + f"/api/{url}")), f"#4712: {kind}: and back into the organisation")

# ================================================================== two writers (#4703, #4705)
old = E1["updated_at"]
r = Bo.patch(B + f"/api/events/{E1['id']}", json={"title": "Kick-off (moved)", "expect": old})
check(r.ok, f"bob saves with the version he read {r.status_code} {r.text[:160]}")
r = A.patch(B + f"/api/events/{E1['id']}", json={"title": "Kick-off (Alice)", "expect": old})
check(r.status_code == 409, f"#4703: alice with the old version -> 409 ({r.status_code})")
r = A.patch(B + f"/api/events/{E1['id']}", json={"title": "Kick-off (Alice)", "expect_updated_at": old})
check(r.status_code == 409, f"#4712: the core's name expect_updated_at is the same as expect ({r.status_code})")
check(A.get(B + f"/api/events/{E1['id']}").json()["title"] == "Kick-off (moved)", "#4703: bob's change stays")
cur = A.get(B + f"/api/events/{E1['id']}").json()["updated_at"]
check(A.patch(B + f"/api/events/{E1['id']}", json={"title": "Kick-off (Alice)", "expect_updated_at": cur}).ok, "with the current version it saves")

# CalDAV: If-Match is compared under the lock
r = A.post(B + "/api/me/app-passwords", json={"name": "Phone"})
DPW = r.json()["password"]


def dav(m, path, data=None, **hd):
    return requests.request(m, B + path, auth=("alice", DPW), data=data.encode() if isinstance(data, str) else data,
                            headers={"X-Forwarded-Proto": "https", **hd}, allow_redirects=False, timeout=30)


href = sql("SELECT href FROM events WHERE id=?", (E1["id"],))[0][0]
P = f"/dav/calendars/alice/e{K}/{href}"
g = dav("GET", P)
check(g.status_code == 200 and g.headers.get("ETag"), f"CalDAV GET {g.status_code}")
check(Bo.patch(B + f"/api/events/{E1['id']}", json={"location": "Room 2"}).ok, "bob changes the event in the app")
body = g.text.replace("SUMMARY:Kick-off (Alice)", "SUMMARY:Phone title")
r = dav("PUT", P, body, **{"Content-Type": "text/calendar; charset=utf-8", "If-Match": g.headers["ETag"]})
check(r.status_code == 412, f"#4703: a PUT with the old ETag -> 412 ({r.status_code})")
e = A.get(B + f"/api/events/{E1['id']}").json()
check(e["location"] == "Room 2" and e["title"] == "Kick-off (Alice)", "#4703: bob's change stays, the phone's is not taken")
g2 = dav("GET", P)
r = dav("PUT", P, g2.text.replace("SUMMARY:Kick-off (Alice)", "SUMMARY:Phone title"),
        **{"Content-Type": "text/calendar; charset=utf-8", "If-Match": g2.headers["ETag"]})
check(r.status_code == 204 and A.get(B + f"/api/events/{E1['id']}").json()["title"] == "Phone title", f"with the current ETag it saves ({r.status_code})")

# calendar settings through the core's write path
kc = {c["id"]: c for c in A.get(B + "/api/evcals").json()["items"]}[K]
check(bool(kc.get("updated_at")), "the calendar names its version")
r = A.patch(B + f"/api/evcals/{K}", json={"name": "Studio plan 2026", "expect_updated_at": kc["updated_at"]})
check(r.ok and r.json()["name"] == "Studio plan 2026", f"#4712: renamed with its version {r.status_code} {r.text[:160]}")
r = A.patch(B + f"/api/evcals/{K}", json={"color": "#4ade80", "expect_updated_at": kc["updated_at"]})
check(r.status_code == 409 and (r.json().get("current") or {}).get("name") == "Studio plan 2026",
      f"#4712: an old version -> 409 with the calendar as it is under current ({r.status_code} {r.text[:160]})")
check(sql("SELECT COUNT(*) FROM obj_history WHERE kind='evcal' AND ref_id=?", (K,))[0][0] >= 1, "#4712: the change is in the core's history")
check(sql("SELECT name FROM fs_nodes WHERE id=?", (node("evcal", K),))[0][0] == "Studio plan 2026", "the node carries the new name")
check(A.patch(B + f"/api/evcals/{K}", json={"color": "#4ade80"}).ok, "without a version the old behaviour (saves)")
check(Bo.patch(B + f"/api/evcals/{K}", json={"name": "Bob's"}).status_code == 403, "a member with edit still cannot change the settings")

# ================================================================== leaving the organisation (#4697 through the core)
check(A.delete(B + f"/api/orgs/{ORG}/members/{GINA}").ok, "gina leaves the organisation")
check(BK not in ids(Gi.get(B + "/api/books")), "#4697: gina no longer has the organisation's book")
check(not sql("SELECT 1 FROM book_members WHERE book_id=? AND user_id=?", (BK, GINA)) and share("address_book", BK, GINA) is None,
      "#4712: her member row and her core share are gone")
check(sql("SELECT COUNT(*) FROM obj_revoked WHERE user_id=? AND reason='leave' AND src IN ('book_members','fs_shares')", (GINA,))[0][0] >= 1,
      "#4712: taken by the core's revocation (restorable rows)")

# ================================================================== the trash (#4707)
E2 = A.post(B + "/api/events", json={"cal_id": K, "title": "Review", "start": f"{D}T14:00", "end": f"{D}T15:00"}).json()
E3 = A.post(B + "/api/events", json={"cal_id": K, "title": "Deleted before", "start": f"{D}T16:00", "end": f"{D}T17:00"}).json()
check(A.delete(B + f"/api/events/{E3['id']}").ok, "one event deleted before")
check(A.delete(B + f"/api/evcals/{K}").ok, "#4707: alice deletes the calendar")
check(sql("SELECT deleted_at IS NOT NULL FROM ev_cals WHERE id=?", (K,)) == [(True,)], "#4707: the calendar row stays (in the trash)")
check(K not in ids(A.get(B + "/api/evcals")) and K not in ids(Bo.get(B + "/api/evcals")), "#4707: gone from the lists")
rng = A.get(B + "/api/events", params={"from": D, "to": D}).json().get("items") or []
check(not [x for x in rng if x.get("cal_id") == K], "#4707: its events are gone from the range")
check(A.get(B + f"/api/events/{E2['id']}").status_code == 404, "#4707: and as single events")
check(dav("GET", P).status_code == 404, "#4707: and on the phone")
tr_ = A.get(B + "/api/evcals/trash").json()
t = {x["id"]: x for x in tr_.get("items") or []}
check(K in t and t[K]["events"] == 2, f"#4707: the trash lists it with its two events {tr_}")
check(K not in {x["id"] for x in Bo.get(B + "/api/evcals/trash").json().get("items") or []}, "a member's trash does not list it")
check(Bo.post(B + f"/api/evcals/{K}/restore").status_code == 404, "#4707: a member cannot restore it")
r = A.post(B + f"/api/evcals/{K}/restore")
check(r.ok and r.json()["id"] == K, f"#4707: its owner restores it {r.status_code} {r.text[:120]}")
check(K in ids(A.get(B + "/api/evcals")) and K in ids(Bo.get(B + "/api/evcals")), "#4707: back for the owner and the member")
check(A.get(B + f"/api/events/{E2['id']}").ok and A.get(B + f"/api/events/{E1['id']}").ok, "#4707: its events are back")
check(A.get(B + f"/api/events/{E3['id']}").status_code == 404, "#4707: the event deleted before stays deleted")
check(A.post(B + f"/api/evcals/{K}/restore").status_code == 404, "restoring a calendar not in the trash: 404")

# ================================================================== a person without an organisation, her agent (#4699)
FID, F = freelancer(B, A)
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": ["read", "calendar", "contacts"]})
check(r.status_code in (200, 201), f"her personal agent {r.status_code} {r.text[:120]}")
FA, FH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
sql("INSERT INTO user_settings(user_id,key,value) VALUES(?,'features',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
    (FA, "events,contacts,collab"), write=True)
FK = F.post(B + "/api/evcals", json={"name": "Frida"}).json()["id"]
FB = F.post(B + "/api/books", json={"name": "Frida's clients"}).json()["id"]
check(F.put(B + f"/api/evcals/{FK}/members", json={"user_id": FA, "role": "edit"}).ok
      and F.put(B + f"/api/books/{FB}/members", json={"user_id": FA, "role": "view"}).ok, "freelancer: calendar and book shared with her agent")
check(share("evcal", FK, FA) == "edit" and share("address_book", FB, FA) == "view", "freelancer: the agent's core shares (as agent_id)")
check(sql("SELECT COUNT(*) FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.ref_kind='evcal' AND n.ref_id=? AND s.agent_id=?",
          (FK, FA))[0][0] == 1, "freelancer: an agent's share is an agent share")
FE = F.post(B + "/api/events", json={"cal_id": FK, "title": "Dentist", "start": f"{D}T08:00", "end": f"{D}T09:00"}).json()
ag = lambda p: requests.get(V + p, headers=FH, timeout=30)  # noqa: E731
check(FK in ids(ag("/event-calendars")) and FB in ids(ag("/address-books")), "freelancer: the agent sees calendar and book")
r = F.patch(B + f"/api/agents/{FA}/data-lock", json={"areas": {"calendar": True, "contacts": True}})
check(r.status_code == 200, f"freelancer: the data lock on {r.status_code} {r.text[:120]}")
check(FK not in ids(ag("/event-calendars")) and ag(f"/events/{FE['id']}").status_code == 404, "#4699: locked, no calendar, no event")
check(FB not in ids(ag("/address-books")), "#4699: locked, no address book")
check(F.patch(B + f"/api/agents/{FA}/data-lock", json={"areas": {"calendar": False, "contacts": False}}).status_code == 200
      and FK in ids(ag("/event-calendars")), "freelancer: unlocked, the calendar again")
check(F.delete(B + f"/api/evcals/{FK}").ok and FK not in ids(F.get(B + "/api/evcals")), "freelancer: her calendar into the trash")
check(FK not in ids(ag("/event-calendars")), "freelancer: gone for her agent too")
check(F.post(B + f"/api/evcals/{FK}/restore").ok and FK in ids(F.get(B + "/api/evcals")) and F.get(B + f"/api/events/{FE['id']}").ok,
      "freelancer: restored with its event")

# ================================================================== the one-shot copy at the start (migr_kern4712)
K3 = A.post(B + "/api/evcals", json={"name": "Before the update"}).json()["id"]
B3 = A.post(B + "/api/books", json={"name": "Old book"}).json()["id"]
sql("INSERT INTO ev_cal_members(cal_id,user_id,role,added_at) VALUES(?,?,'edit','2026-11-01T00:00:00+00:00')", (K3, BOB), write=True)
sql("INSERT INTO book_members(book_id,user_id,role,added_at) VALUES(?,?,'view','2026-11-01T00:00:00+00:00')", (B3, BOB), write=True)
sql("UPDATE ev_cals SET updated_at='' WHERE id=?", (K3,), write=True)
check(node("evcal", K3) is None and node("address_book", B3) is None, "rows of an older version: members without a node")
sql("DELETE FROM settings WHERE key='migr_kern4712'", write=True)
if kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_API_RATE": "100000"}, prefix="P2566C", keep=True):
    check(share("evcal", K3, BOB) == "edit" and share("address_book", B3, BOB) == "view",
          "#4712: the start's one-shot gave them their nodes and copied the members into the core's shares")
    check(sql("SELECT updated_at<>'' FROM ev_cals WHERE id=?", (K3,)) == [(True,)], "#4712: the one-shot set the calendar's version")
    check(sql("SELECT value FROM settings WHERE key='migr_kern4712'") == [("1",)], "#4712: and set its flag")
    Bo2 = sess("bob")
    check(K3 in ids(Bo2.get(B + "/api/evcals")) and B3 in ids(Bo2.get(B + "/api/books")), "#4712: bob keeps both after the copy")

sys.exit(kt.done("p2566_c_kern_cal"))
