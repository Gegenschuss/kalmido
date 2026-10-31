#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.360.2 M (#2561): the boundary between organisations: no account oracle in sharing a table or in the open invitations.
Invented names only.
 - a table shared by address: a row with or without an account, the same answer, list, count and limit; the address sealed;
   a person outside the table's organisation gets nothing; the account made later takes the row at sign-in
 - a person picked by name beside an address row, leaving the organisation, removing an address row
 - 2.453.0 (#3781): a deleted account leaves the address row open
 - 2.453.0 (#3780): a new address joins by accepting like an existing account: the member list is the same in both cases
 - open invitations: new account and existing account in one form (ref instead of ids); resend, withdraw, another
   organisation's ref; expired ones; with invitations switched off they stay visible and can be ended
usage: p23602_m_api_test.py <datadir>"""
# freelancer-matrix: sheets
import hashlib
import sys

import kt
from kt import B, check, dbx, sess
from freelancer_fixture import FEATURES, freelancer

kt.fresh(prefix="P23602M")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
uid = {}
for u, orgs in (("bob", [ORG]), ("carol", [ORG]), ("dora", [ORG]), ("erin", [])):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": u, "display_name": u.title() + " Name", "password": "password123",
                                       "email": f"{u}@example.com", "features": "sheets,collab,comments"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "admin"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["erin"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ca, Do, Er = sess("bob"), sess("carol"), sess("dora"), sess("erin")
for s in (Bo, Ca, Do, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "sheets,collab,comments", "tour": "done"})


def new(s, title, **kw):
    r = s.post(B + "/api/sheets", json={"title": title, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def post(s, sid, **kw):
    return s.post(B + f"/api/sheets/{sid}/shares", json=kw)


def rows(s, sid):
    return s.get(B + f"/api/sheets/{sid}/shares").json()["shares"]


# ================================================================ a table shared by address
S1 = new(Bo, "Rates", space="private")
r1, r2 = post(Bo, S1, email="carol@example.com"), post(Bo, S1, email="ghost@example.com")
check(r1.status_code == r2.status_code == 201 and set(r1.json()) == set(r2.json()), "account or not: the same answer " + r2.text[:200])
ls = rows(Bo, S1)
check(len(ls) == 2 and {x["state"] for x in ls} == {"invited"} and all(x["user_id"] is None and x["agent"] is False for x in ls),
      f"both rows the same way: {ls}")
check({x["name"] for x in ls} == {x["email"] for x in ls} == {"carol@example.com", "ghost@example.com"}, "the address, never a name")
check(set(ls[0]) == set(ls[1]), "the same fields")
check(Bo.get(B + f"/api/sheets/{S1}").json().get("shared") == 2, "the count takes both")
db = dbx("SELECT user_id, email_seal, email_key FROM sheet_shares WHERE sheet_id=? ORDER BY id", (S1,))
check(db[0][0] == uid["carol"] and db[1][0] is None, f"the account is bound behind the scenes, the other row stays open {db}")
check(all("example.com" not in x[1] and x[1] and x[2] for x in db), "the address is sealed")
check(Ca.get(B + f"/api/sheets/{S1}").ok, "the account reads the table at once (as before)")
check(post(Bo, S1, email="no address").status_code == 400, "an invalid address: 400 for everybody")
n = len(rows(Bo, S1))
post(Bo, S1, email="GHOST@example.com ", role="write")
ls = rows(Bo, S1)
check(len(ls) == n and {x["email"]: x["role"] for x in ls}["ghost@example.com"] == "write", "the same address again: its role, no second row")

# outside the organisation: a row like any other, nothing to read
S0 = new(Bo, "Org table", space=f"org:{ORG}")
post(Bo, S0, email="erin@example.com")
check(len(rows(Bo, S0)) == 1 and not dbx("SELECT 1 FROM sheet_shares WHERE sheet_id=? AND user_id=?", (S0, uid["erin"])), "a stranger: an open row")
check(Er.get(B + f"/api/sheets/{S0}").status_code == 404, "... and no access")
sess("erin")
check(not dbx("SELECT 1 FROM sheet_shares WHERE sheet_id=? AND user_id=?", (S0, uid["erin"])), "... a sign-in does not take a row that does not fit")

# the limit counts both the same
S2 = new(Bo, "Full", space=f"org:{ORG}")
for i in range(200):
    dbx("INSERT INTO sheet_shares(sheet_id,org_id,role,created_at,email_seal,email_key) VALUES(?,?,'read','2026-01-01T00:00:00+00:00','x',?)", (S2, ORG, f"k{i}"))
dbx("DELETE FROM sheet_shares WHERE sheet_id=? AND email_key='k0'", (S2,))
check(post(Bo, S2, email="room@example.com").status_code == 201, "room for one more")
r1, r2 = post(Bo, S2, email="dora@example.com"), post(Bo, S2, email="ghost2@example.com")
check(r1.status_code == r2.status_code == 409 and r1.text == r2.text, f"at the limit: the same refusal {r1.status_code} {r2.status_code}")
dbx("DELETE FROM sheet_shares WHERE sheet_id=?", (S2,))

# the account of the address appears later: the row is taken at sign-in, it reads the same
S3 = new(Bo, "Later", space="private")
post(Bo, S3, email="late@example.com", role="write")
before = rows(Bo, S3)
r = A.post(B + "/api/users", json={"orgs": [], "username": "late", "display_name": "Late Person", "password": "password123", "email": "Late@Example.com"})
assert r.ok, r.text
uid["late"] = r.json()["id"]
check(not dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=?", (S3,))[0][0], "an account alone takes nothing yet")
La = sess("late")
La.patch(B + "/api/settings", json={"lang": "en", "features": "sheets,collab,comments", "tour": "done"})
check(not dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=?", (S3,))[0][0], "review: a sign-in with an address nobody proved takes nothing")
dbx("UPDATE users SET email_proved='other@example.com' WHERE id=?", (uid["late"],))
La = sess("late")
check(not dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=?", (S3,))[0][0], "review: ... nor with another address proved before")
dbx("UPDATE users SET email_proved='late@example.com' WHERE id=?", (uid["late"],))  # (a mail link or a verified OIDC claim)
La = sess("late")
check(dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=?", (S3,))[0][0] == uid["late"], "the sign-in with the proved address takes the row")
check(La.get(B + f"/api/sheets/{S3}").ok, "the person reads the table")
check(La.put(B + f"/api/sheets/{S3}/cells", json={"cells": [{"cell": "A1", "raw": "1"}]}).ok, "... with the role of the invitation")
check(rows(Bo, S3) == before, "the row reads as before: nothing tells the account exists now")

# picked by name beside an address row: its own row, the address row stays
S4 = new(Bo, "Both", space="private")
post(Bo, S4, email="dora@example.com", role="write")
r = post(Bo, S4, user_id=uid["dora"], role="read")
ls = rows(Bo, S4)
check(r.status_code == 201 and len(ls) == 2 and {x["state"] for x in ls} == {"invited", "active"}, f"two rows: the address stays open {ls}")
check(Do.get(B + f"/api/sheets/{S4}").ok, "the person keeps the table")
S5 = new(Bo, "Named first", space="private")
post(Bo, S5, user_id=uid["dora"], role="read")
post(Bo, S5, email="dora@example.com", role="write")
ls = rows(Bo, S5)
check(len(ls) == 2 and {x["role"] for x in ls} == {"read", "write"}, f"the other way round: two rows as well {ls}")

# leaving the organisation: the address row stays listed
S6 = new(Bo, "Leaver", space=f"org:{ORG}")
post(Bo, S6, email="dora@example.com")
n = rows(Bo, S6)
r = Bo.delete(B + f"/api/orgs/{ORG}/members/{uid['dora']}")
check(r.ok, "dora leaves " + r.text[:200])
check(rows(Bo, S6) == n and dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=?", (S6,))[0][0] is None, "the row stays, open again")
check(Do.get(B + f"/api/sheets/{S6}").status_code == 404, "... without access")

# 2.453.0 (#3781): a deleted account: the address row stays open, nothing tells the address had an account
gone = A.post(B + "/api/users", json={"orgs": [], "username": "gone", "display_name": "Gone Name", "password": "password123",
                                      "email": "gone@example.com", "features": "sheets,collab,comments"}).json()["id"]
S7 = new(Bo, "Deleted", space="private")
post(Bo, S7, email="gone@example.com", role="write")
n = rows(Bo, S7)
check(dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=?", (S7,))[0][0] == gone, "the address row is bound to the account")
r = A.delete(B + f"/api/users/{gone}")
check(r.ok, "the account is deleted " + r.text[:200])
check(rows(Bo, S7) == n, f"the address row reads as before {rows(Bo, S7)}")
check([x[0] for x in dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=?", (S7,))] == [None], "... open again, without an account behind it")

# removing an address row: the address is gone, Undo = the address again
x = [v for v in rows(Bo, S1) if v["email"] == "carol@example.com"][0]
check(Bo.delete(B + f"/api/sheets/{S1}/shares/{x['id']}").ok, "stop sharing by address")
check(not dbx("SELECT 1 FROM sheet_shares WHERE id=?", (x["id"],)), "the row with the address is deleted")
check(Ca.get(B + f"/api/sheets/{S1}").status_code == 404, "the access ends at once")
check(post(Bo, S1, email="carol@example.com").status_code == 201 and Ca.get(B + f"/api/sheets/{S1}").ok, "Undo: the address again")
check(Bo.get(B + f"/api/sheets/{S1}/shares").ok and Ca.get(B + f"/api/sheets/{S1}/shares").status_code == 403, "a recipient never manages shares")

# a person without an organisation
FID, Fl = freelancer(B, A, features=FEATURES + ",sheets")
GID, Gl = freelancer(B, A, "fiona", features=FEATURES + ",sheets")
FS = new(Fl, "Freelance rates")
r1, r2 = post(Fl, FS, email="fiona@example.com"), post(Fl, FS, email="nobody@example.com")
ls = rows(Fl, FS)
check(r1.status_code == r2.status_code == 201 and len(ls) == 2 and {x["state"] for x in ls} == {"invited"}, f"freelancer: the same rows {ls}")
check(Gl.get(B + f"/api/sheets/{FS}").ok, "freelancer: the other one reads it")
post(Fl, FS, email="frida@example.com")
check(not dbx("SELECT 1 FROM sheet_shares WHERE sheet_id=? AND user_id=?", (FS, FID)), "the owner's own address: an open row, no share with oneself")
sess("frida")
check(not dbx("SELECT 1 FROM sheet_shares WHERE sheet_id=? AND user_id=?", (FS, FID)), "... also after a sign-in")

# ================================================================ open invitations
inv = lambda s=Bo, o=ORG: s.get(B + f"/api/orgs/{o}/invites").json()
Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "newby@example.com", "name": "Newby Person", "role": "admin"})
Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "erin@example.com", "role": "admin"})
iv = {x["email"]: x for x in inv()["invites"]}
n, e = iv.get("newby@example.com"), iv.get("erin@example.com")
check(n and e and set(n) == set(e) and n["user_id"] is None and e["user_id"] is None, f"one form for both kinds {iv}")
check(n["name"] == "newby@example.com" and e["name"] == "erin@example.com" and "join_id" not in e, "the address, no name, no id")
check(inv()["invites"][0]["ref"] != inv()["invites"][0]["ref"], "opaque references, new on every read")
a_iv = {x["email"]: x for x in inv(A)["invites"]}
check(isinstance(a_iv["newby@example.com"]["user_id"], int) and a_iv["erin@example.com"]["user_id"] is None, "an instance admin keeps the id of a new account")

r = Bo.post(B + f"/api/orgs/{ORG}/invites/{e['ref']}/resend")
check(r.ok and r.json()["invitation"].get("sent") is True, "resend works for an existing account " + r.text[:200])
check(Ca.post(B + f"/api/orgs/{ORG}/invites/{e['ref']}/resend").status_code == 403, "a plain member cannot resend")
check(Er.delete(B + f"/api/orgs/{ORG}/invites/{e['ref']}").status_code == 404, "another organisation's admin: 404")
BETA_REF = e["ref"]
check(Er.delete(B + f"/api/orgs/{BETA}/invites/{BETA_REF}").status_code == 404, "a reference of another organisation: 404")
check(Bo.delete(B + f"/api/orgs/{ORG}/invites/v1.AAAA").status_code == 404, "a made-up reference: 404")
check(Ca.delete(B + f"/api/orgs/{ORG}/invites/{e['ref']}").status_code == 403, "a plain member cannot withdraw")
check(any(o.get("org_id") == ORG for o in Er.get(B + "/api/orgs").json().get("joins", [])), "the person still has the invitation")
r = Bo.delete(B + f"/api/orgs/{ORG}/invites/{e['ref']}")
check(r.ok and r.json().get("email") == "erin@example.com" and r.json().get("role") == "admin", "withdrawn, with the data for the undo " + r.text[:200])
check("erin@example.com" not in {x["email"] for x in r.json()["invites"]}, "gone from the list")
check(Er.post(B + f"/api/orgs/{ORG}/join").status_code == 404, "the person can no longer accept")
check(dbx("SELECT 1 FROM users WHERE id=?", (uid["erin"],)), "the account stays")
check(Bo.delete(B + f"/api/orgs/{ORG}/invites/{e['ref']}").status_code == 404, "withdrawing twice: 404")

r = Bo.delete(B + f"/api/orgs/{ORG}/invites/{n['ref']}")
check(r.ok and not dbx("SELECT 1 FROM users WHERE lower(email)='newby@example.com'"), "a new account's invitation: withdrawn by its reference, the account goes")

# ---- 2.453.0 (#3780): the member list tells nothing: a new address and an existing account both join by accepting
def roster():
    return sorted(x[0] for x in dbx("SELECT user_id FROM org_members WHERE org_id=?", (ORG,)))


def members_seen():
    return next(o for o in Bo.get(B + "/api/orgs").json()["orgs"] if o["id"] == ORG)["members"]


def in_org(mail):
    return dbx("SELECT 1 FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND lower(u.email)=?", (ORG, mail))


def link_of(mail):  # the link goes by mail only: a known token instead (only the hash is stored)
    tok = hashlib.sha256(mail.encode()).hexdigest()[:40]
    dbx("UPDATE user_invites SET token_hash=? WHERE user_id=(SELECT id FROM users WHERE lower(email)=?)", (hashlib.sha256(tok.encode()).hexdigest(), mail))
    return tok


before, seen = roster(), members_seen()
ra = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "fresh@example.com", "role": "readonly"})
check(ra.ok and roster() == before and members_seen() == seen, "a new address: no row in the member list " + ra.text[:200])
rb = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "erin@example.com", "role": "readonly"})
check(rb.ok and roster() == before and members_seen() == seen, "an existing account: no row either")
check(set(ra.json()) == set(rb.json()), "the same answer")
iv = {x["email"]: x for x in inv()["invites"]}
f, e = iv.get("fresh@example.com"), iv.get("erin@example.com")
check(len(inv()["invites"]) == 2 and {k: v for k, v in f.items() if k not in ("ref", "email", "name", "created_at")} == {k: v for k, v in e.items() if k not in ("ref", "email", "name", "created_at")},
      f"one row each, the same values {iv}")
dbx("UPDATE org_joins SET created_at='2020-01-01T00:00:00+00:00' WHERE org_id=?", (ORG,))
dbx("UPDATE user_invites SET expires_at='2020-01-15T00:00:00+00:00' WHERE user_id=(SELECT id FROM users WHERE email='fresh@example.com')")
st = {x["email"]: x["state"] for x in inv()["invites"]}
check(st == {"fresh@example.com": "expired", "erin@example.com": "expired"}, f"both run out alike {st}")
r = Bo.post(B + f"/api/orgs/{ORG}/invites/{next(x['ref'] for x in inv()['invites'] if x['email'] == 'fresh@example.com')}/resend")
iv = {x["email"]: x for x in inv()["invites"]}
check(r.ok and iv["fresh@example.com"]["state"] == "invited", "Resend renews the invitation with the link " + r.text[:200])
re_u = r.json()["invitation"]
r = Bo.post(B + f"/api/orgs/{ORG}/invites/{iv['erin@example.com']['ref']}/resend")
check(set(re_u) == set(r.json()["invitation"]) == {"sent", "email"}, f"review: resend answers the same for both kinds {re_u} {r.text[:200]}")
dbx("UPDATE org_joins SET created_at='2020-01-01T00:00:00+00:00' WHERE org_id=? AND user_id=(SELECT id FROM users WHERE email='erin@example.com')", (ORG,))
tok = link_of("fresh@example.com")
Fr = sess()
chk = Fr.post(B + "/api/auth/invite/check", json={"token": tok}).json()
check(chk.get("org_name") == "Alpha", f"the invitation page names the organisation {chk}")
dbx("UPDATE org_joins SET created_at='2020-01-01T00:00:00+00:00' WHERE org_id=? AND user_id=(SELECT id FROM users WHERE email='fresh@example.com')", (ORG,))
r = Fr.post(B + "/api/auth/invite/accept", json={"token": tok, "password": "password123"})
check(r.ok, "the password is set " + r.text[:200])
Fr.post(B + "/api/me/purpose", json={"purpose": "me", "only": True})
check("collab" in Fr.get(B + "/api/state").json()["settings"]["features"].split(","), "the first start keeps collaboration for the organisation ahead")
check(Fr.post(B + f"/api/orgs/{ORG}/join").ok and in_org("fresh@example.com"), "the link used on the last day: the time to accept starts again, accepted = a member")
check(dbx("SELECT role FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND u.email='fresh@example.com'", (ORG,)) == [("readonly",)], "in the invited role")
check(Er.post(B + f"/api/orgs/{ORG}/join").status_code == 404, "a used link says nothing for somebody else's expired invitation")
Bo.delete(B + f"/api/orgs/{ORG}/invites/{inv()['invites'][0]['ref']}")
# review: a reset names no organisation the person never joined; an older link does not bring an expired invitation back
Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "stale@example.com"})
St = sess()
check(St.post(B + "/api/auth/invite/accept", json={"token": link_of("stale@example.com"), "password": "password123"}).ok, "the stale person sets a password")
dbx("UPDATE user_invites SET kind='reset', used_at=NULL, expires_at='2099-01-01T00:00:00+00:00' WHERE user_id=(SELECT id FROM users WHERE email='stale@example.com')")
chk = sess().post(B + "/api/auth/invite/check", json={"token": link_of("stale@example.com")}).json()
check(chk.get("kind") == "reset" and not chk.get("org_name"), f"review: a reset link names no organisation {chk}")
dbx("UPDATE user_invites SET kind='invite', used_at=?, created_at='2020-01-02T00:00:00+00:00' WHERE user_id=(SELECT id FROM users WHERE email='stale@example.com')", (kt.now().isoformat(),))
dbx("UPDATE org_joins SET created_at='2020-03-01T00:00:00+00:00' WHERE org_id=? AND user_id=(SELECT id FROM users WHERE email='stale@example.com')", (ORG,))
check(St.post(B + f"/api/orgs/{ORG}/join").status_code == 404, "review: a link older than the invitation keeps it expired")
Bo.delete(B + f"/api/orgs/{ORG}/invites/{next(x['ref'] for x in inv()['invites'] if x['email'] == 'stale@example.com')}")
# declined: nothing is left that the boundary check would count once the person is in another organisation
Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "other@example.com"})
tok = link_of("other@example.com")
Ot = sess()
check(Ot.post(B + "/api/auth/invite/accept", json={"token": tok, "password": "password123"}).ok, "another new person sets a password")
check(Ot.delete(B + f"/api/orgs/{ORG}/join").ok and not dbx("SELECT 1 FROM org_invites i JOIN users u ON u.id=i.user_id WHERE u.email='other@example.com'"), "declined: the invitation is gone")
check(dbx("SELECT 1 FROM users WHERE email='other@example.com'"), "the person keeps the own account")
check(not in_org("other@example.com"), "and joined nothing")
# an instance admin still adds directly, the row of such an account is the old one
r = A.post(B + f"/api/orgs/{ORG}/invites", json={"email": "direct@example.com", "role": "member"})
check(r.ok and in_org("direct@example.com") and not dbx("SELECT 1 FROM org_joins WHERE org_id=?", (ORG,)), "the instance admin: a member at once " + r.text[:200])
r = Bo.delete(B + f"/api/orgs/{ORG}/invites/{next(x['ref'] for x in inv()['invites'] if x['email'] == 'direct@example.com')}")
check(r.ok and not dbx("SELECT 1 FROM users WHERE email='direct@example.com'"), "withdrawn as ever")
# withdrawing a new account with invitations switched off: the account goes with the invitation
Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "offnew@example.com", "role": "admin"})
# 2.458.0 (#3843): another organisation's open invitation lies on the never used account: it stays, only this invitation ends
Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "twice@example.com", "role": "member"})
twice = dbx("SELECT id FROM users WHERE email='twice@example.com'")[0][0]
r = Er.post(B + f"/api/orgs/{BETA}/invites", json={"email": "twice@example.com", "role": "member"})
check(r.ok and dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (BETA, twice)), "#3843: the second organisation invites the same address " + r.text[:200])
ref = {x["email"]: x for x in inv()["invites"]}["twice@example.com"]["ref"]
r = Bo.delete(B + f"/api/orgs/{ORG}/invites/{ref}")
check(r.ok and r.json().get("email") == "twice@example.com" and r.json().get("role") == "member", "#3843: withdrawn, the same answer for the undo " + r.text[:200])
check(dbx("SELECT 1 FROM users WHERE id=?", (twice,)), "#3843: the account stays")
check(dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (BETA, twice)), "#3843: the other organisation's invitation stays")
check(not dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (ORG, twice)) and not dbx("SELECT 1 FROM org_invites WHERE org_id=? AND user_id=?", (ORG, twice)), "#3843: only this invitation ends")
check(not dbx("SELECT 1 FROM user_invites WHERE user_id=?", (twice,)), "#3843: the link of this invitation ends with it")
check("twice@example.com" not in {x["email"] for x in inv()["invites"]} and "twice@example.com" in {x["email"] for x in inv(Er, BETA)["invites"]}, "#3843: gone here, open there")
# ... an expired one does not keep the account alive
Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "thrice@example.com", "role": "member"})
Er.post(B + f"/api/orgs/{BETA}/invites", json={"email": "thrice@example.com", "role": "member"})
thrice = dbx("SELECT id FROM users WHERE email='thrice@example.com'")[0][0]
dbx("UPDATE org_joins SET created_at='2020-01-01T00:00:00+00:00' WHERE org_id=? AND user_id=?", (BETA, thrice))
ref = {x["email"]: x for x in inv()["invites"]}["thrice@example.com"]["ref"]
check(Bo.delete(B + f"/api/orgs/{ORG}/invites/{ref}").ok and not dbx("SELECT 1 FROM users WHERE id=?", (thrice,)), "#3843: only an expired invitation elsewhere: the account goes")

A.patch(B + "/api/admin/settings", json={"org_invites": False})
iv = inv()["invites"]
check([x["email"] for x in iv] == ["offnew@example.com"], f"off: a new account's open invitation stays visible {iv}")
check(Bo.delete(B + f"/api/orgs/{ORG}/invites/{iv[0]['ref']}").ok and not dbx("SELECT 1 FROM users WHERE email='offnew@example.com'"), "off: withdrawn, the account goes")
A.patch(B + "/api/admin/settings", json={"org_invites": True})

# expired: listed as expired, withdrawing works
Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "erin@example.com"})
dbx("UPDATE org_joins SET created_at='2020-01-01T00:00:00+00:00' WHERE org_id=?", (ORG,))
iv = {x["email"]: x for x in inv()["invites"]}
check(iv["erin@example.com"]["state"] == "expired", f"an expired invitation is shown as expired {iv}")
check(Er.post(B + f"/api/orgs/{ORG}/join").status_code == 404, "... and cannot be accepted")

# switched off: what is open stays visible, and can end
dbx("UPDATE org_joins SET created_at=? WHERE org_id=?", (kt.now().isoformat(), ORG))
check(A.patch(B + "/api/admin/settings", json={"org_invites": False}).ok, "invitations off")
j = inv()
check(j["enabled"] is False and [x["email"] for x in j["invites"]] == ["erin@example.com"], f"off: the open invitation stays visible {j}")
ref = j["invites"][0]["ref"]
check(Bo.post(B + f"/api/orgs/{ORG}/invites/{ref}/resend").status_code == 403, "off: no resend")
check(Bo.delete(B + f"/api/orgs/{ORG}/invites/{ref}").ok and inv()["invites"] == [], "off: it can be withdrawn")
A.patch(B + "/api/admin/settings", json={"org_invites": True})

sys.exit(kt.done("p23602_m_api"))
