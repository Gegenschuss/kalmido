#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.364.0 A API: the first start of new accounts (own container, KALMIDO_ONBOARDING=1).
 - #3016: the first-run setup's start "Empty" creates no "Getting started" list (the sample project keeps it; a project of
   a type too, as before)
 - #3032: accounts an admin made (user admin, organisation invitation) get the short "What do you use Kalmido for?"
   (setting purpose_ask = the preselected purpose: the inviting admin's own, else "me"); the setting admin, kids and old
   accounts not; POST /api/me/purpose {only: true} switches exactly the purpose's package (a member of an organisation
   keeps collaboration) and answers the question; purpose_ask is server-only
 - #3037: an invited member of an organisation gets no "Getting started" list and no sample offer (sample_ask 0); the
   list comes on request (again: true, Settings > Help); an organisation admin and a person without organisation keep it
freelancer-matrix: onboarding (elena has no organisation and gets the list and "For me")
usage: p2364_a_onboard_test.py <datadir>"""
import sys

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

kt.fresh(env={"KALMIDO_ONBOARDING": "1"})
import requests  # noqa: E402

s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": kt.PASSWORD}).ok
A = sess("alice")


def st(s):
    return s.get(B + "/api/state").json()


def lists(s):
    return [l for l in st(s)["lists"] if not l.get("is_inbox")]


def onboard(s, **kw):
    return s.post(B + "/api/onboarding", json={"touch": False, "mac": False, **kw}).json()


# ================= #3016: "Empty" is empty
check(st(A)["settings"].get("onboard") == "pending", "setup admin: onboard pending before the setup")
check(st(A)["settings"].get("purpose_ask") == "done", "#3032: the setting-up admin gets the full setup, not the short question")
r = A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"], "sample": False, "examples": False})
check(r.ok, "admin setup with the start Empty " + r.text[:200])
check(st(A)["settings"].get("onboard") == "done", "#3016: start Empty -> onboard done")
check(onboard(A).get("created") is False and lists(A) == [], "#3016: start Empty -> no Getting started list " + str([l["name"] for l in lists(A)]))

# a second and a third admin: the sample project keeps the list; a project of a type too (unchanged)
for u in ("bob", "carol"):
    A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": kt.PASSWORD, "is_admin": True})
Bo, Ca = sess("bob"), sess("carol")
Bo.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal"], "sample": True, "examples": True})
check(st(Bo)["settings"].get("onboard") == "pending" and onboard(Bo).get("created") is True, "#3016: start Sample project -> Getting started list as before")
Ca.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal"], "sample": False, "project_type": "private"})
check(st(Ca)["settings"].get("onboard") == "pending", "#3016: start with a project of a type -> onboard unchanged (pending)")

# ================= #3032: the short question for accounts an admin made
check(A.post(B + "/api/me/purpose", json={"purpose": "team"}).ok, "alice uses Kalmido for Team")
r = A.post(B + "/api/admin/orgs", json={"name": "Acme"})
check(r.ok, "organisation Acme " + r.text[:200])
OID = next(o["id"] for o in st(A)["me"]["workspaces"] if o["name"] == "Acme")
r = A.post(B + "/api/users", json={"username": "tom", "display_name": "Tom", "password": kt.PASSWORD, "email": "tom@example.com", "orgs": [OID]})
check(r.ok, "tom: a member of Acme " + r.text[:200])
To = sess("tom")
check(st(To)["settings"].get("purpose_ask") == "team", "#3032: a member made by the admin: question pending, preselected with the admin's purpose: " + str(st(To)["settings"].get("purpose_ask")))
r = A.post(B + "/api/orgs/%d/invites" % OID, json={"email": "clara@example.com", "name": "Clara"})
check(r.ok and r.json().get("user_id"), "clara invited into Acme " + r.text[:200])
CID = r.json().get("user_id")
row = kt.dbx("SELECT value FROM user_settings WHERE user_id=? AND key='purpose_ask'", (CID,))
check(row and row[0][0] == "team", "#3032: an invited account: question pending, preselected with the inviting admin's purpose " + str(row))
r = A.post(B + "/api/users", json={"username": "kim", "display_name": "Kim", "password": kt.PASSWORD, "kid": True})
row = kt.dbx("SELECT value FROM user_settings WHERE user_id=? AND key='purpose_ask'", (r.json().get("id"),))
check(r.ok and (not row or row[0][0] == "done"), "#3032: a kid account gets no question " + str(row))
check(st(Bo)["settings"].get("purpose_ask") == "me", "#3032: an account the admin made without organisation: preselected For me")
To.patch(B + "/api/settings", json={"purpose_ask": "done"})
check(st(To)["settings"].get("purpose_ask") == "team", "#3032: purpose_ask is server-only (the client cannot answer it by PATCH)")

# P4: elena without organisation: the question with "For me"; the answer switches exactly calendar, events, contacts
EID, El = freelancer(B, A, "elena")
check(st(El)["settings"].get("purpose_ask") == "me", "#3032 P4: without organisation the question is preselected with For me")
r = El.post(B + "/api/me/purpose", json={"purpose": "me", "only": True})
fs = set(st(El)["settings"]["features"].split(","))
check(r.ok and fs == {"cal", "events", "contacts"}, "#3032 P4: For me = exactly calendar, events, contacts, nothing else: " + ",".join(sorted(fs)))
check(st(El)["settings"].get("purpose_ask") == "done" and st(El)["settings"].get("purpose") == "me", "#3032: answered -> done")
r = To.post(B + "/api/me/purpose", json={"purpose": "me", "only": True})
fs = set(st(To)["settings"]["features"].split(","))
check(r.ok and fs == {"cal", "events", "contacts", "collab"}, "#3032: a member of an organisation keeps collaboration with For me: " + ",".join(sorted(fs)))

# ================= #3037: invited members start without the practice project
j = onboard(To)
s = st(To)["settings"]
check(j.get("created") is False and s.get("onboard") == "done" and s.get("sample_ask") == "0", "#3037: member of Acme: no Getting started list, no sample offer " + str(j))
check(not [l for l in lists(To) if l["owner_id"] == st(To)["me"]["id"]], "#3037: tom owns no list after the first start")
j = onboard(To, again=True)
check(j.get("created") is True and any(l["id"] == j.get("list_id") for l in lists(To)), "#3037: Settings > Help creates the list on request " + str(j))
El.patch(B + "/api/settings", json={"tour": "done"})
kt.dbx("UPDATE user_settings SET value='pending' WHERE user_id=? AND key='onboard'", (EID,))
check(onboard(El).get("created") is True, "#3037 P4: without organisation the Getting started list comes as before")
r = A.post(B + "/api/users", json={"username": "dora", "display_name": "Dora", "password": kt.PASSWORD, "orgs": [{"id": OID, "role": "admin"}]})
Do = sess("dora")
check(r.ok and onboard(Do).get("created") is True, "#3037: an organisation admin keeps the list")

sys.exit(kt.done("p2364_a_onboard"))
