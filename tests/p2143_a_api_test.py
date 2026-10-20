#!/usr/bin/env python3
"""2.143.0 API tests, part A (#2151): organisation roles guest / read-only / accounting, own container (start.sh). Invented
names only, addresses @example.com. tenant-matrix: org (every check runs inside one organisation and its private spaces).
 - the roles are accepted when an admin adds / changes a member and when the server admin creates an account; unknown -> 400
 - the last admin cannot step down; GET /api/orgs carries the roles with their explanation
 - read-only: sees an organisation-wide list (role view in the state), changes nothing (task / new task / own share 403),
   office settings readable, no office change, no admin bookkeeping; pages readable (may_write false), not writable;
   an address book / calendar of the organisation only to read; no invitation, no member change; API v1 the same
 - guest: no organisation-wide list, no office, no pages, no open channel; a list shared with them personally works with
   its own role; no list / page in the organisation; the member list shows only the people they share something with
 - accounting: like a guest outside the office; the office and its bookkeeping readable, nothing writable; receipts upload
   into the organisation's documents (a guest / read-only person cannot)
 - review fixes: no folder / file at the organisation's top for limited roles (accounting removes its own receipt); no
   office move, no list copy into the organisation, no list ownership, no internal form, no group through the organisation
   for them; a guest's / accounting person's closed month stays theirs; travel people only the organisation's staff; an
   unknown stored role reads as guest
 - a person without organisation (freelancer-matrix: lists, office, wiki): unchanged, everything in the own space works
usage: p2143_a_api_test.py <datadir>      (a fresh container; P2143A_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
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
    r = s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
    assert r.ok, (user, r.text)
    return s


def state_lists(s):
    return {x["id"]: x for x in s.get(B + "/api/state").json()["lists"]}


def v1(token):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + token})
    return s


if not os.environ.get("P2143A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
# ================================================================ the roles are accepted (POST /api/users, PUT members)
for u, role in (("bob", "member"), ("gina", "guest"), ("rita", "readonly"), ("axel", "accounting")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"create {u} as {role}: " + r.text[:200])
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "boss"}], "username": "zed", "display_name": "Zed",
                                   "password": "password123", "email": "zed@example.com"})
check(r.status_code == 400, "an unknown role: 400 " + r.text[:200])
Bo, Gi, Ri, Ax = sess("bob"), sess("gina"), sess("rita"), sess("axel")
j = A.get(B + "/api/orgs").json()
o = next(x for x in j["orgs"] if x["id"] == ORG)
roles = {m["id"]: m["role"] for m in o["members"]}
check(roles.get(uid["gina"]) == "guest" and roles.get(uid["rita"]) == "readonly" and roles.get(uid["axel"]) == "accounting"
      and roles.get(uid["bob"]) == "member", f"the roles are stored: {roles}")
check([x["key"] for x in o.get("roles", [])] == ["member", "admin", "readonly", "accounting", "guest"]
      and all(x["hint"] for x in o["roles"]), "GET /api/orgs: the roles with their explanation")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "boss"}).status_code == 400, "PUT members: unknown role 400")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "readonly"}).ok, "PUT members: read-only accepted")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "member"}).ok, "PUT members: back to member")
r = A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": A.get(B + "/api/state").json()["me"]["id"], "role": "readonly"})
check(r.status_code == 409, "the last admin cannot step down " + r.text[:200])

# ================================================================ lists
L1 = A.post(B + "/api/lists", json={"name": "Team board", "org_id": ORG}).json()["id"]
check(A.patch(B + f"/api/lists/{L1}", json={"org_visibility": "org", "org_edit": 1}).ok, "setup: everyone in the organisation may edit")
T1 = A.post(B + "/api/tasks", json={"list_id": L1, "title": "Plan the spring"}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Guest project", "org_id": ORG}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"list_id": L2, "title": "Shared work"}).json()["id"]
for u in ("gina", "rita", "axel"):
    check(A.put(B + f"/api/lists/{L2}/members", json={"user_id": uid[u], "role": "edit"}).ok, f"share L2 with {u}")

check(state_lists(Bo).get(L1, {}).get("role") == "edit", "member: the organisation-wide list, role edit")
check(Bo.patch(B + f"/api/tasks/{T1}", json={"title": "Plan the spring!"}).ok, "member changes a task")
sl = state_lists(Ri)
check(sl.get(L1, {}).get("role") == "view" and sl.get(L2, {}).get("role") == "view", f"read-only: both lists as view {[(k, v.get('role')) for k, v in sl.items()]}")
check(Ri.get(B + f"/api/tasks/{T1}").ok, "read-only reads a task")
check(Ri.patch(B + f"/api/tasks/{T1}", json={"title": "x"}).status_code == 403, "read-only: no change of an organisation-wide task")
check(Ri.patch(B + f"/api/tasks/{T2}", json={"title": "x"}).status_code == 403, "read-only: no change even with a personal edit share")
check(Ri.post(B + "/api/tasks", json={"list_id": L2, "title": "x"}).status_code == 403, "read-only: no new task")
check(Ri.post(B + "/api/lists", json={"name": "Mine", "org_id": ORG}).status_code == 403, "read-only: no list in the organisation")
r = Ri.post(B + "/api/lists", json={"name": "Private notes", "org_id": None})
check(r.ok and Ri.patch(B + f"/api/lists/{r.json()['id']}", json={"name": "Private notes 2"}).ok, "read-only: the own private space works")

for nm, s in (("guest", Gi), ("accounting", Ax)):
    sl = state_lists(s)
    check(L1 not in sl, f"{nm}: no organisation-wide list")
    check(s.get(B + f"/api/tasks/{T1}").status_code == 404, f"{nm}: an organisation-wide task is 404")
    check(sl.get(L2, {}).get("role") == "edit", f"{nm}: the personally shared list with its role")
    check(s.patch(B + f"/api/tasks/{T2}", json={"title": "Shared work, done by " + nm}).ok, f"{nm}: changes in the shared list")
    check(s.post(B + "/api/lists", json={"name": "Mine", "org_id": ORG}).status_code == 403, f"{nm}: no list in the organisation")
    r = s.post(B + "/api/lists", json={"name": "Own " + nm})
    check(r.ok and not r.json().get("org_id"), f"{nm}: a new list without workspace is private " + r.text[:200])

# ================================================================ office (Büro)
r = A.post(B + "/api/office/services", json={"name_de": "Beratung", "daily_rate": 800})
check(r.status_code in (200, 201), "setup: the admin adds a service " + r.text[:200])
for nm, s, code in (("read-only", Ri, 200), ("accounting", Ax, 200), ("guest", Gi, 403)):
    r = s.get(B + "/api/office/settings")
    check(r.status_code == code, f"{nm}: office settings {code} (got {r.status_code} {r.text[:120]})")
check(Ri.get(B + "/api/office/settings").json().get("role") == "readonly", "read-only: the role in the office answer")
for nm, s in (("read-only", Ri), ("accounting", Ax), ("guest", Gi)):
    check(s.post(B + "/api/office/services", json={"name_de": "x", "daily_rate": 1}).status_code == 403, f"{nm}: no new service")
    check(s.post(B + "/api/office/docs", json={"project_title": "x"}).status_code == 403, f"{nm}: no new quotation / invoice")
check(Bo.post(B + "/api/office/docs", json={"project_title": "Spring campaign"}).status_code in (200, 201), "member: a new document as before")
check(Ax.get(B + "/api/office/books").ok, "accounting: reads the bookkeeping (an admin area)")
check(Ax.get(B + "/api/office/books/euer.csv").ok, "accounting: exports the income statement")
check(Ri.get(B + "/api/office/books").status_code == 403, "read-only: the bookkeeping stays the admins'")
check(Bo.get(B + "/api/office/books").status_code == 403, "member: the bookkeeping stays the admins' (unchanged)")

# receipts into the organisation's documents
for nm, s, ok in (("accounting", Ax, True), ("read-only", Ri, False), ("guest", Gi, False)):
    r = s.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files={"files": ("receipt.txt", b"Receipt 12.50 EUR", "text/plain")})
    check((r.status_code == 201) == ok and (ok or r.status_code in (403, 404)), f"{nm}: receipt upload {'ok' if ok else 'refused'} ({r.status_code} {r.text[:150]})")

# ================================================================ address books, calendars, pages, channels
OB = A.post(B + "/api/books", json={"name": "Alpha customers", "org_id": ORG}).json()["id"]
A.post(B + f"/api/books/{OB}/org", json={"org_role": "edit"})
bk = lambda s: {x["id"]: x["role"] for x in s.get(B + "/api/books").json()["items"]}  # noqa: E731
check(bk(Bo).get(OB) == "edit", "member: the organisation's address book, edit")
check(bk(Ri).get(OB) == "view", "read-only: the organisation's address book, view")
check(OB not in bk(Gi) and OB not in bk(Ax), "guest / accounting: no organisation address book")
check(Ri.post(B + "/api/contacts", json={"book_id": OB, "given": "Hanna", "family": "Probe"}).status_code in (403, 404), "read-only: no new contact")
check(Bo.post(B + "/api/contacts", json={"book_id": OB, "given": "Hanna", "family": "Probe"}).ok, "member: a new contact")

CAL = A.post(B + "/api/evcals", json={"name": "Studio", "org_id": ORG}).json()["id"]
A.put(B + f"/api/evcals/{CAL}/members", json={"user_id": uid["rita"], "role": "edit"})
A.put(B + f"/api/evcals/{CAL}/members", json={"user_id": uid["gina"], "role": "edit"})
cals = lambda s: {x["id"]: x["role"] for x in s.get(B + "/api/evcals").json()["items"]}  # noqa: E731
check(cals(Ri).get(CAL) == "view", f"read-only: a shared calendar of the organisation only to read {cals(Ri)}")
ev = {"cal_id": CAL, "title": "Kick-off", "start": "2026-11-02T10:00", "end": "2026-11-02T11:00", "tz": "Europe/Berlin"}
check(Ri.post(B + "/api/events", json=ev).status_code == 403, "read-only: no new event")
check(cals(Gi).get(CAL) == "edit" and Gi.post(B + "/api/events", json=ev).status_code in (200, 201), "guest: a calendar shared personally works")

r = A.post(B + "/api/wiki/pages", json={"space": f"org:{ORG}", "path": "Handbook", "body": "How we work"})
check(r.status_code in (200, 201), "setup: an organisation page " + r.text[:150])
w = Ri.get(B + "/api/wiki", params={"space": f"org:{ORG}"})
check(w.ok and w.json().get("may_write") is False and w.json()["pages"], "read-only: pages readable, may_write false")
check(Bo.get(B + "/api/wiki", params={"space": f"org:{ORG}"}).json().get("may_write") is True, "member: may_write true")
check(Ri.post(B + "/api/wiki/pages", json={"space": f"org:{ORG}", "path": "Mine", "body": "x"}).status_code == 403, "read-only: no new page")
for nm, s in (("guest", Gi), ("accounting", Ax)):
    check(s.get(B + "/api/wiki", params={"space": f"org:{ORG}"}).status_code == 404, f"{nm}: no pages of the organisation")
    check(s.post(B + "/api/wiki/pages", json={"space": f"org:{ORG}", "path": "Mine", "body": "x"}).status_code == 404, f"{nm}: no new page")

ch = A.post(B + "/api/team/channels", json={"name": "General", "org_id": ORG, "open": True})
CH = ch.json().get("id") if ch.ok else None
chans = lambda s: [x["id"] for x in s.get(B + "/api/team/channels").json().get("channels", [])]  # noqa: E731
check(CH and CH in chans(Ri), "read-only: sees the open channel (the team chat stays open)")
check(CH and CH not in chans(Gi), "guest: no open channel of the organisation")
check(Ri.post(B + "/api/team/channels", json={"name": "Mine", "org_id": ORG}).status_code == 403, "read-only: opens no channel")

# ================================================================ members, invitations
for nm, s in (("guest", Gi), ("read-only", Ri), ("accounting", Ax)):
    check(s.post(B + f"/api/orgs/{ORG}/invites", json={"email": f"new-{nm}@example.com"}).status_code == 403, f"{nm}: no invitation")
    check(s.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "admin"}).status_code == 403, f"{nm}: no member change")
og = next(x for x in Gi.get(B + "/api/orgs").json()["orgs"] if x["id"] == ORG)
seen = {m["id"] for m in og["members"]}
check(uid["gina"] in seen and uid["bob"] not in seen and og["lists"] == 0 and og.get("limited") is True,
      f"guest: the member list only with the people they share with ({seen})")
ob = next(x for x in Bo.get(B + "/api/orgs").json()["orgs"] if x["id"] == ORG)
check({uid["gina"], uid["rita"], uid["axel"]} <= {m["id"] for m in ob["members"]} and not ob.get("limited"), "member: sees everybody")

# ================================================================ API v1 (same rules)
tok = lambda s: s.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]  # noqa: E731
VR, VG = v1(tok(Ri)), v1(tok(Gi))
check(VR.get(B + f"/api/v1/tasks/{T1}").ok, "v1 read-only: reads the task")
check(VR.patch(B + f"/api/v1/tasks/{T1}", json={"title": "x"}).status_code == 403, "v1 read-only: no change")
check(VR.post(B + "/api/v1/tasks", json={"list_id": L2, "title": "x"}).status_code == 403, "v1 read-only: no new task")
check(VG.get(B + f"/api/v1/tasks/{T1}").status_code == 404, "v1 guest: an organisation-wide task is 404")
check(VG.get(B + f"/api/v1/tasks/{T2}").ok, "v1 guest: the shared list's task")

# ================================================================ review fixes (#2151, 2.143.0 A2)
# files: the organisation's top level only for members / admins; accounting removes its own receipt
for nm, s in (("guest", Gi), ("read-only", Ri), ("accounting", Ax)):
    check(s.post(B + "/api/files/folders", json={"name": "Top " + nm, "space": f"org:{ORG}"}).status_code in (403, 404), f"{nm}: no folder at the organisation's top")
    r = s.post(B + "/api/files/upload", data={"space": f"org:{ORG}"}, files={"file": ("note.txt", b"note", "text/plain")})
    check(r.status_code in (403, 404), f"{nm}: no file at the organisation's top ({r.status_code})")
    r = s.get(B + "/api/files", params={"space": f"org:{ORG}"})
    check(not r.ok or r.json().get("role") != "edit", f"{nm}: the top level is not offered as editable ({r.status_code} {r.text[:120]})")
check(Bo.post(B + "/api/files/folders", json={"name": "Team folder", "space": f"org:{ORG}"}).ok, "member: a folder at the organisation's top")
r = Ax.post(B + "/api/docs", data={"ws": f"org:{ORG}"}, files={"files": ("receipt2.txt", b"Receipt 7.10 EUR", "text/plain")})
rid = (r.json().get("ids") or [None])[0] if r.status_code == 201 else None
rd = Ax.delete(B + f"/api/files/nodes/{rid}") if rid else None
check(rd is not None and rd.ok, f"accounting: removes its own wrong receipt {r.text[:80]} -> {rd.status_code if rd is not None else '-'} {rd.text[:150] if rd is not None else ''}")

# office: moving clients / drafts out of the organisation needs a writing office role
cl = Bo.post(B + "/api/clients", json={"name": "Northwind Example GmbH", "org_id": ORG})
CL = cl.json().get("id") if cl.ok else None
check(CL, "setup: a client of the organisation " + cl.text[:150])
for nm, s in (("read-only", Ri), ("accounting", Ax)):
    r = s.post(B + "/api/office/move-space", json={"what": "clients", "ids": [CL], "to": "private", "dry": 1})
    check(r.status_code in (403, 404), f"{nm}: moves no client out of the organisation ({r.status_code} {r.text[:120]})")
r = Gi.post(B + "/api/office/move-space", json={"what": "clients", "ids": [CL], "to": "private", "dry": 1})
check(r.status_code in (403, 404), f"guest: no office move ({r.status_code})")

# a copied list stays in the organisation only for writing roles
for nm, s in (("guest", Gi), ("read-only", Ri), ("accounting", Ax)):
    r = s.post(B + f"/api/lists/{L2}/duplicate", json={"name": "Copy " + nm})
    if r.ok:
        nl = state_lists(s).get(r.json()["list_id"], {})
        check(nl.get("org_id") != ORG, f"{nm}: the copy is not in the organisation ({nl.get('org_id')})")
    else:
        check(r.status_code in (403, 404), f"{nm}: copy refused or private ({r.status_code} {r.text[:120]})")
r = Bo.post(B + f"/api/lists/{L1}/duplicate", json={"name": "Copy member"})
check(r.ok and state_lists(Bo).get(r.json()["list_id"], {}).get("org_id") == ORG, "member: the copy stays in the organisation " + r.text[:120])

# list ownership: only to a member / admin of the organisation
cands = {x["id"] for x in A.get(B + f"/api/lists/{L2}/owner").json().get("candidates", [])}
check(uid["bob"] in cands and not cands & {uid["gina"], uid["rita"], uid["axel"]}, f"owner candidates without limited roles {cands}")
for u in ("gina", "rita", "axel"):
    check(A.post(B + f"/api/lists/{L2}/owner", json={"user_id": uid[u]}).status_code == 409, f"no list ownership for {u}")

# an organisation's internal form: not for guests / read-only / accounting
fr = A.post(B + f"/api/lists/{L1}/forms", json={"title": "Requests", "access": "org"})
FT = fr.json().get("url", "").rsplit("/f/", 1)[-1] if fr.status_code == 201 else ""
check(FT, "setup: an internal form " + fr.text[:150])
check(Bo.get(B + f"/f/{FT}").status_code == 200, "member: opens the internal form")
for nm, s in (("guest", Gi), ("read-only", Ri), ("accounting", Ax)):
    check(s.get(B + f"/f/{FT}").status_code == 404, f"{nm}: the internal form is not available")

# groups: not visible through an organisation where one is a guest / accounting
gr = A.post(B + "/api/admin/groups", json={"name": "Studio crew", "members": [uid["bob"]]})
GID = gr.json().get("id") if gr.ok else None
check(GID, "setup: a group " + gr.text[:150])
gids = lambda s: {x["id"] for x in s.get(B + "/api/groups").json().get("groups", [])}  # noqa: E731
check(GID in gids(Ri), "read-only: sees the group of organisation people")
check(GID not in gids(Gi) and GID not in gids(Ax), "guest / accounting: no group through the organisation")

# timesheets: a guest's / accounting person's closed month stays theirs (no approval by the organisation)
import datetime as _dt  # noqa: E402
PM = (_dt.date.today().replace(day=1) - _dt.timedelta(days=1)).strftime("%Y-%m")
for nm, s in (("guest", Gi), ("accounting", Ax)):
    r = s.post(B + "/api/time/sheets", json={"month": PM, "action": "close"})
    check(r.ok and not r.json()["sheet"].get("org_id"), f"{nm}: the closed month has no organisation " + r.text[:200])
r = Bo.post(B + "/api/time/sheets", json={"month": PM, "action": "close"})
check(r.ok and r.json()["sheet"].get("org_id") == ORG, "member: the closed month goes to the organisation " + r.text[:200])

# an unknown stored role (a newer version's, a hand edit) reads as guest, not as member
import dbx  # noqa: E402
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "uma", "display_name": "Uma",
                                   "password": "password123", "email": "uma@example.com"})
check(r.ok, "setup: uma " + r.text[:150])
uid["uma"] = r.json().get("id")
dbx.connect(DATA).execute("UPDATE org_members SET role=? WHERE org_id=? AND user_id=?", ("boss", ORG, uid["uma"]))
Um = sess("uma")
check(L1 not in state_lists(Um), "unknown role: no organisation-wide list (guest)")
check(Um.post(B + "/api/tasks", json={"list_id": L1, "title": "x"}).status_code in (403, 404), "unknown role: no task in an organisation list")
check(Um.get(B + "/api/office/settings").status_code == 403, "unknown role: no office")
og = next(x for x in A.get(B + "/api/orgs").json()["orgs"] if x["id"] == ORG)
check({m["id"]: m["role"] for m in og["members"]}.get(uid["uma"]) == "guest", "unknown role: shown as guest to the admin")

# office people lists: no guests / accounting among the organisation's people
r = A.get(B + "/api/office/trips")
ppl = {p["id"] for p in r.json().get("people", [])} if r.ok else set()
check(r.ok and uid["bob"] in ppl and uid["rita"] in ppl and uid["gina"] not in ppl and uid["axel"] not in ppl,
      f"travel people: the staff only ({r.status_code} {ppl})")

# ================================================================ a person without organisation (P4)
# freelancer-matrix: lists
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Own work"}).json()
check(not FL.get("org_id") and Fr.post(B + "/api/tasks", json={"list_id": FL["id"], "title": "Cut"}).ok, "freelancer: own list + task")
# freelancer-matrix: office
check(Fr.post(B + "/api/office/services", json={"name_de": "Schnitt", "daily_rate": 400}).status_code in (200, 201), "freelancer: own office service")
check(Fr.get(B + "/api/office/books").ok, "freelancer: own bookkeeping (their own admin)")
# freelancer-matrix: wiki
check(Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Notes", "body": "x"}).status_code in (200, 201), "freelancer: own page")
check(next(x for x in A.get(B + "/api/orgs").json()["orgs"] if x["id"] == ORG)["roles"], "the admin's view still has the role list")

print(f"\np2143_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
