#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.361.2 B (#2923): one rule for the other areas -- knowledge pages, office clients and drafts, video sign-offs, polls
and bookmarks leave an organisation only through its admin, or into the maker's private space after an admin released
the maker's request (before, the maker took them out alone, without a log or a word to the admins). Invented names only,
addresses @example.com. tenant-matrix: org
 - per area: the maker (a plain member) gets 403 with out_request (the dry run: block + out_request); asking
   (POST /api/orgs/<oid>/out-requests) and an admin's release let the move go through; the organisation's log has
   "moveout" with released, the admins are told; the release is used up (out again after moving it back in: 403)
 - another member (not the maker) gets 403 without out_request; moving it to another organisation needs an admin
 - an admin takes it out without asking (logged, not released)
 - the dry run of a move INTO the organisation names the way back for a member
 - office: undoing a member's move into the organisation is a move out (403 with out_request)
 - a person without an organisation (freelancer-matrix: wiki, polls, bookmarks): the own private things stay as they are,
   there is no other workspace (409), never a request
usage: p23612_b_api_test.py <datadir>      (P23612B_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402

FEAT = "sheets,wiki,collab,comments,cal,events,office,clients,reading"
BACK = "Back into your private space only after an admin of the organisation releases it"
TIMES = [{"start": "2031-03-10T10:00"}, {"start": "2031-03-11T14:30"}]


def usess(user):
    s = sess(user)
    r = s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def log(action, kind):
    out = []
    for name, d in sql("SELECT list_name, detail FROM org_list_log WHERE action=? ORDER BY id", (action,)):
        d = json.loads(d) if isinstance(d, str) else (d or {})
        if d.get("kind") == kind:
            out.append(dict(d, name=name))
    return out


def news_moveout(uid, kind):
    out = []
    for (d,) in sql("SELECT data FROM notifications WHERE user_id=? AND kind='orglist'", (uid,)):
        d = json.loads(d) if isinstance(d, str) else (d or {})
        if d.get("action") == "moveout" and d.get("kind") == kind:
            out.append(d)
    return out


def release(s, kind, oid_):
    """The maker asks, alice releases (one click)."""
    r = s.post(B + f"/api/orgs/{ORG}/out-requests", json={"kind": kind, "id": oid_})
    check(r.ok and r.json().get("state") == "open", f"{kind}: the maker asks " + r.text[:200])
    r = A.post(B + f"/api/orgs/{ORG}/out-requests/{r.json().get('id')}", json={"decision": "approve"})
    check(r.ok and r.json().get("state") == "approved", f"{kind}: alice releases it " + r.text[:200])


def refused(r, kind, oid_, what):
    check(r.status_code == 403 and r.json().get("out_request") == {"org": ORG, "kind": kind, "id": oid_}, what + ": 403 with out_request " + r.text[:300])


def dry_refused(r, kind, oid_, what):
    check(r.ok and r.json().get("block") and r.json().get("out_request") == {"org": ORG, "kind": kind, "id": oid_},
          what + ": the dry run's block carries out_request " + r.text[:300])


def released_logged(kind, what):
    check(any(x.get("released") and x.get("to") == "private" for x in log("moveout", kind)), what + ": logged as released")
    check(news_moveout(ERIN, kind), what + ": the other admin is told")


if not os.environ.get("P23612B_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = usess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = usess("alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
for u, role in (("bob", "member"), ("carol", "member"), ("erin", "admin")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["bob"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ca, Er = usess("bob"), usess("carol"), usess("erin")
BOB, ERIN = uid["bob"], uid["erin"]
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})

# ================================================================ knowledge pages
r = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Bob/Notes", "body": "bob's text"})
assert r.status_code == 201, r.text
WP = r.json()["id"]
WMV = {"pages": [WP], "space": SP, "to": "private", "dest": ""}
dry_refused(Bo.post(B + "/api/wiki/move-space", json={**WMV, "dry": 1}), "wiki", WP, "wiki")
refused(Bo.post(B + "/api/wiki/move-space", json=WMV), "wiki", WP, "wiki: the maker without a release")
r = Bo.post(B + "/api/wiki/move-space", json={**WMV, "to": f"org:{BETA}"})
check(r.status_code == 403 and not r.json().get("out_request"), "wiki: into another organisation only by an admin of Alpha " + r.text[:200])
r = Ca.post(B + "/api/wiki/move-space", json=WMV)
check(r.status_code == 403 and not r.json().get("out_request"), "wiki: another member: 403 without out_request " + r.text[:200])
check(sql("SELECT org_id FROM wiki_pages WHERE id=?", (WP,))[0][0] == ORG, "wiki: the page stays in Alpha")
release(Bo, "wiki", WP)
r = Bo.post(B + "/api/wiki/move-space", json={**WMV, "dry": 1})
check(r.ok and not r.json().get("block"), "wiki: after the release the dry run passes " + r.text[:200])
r = Bo.post(B + "/api/wiki/move-space", json=WMV)
check(r.ok and sql("SELECT org_id, owner_id FROM wiki_pages WHERE id=?", (WP,))[0] == (None, BOB), "wiki: bob moves it private " + r.text[:200])
released_logged("wiki", "wiki")
r = Bo.post(B + "/api/wiki/move-space", json={"pages": [WP], "space": "private", "to": SP, "dest": "", "dry": 1})
check(r.ok and any(BACK in n for n in r.json().get("notes", [])), "wiki: the dry run into Alpha names the way back " + r.text[:300])
check(Bo.post(B + "/api/wiki/move-space", json={"pages": [WP], "space": "private", "to": SP, "dest": ""}).ok, "wiki: into Alpha again")
check(Bo.post(B + "/api/wiki/move-space", json=WMV).status_code == 403, "wiki: the release is used up")
r = A.post(B + "/api/wiki/move-space", json={**WMV, "dry": 1})
check(r.ok and not r.json().get("block") and not any(BACK in n for n in r.json().get("notes", [])), "wiki: an admin is not refused " + r.text[:200])

# ================================================================ office: clients, drafts, undo
O = "/api/office"
for s in (Bo, A):
    assert s.patch(B + "/api/settings", json={"workspace": SP}).ok
r = Bo.post(B + "/api/clients", json={"name": "Bobs Kunde KG", "org_id": ORG})
assert r.ok, r.text
CL = r.json()["id"]
CMV = {"what": "clients", "ids": [CL], "to": "private"}
dry_refused(Bo.post(B + O + "/move-space", json={**CMV, "dry": 1}), "clients", CL, "clients")
refused(Bo.post(B + O + "/move-space", json=CMV), "clients", CL, "clients: the maker without a release")
r = Ca.post(B + O + "/move-space", json={**CMV, "dry": 1})
check((r.status_code in (403, 404)) or (r.ok and r.json().get("block") and not r.json().get("out_request")),
      "clients: another member gets no way out " + r.text[:200])
release(Bo, "clients", CL)
r = Bo.post(B + O + "/move-space", json=CMV)
check(r.ok and sql("SELECT org_id, created_by FROM clients WHERE id=?", (CL,))[0] == (None, BOB), "clients: bob moves it private " + r.text[:200])
released_logged("clients", "clients")
check(Bo.post(B + O + "/move-space", json={**CMV, "to": SP}).ok, "clients: into Alpha again")
check(Bo.post(B + O + "/move-space", json=CMV).status_code == 403, "clients: the release is used up")
r = Bo.post(B + O + "/docs", json={"project_title": "Bobs Entwurf", "client_id": CL})
check(r.status_code == 201, "drafts: setup, bob makes a draft in Alpha's office " + r.text[:200])
DR = r.json().get("id")
DMV = {"what": "drafts", "ids": [DR], "to": "private"}
dry_refused(Bo.post(B + O + "/move-space", json={**DMV, "dry": 1}), "drafts", DR, "drafts")
release(Bo, "drafts", DR)
r = Bo.post(B + O + "/move-space", json=DMV)
check(r.ok and r.json().get("count", {}).get("drafts") == 1, "drafts: bob moves his draft private " + r.text[:200])
released_logged("drafts", "drafts")
# the undo of a move INTO the organisation takes it out again
assert Bo.patch(B + "/api/settings", json={"workspace": "private"}).ok
r = Bo.post(B + "/api/clients", json={"name": "Zweiter Kunde", "org_id": None})
C2 = r.json()["id"]
r = Bo.post(B + O + "/move-space", json={"what": "clients", "ids": [C2], "to": SP, "dry": 1})
check(r.ok and any(BACK in n for n in r.json().get("notes", [])), "clients: the dry run into Alpha names the way back " + r.text[:300])
r = Bo.post(B + O + "/move-space", json={"what": "clients", "ids": [C2], "to": SP})
check(r.ok and r.json().get("move_id"), "clients: bob moves a private client into Alpha " + r.text[:200])
refused(Bo.post(B + O + "/move-space", json={"undo": r.json().get("move_id")}), "clients", C2, "office undo (out of Alpha again)")
check(sql("SELECT org_id FROM clients WHERE id=?", (C2,))[0][0] == ORG, "office undo: the client stays in Alpha")
r = A.post(B + "/api/clients", json={"name": "Adminkunde", "org_id": ORG})
r = A.post(B + O + "/move-space", json={"what": "clients", "ids": [r.json()["id"]], "to": "private"})
check(r.ok and any(not x.get("released") for x in log("moveout", "clients")), "clients: an admin takes one out, logged (not released) " + r.text[:200])

# ================================================================ video sign-offs
LO = Bo.post(B + "/api/lists", json={"name": "Filmprojekt", "org_id": ORG}).json()["id"]
LP = Bo.post(B + "/api/lists", json={"name": "Privat", "org_id": None}).json()["id"]
r = Bo.post(B + "/api/videos", json={"list_id": LO, "url": "https://example.com/film.webm", "title": "Rohschnitt"})
check(r.ok and r.json().get("org_id") == ORG, "video: setup, bob's review in Alpha " + r.text[:200])
VD = r.json().get("id")
VMV = {"to": "private", "place": LP}
dry_refused(Bo.post(B + f"/api/videos/{VD}/move-space", json={**VMV, "dry": 1}), "video", VD, "video")
refused(Bo.post(B + f"/api/videos/{VD}/move-space", json=VMV), "video", VD, "video: the maker without a release")
release(Bo, "video", VD)
r = Bo.post(B + f"/api/videos/{VD}/move-space", json=VMV)
check(r.ok and sql("SELECT org_id FROM video_reviews WHERE id=?", (VD,))[0][0] is None, "video: bob moves it private " + r.text[:200])
released_logged("video", "video")
r = Bo.post(B + f"/api/videos/{VD}/move-space", json={"to": SP, "place": LO, "dry": 1})
check(r.ok and any(BACK in n for n in r.json().get("notes", [])), "video: the dry run into Alpha names the way back " + r.text[:300])
check(Bo.post(B + f"/api/videos/{VD}/move-space", json={"to": SP, "place": LO}).ok, "video: into Alpha again")
check(Bo.post(B + f"/api/videos/{VD}/move-space", json=VMV).status_code == 403, "video: the release is used up")

# ================================================================ polls
r = Bo.post(B + "/api/polls", json={"title": "Teamessen", "duration": 60, "tz": "Europe/Berlin", "options": TIMES, "space": SP})
check(r.status_code in (200, 201), "poll: setup, bob's poll in Alpha " + r.text[:200])
PL = (r.json().get("poll") or r.json()).get("id")
dry_refused(Bo.post(B + f"/api/polls/{PL}/move-space", json={"to": "private", "dry": 1}), "poll", PL, "poll")
refused(Bo.post(B + f"/api/polls/{PL}/move-space", json={"to": "private"}), "poll", PL, "poll: the maker without a release")
release(Bo, "poll", PL)
r = Bo.post(B + f"/api/polls/{PL}/move-space", json={"to": "private"})
check(r.ok and r.json().get("space") == "private", "poll: bob moves it private " + r.text[:200])
released_logged("poll", "poll")
r = Bo.post(B + f"/api/polls/{PL}/move-space", json={"to": SP, "dry": 1})
check(r.ok and any(BACK in n for n in r.json().get("notes", [])), "poll: the dry run into Alpha names the way back " + r.text[:300])
check(Bo.post(B + f"/api/polls/{PL}/move-space", json={"to": SP}).ok, "poll: into Alpha again")
check(Bo.post(B + f"/api/polls/{PL}/move-space", json={"to": "private"}).status_code == 403, "poll: the release is used up")

# ================================================================ bookmarks
r = Bo.post(B + "/api/bookmarks", json={"url": "https://example.com/artikel", "space": SP, "title": "Artikel"})
check(r.status_code in (200, 201), "bookmark: setup, bob's bookmark in Alpha " + r.text[:200])
BM = r.json()["bookmark"]["id"]
BMV = {"ids": [BM], "to": "private"}
dry_refused(Bo.post(B + "/api/bookmarks/move-space", json={**BMV, "dry": 1}), "bookmark", BM, "bookmark")
refused(Bo.post(B + "/api/bookmarks/move-space", json=BMV), "bookmark", BM, "bookmark: the maker without a release")
r = Ca.post(B + "/api/bookmarks/move-space", json=BMV)
check(r.status_code == 403 and not r.json().get("out_request"), "bookmark: another member 403 without out_request " + r.text[:200])
release(Bo, "bookmark", BM)
r = Bo.post(B + "/api/bookmarks/move-space", json=BMV)
check(r.ok and r.json().get("space") == "private", "bookmark: bob moves it private " + r.text[:200])
released_logged("bookmark", "bookmark")
r = Bo.post(B + "/api/bookmarks/move-space", json={"ids": [BM], "to": SP, "dry": 1})
check(r.ok and any(BACK in n for n in r.json().get("notes", [])), "bookmark: the dry run into Alpha names the way back " + r.text[:300])
check(Bo.post(B + "/api/bookmarks/move-space", json={"ids": [BM], "to": SP}).ok, "bookmark: into Alpha again")
check(Bo.post(B + "/api/bookmarks/move-space", json=BMV).status_code == 403, "bookmark: the release is used up")

# ================================================================ freelancer-matrix: wiki, polls, bookmarks
r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Eigene Seite", "body": "x"})
check(r.status_code == 201 and Fr.post(B + "/api/wiki/move-space", json={"pages": [r.json()["id"]], "space": "private", "to": SP}).status_code == 409,
      "freelancer: an own page, no other workspace (409)")
r = Fr.post(B + "/api/polls", json={"title": "Eigene Umfrage", "duration": 30, "tz": "Europe/Berlin", "options": TIMES})
FP = (r.json().get("poll") or r.json()).get("id")
check(r.status_code in (200, 201) and Fr.get(B + f"/api/polls/{FP}").ok, "freelancer: an own poll as before")
check(Fr.post(B + f"/api/polls/{FP}/move-space", json={"to": SP}).status_code == 409, "freelancer: the poll has no other workspace (409)")
r = Fr.post(B + "/api/bookmarks", json={"url": "https://example.com/eigen"})
check(r.status_code in (200, 201) and Fr.get(B + f"/api/bookmarks/{r.json()['bookmark']['id']}").ok, "freelancer: an own bookmark as before")
check(Fr.post(B + f"/api/orgs/{ORG}/out-requests", json={"kind": "wiki", "id": WP}).status_code == 404, "freelancer: no request in Alpha (404)")
check(sql("SELECT COUNT(*) FROM org_out_requests WHERE by_id=?", (FID,))[0][0] == 0, "freelancer: never a request")

print(f"p23612_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
