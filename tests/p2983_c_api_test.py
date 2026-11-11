#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.983.0 part C (job/4103). Invented people and titles only, everyone a person without an organisation.
freelancer-matrix: sheets, wiki
 - #5643 (Fable 2.937 F9): a table / a wiki page shared by e-mail address goes to an account only when that account proved
   the address (users.email_proved); an address an admin typed in that nobody proved gets nothing (a table: the address row
   stays open and is taken at the next sign-in after the proof, shs_redeem; the wiki: answered like an unknown address);
   PATCH /api/me does not set an address at all
usage: p2983_c_api_test.py <datadir>      (KMT_NOSTART=1 / P2983C_NOSTART=1: a running server)"""
import sys

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, sess, setup

fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="P2983C")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FEAT = "sheets,wiki,files,cal,comments,collab"
V = B + "/api/v1"


def table(s, title):
    r = s.post(B + "/api/sheets", json={"title": title, "space": "private"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def reads(s, sid):
    return s.get(B + f"/api/sheets/{sid}").status_code == 200


def page(s, path, text):
    r = s.post(B + "/api/wiki/pages", json={"space": "private", "path": path, "body": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def wiki_shared(s):
    return {x["path"] for x in s.get(B + "/api/wiki/shared").json().get("pages", [])}


def proved(uid):
    return dbx("SELECT email_proved FROM users WHERE id=?", (uid,))[0][0]


FID, F = freelancer(B, A, "frida", features=FEAT)
# uma's account was made by the server's admin with the address typed in: nobody proved it (no mailed link, no OIDC)
UID, U = freelancer(B, A, "uma", features=FEAT)

# ================================================================ #5643: the profile does not take an address
r = U.patch(B + "/api/me", json={"email": "frida@example.com"})
check(dbx("SELECT email FROM users WHERE id=?", (UID,))[0][0] == "uma@example.com",
      f"#5643: PATCH /api/me sets no address (uma cannot type in somebody else's) {r.status_code}")
check(proved(UID) == "", "(setup) #5643: uma's address is not proved")

# ================================================================ #5643: a table by address
T1 = table(F, "Rates for Uma")
r = F.post(B + f"/api/sheets/{T1}/shares", json={"email": "uma@example.com", "role": "read"})
r2 = F.post(B + f"/api/sheets/{T1}/shares", json={"email": "nobody@example.com", "role": "read"})
check(r.status_code == r2.status_code == 201 and set(r.json()) == set(r2.json()),
      f"#5643: the answer is the same as for an address without an account {r.status_code} {r.text[:160]}")
check(not reads(U, T1), "#5643: an account whose address nobody proved does NOT read the table")
check(dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=? AND user_id IS NOT NULL", (T1,)) == [],
      "#5643: the address row stays open (bound to no account)")
check(sess("uma").get(B + f"/api/sheets/{T1}").status_code == 404, "#5643: a sign-in with the address not proved takes nothing")

# ================================================================ #5643: a wiki page by address
W1 = page(F, "Offer for Uma", "the offer text")
r = F.post(B + "/api/wiki/shares", json={"page_id": W1, "kind": "person", "email": "uma@example.com"})
r2 = F.post(B + "/api/wiki/shares", json={"page_id": W1, "kind": "person", "email": "nobody@example.com"})
check(r.ok and r2.ok and r.json() == r2.json() == {"ok": True, "by_email": True},
      f"#5643: wiki by address: the same answer as for an unknown address {r.status_code} {r.text[:160]}")
check("Offer for Uma" not in wiki_shared(U) and U.get(B + f"/api/wiki/shared/pages/{W1}").status_code == 404,
      "#5643: an account whose address nobody proved does NOT read the page")

# ================================================================ #5643: after the proof
dbx("UPDATE users SET email_proved='uma@example.com' WHERE id=?", (UID,))  # (a mailed link or a verified OIDC claim)
U = sess("uma")
check(reads(U, T1), "#5643: proved: the next sign-in takes the open address row, uma reads the table")
check(dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=? AND user_id IS NOT NULL", (T1,)) == [(UID,)],
      "#5643: ... the row is bound to her account now")
T2 = table(F, "Second sheet")
check(F.post(B + f"/api/sheets/{T2}/shares", json={"email": "UMA@example.com ", "role": "read"}).status_code == 201 and reads(U, T2),
      "#5643: proved: a table shared by address afterwards opens at once (case and blanks do not matter)")
r = F.post(B + "/api/wiki/shares", json={"page_id": W1, "kind": "person", "email": "uma@example.com"})
check(r.ok and "Offer for Uma" in wiki_shared(U), f"#5643: proved: the wiki page shared by address opens {r.status_code} {r.text[:120]}")
# an address proved before and changed by the admin afterwards proves nothing any more
dbx("UPDATE users SET email='uma.new@example.com' WHERE id=?", (UID,))
T3 = table(F, "Third sheet")
check(F.post(B + f"/api/sheets/{T3}/shares", json={"email": "uma.new@example.com", "role": "read"}).status_code == 201
      and not reads(U, T3), "#5643: an address changed after the proof: nothing until it is proved again")
# Fable F1: a row bound before (to the proved old address) is checked again when the address is shared anew
r = F.post(B + f"/api/sheets/{T1}/shares", json={"email": "uma@example.com", "role": "write"})
check(r.status_code == 201 and not reads(U, T1), f"#5643 F1: sharing the old address again does not keep / raise uma's share {r.status_code}")
rows = dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=? AND email_key!=''", (T1,))  # uma's and nobody's address
check(len(rows) == 2 and all(x[0] is None for x in rows), f"#5643 F1: ... the address row is open again {rows}")

sys.exit(done("p2983_c_api"))
