#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.485.0 (#3939): support access only with the client's consent (hosted). Own container (start.sh, a server key; hosted
with KALMIDO_HOSTED=1, then restarted self-hosted with KEEP=1). Invented accounts only (example.com).
 - without a grant the operator's ways into a client's account / organisation answer 403 (2.399.0, #2687, unchanged)
 - a person grants the own account (1 h to 7 days): the sign-in link and the password link work again; the use is logged on the
   grant (method, route pattern, status, who) and the client sees it; the operator's account list shows until when
 - an organisation admin grants the organisation: the operator renames it; a member cannot grant it (403), sees no grant
 - ending a grant (the person / an admin) or its end time passing closes the door again; a new grant replaces the open one
 - wrong hours = 400; a stranger cannot end somebody else's grant (404); a self-hosted server: hosted=false, POST = 409
freelancer-matrix: own
tenant-matrix: support
usage: p2485_a_support_test.py <datadir>"""
import os
import sys

import kt
from kt import B, check, sess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer, login, org_join  # noqa: E402

KEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (32 bytes, base64)


def dbw(q, a=()):
    c = kt._dbx.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(q, a)
        c.commit()
    finally:
        c.close()


kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_HOSTED": "1"})
A = kt.sess(None)
assert A.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
uid = {}
for u in ("carl", "cara"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
FID, _Fr = freelancer(B, A)
S = {u: login(B, u) for u in ("carl", "cara", "frida")}
for s in S.values():
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"}).ok
r = S["carl"].post(B + "/api/orgs", json={"name": "Client Studio"})
assert r.status_code == 201, r.text
CO = r.json()["id"]
assert S["carl"].put(B + f"/api/orgs/{CO}/members", json={"email": "cara@example.com"}).ok
assert org_join(B, "cara", CO)


def link(who):
    return A.post(B + f"/api/users/{who}/signin-link")


# ---- without a grant (2.399.0, unchanged)
check(link(FID).status_code == 403, "hosted, no grant: no sign-in link for a person without an organisation")
check(A.patch(B + f"/api/admin/orgs/{CO}", json={"name": "Taken over"}).status_code == 403, "hosted, no grant: the client's organisation stays its own")
j = S["frida"].get(B + "/api/support-access").json()
check(j["hosted"] is True and j["account"] is None and j["orgs"] == [] and j["hours"] == [1, 24, 72, 168], f"GET: hosted, nothing open {j}")

# ---- wrong input, wrong person
check(S["frida"].post(B + "/api/support-access", json={"hours": 5}).status_code == 400, "hours outside the list = 400")
check(S["frida"].post(B + "/api/support-access", json={"hours": True}).status_code == 400, "hours true = 400")
check(S["cara"].post(B + "/api/support-access", json={"hours": 1, "org_id": CO}).status_code == 403, "a member cannot grant its organisation")
check(S["frida"].post(B + "/api/support-access", json={"hours": 1, "org_id": CO}).status_code == 403, "a stranger cannot grant somebody's organisation")

# ---- the account grant (a person without an organisation: P4)
r = S["frida"].post(B + "/api/support-access", json={"hours": 1})
check(r.ok and r.json()["grant"]["active"] is True and r.json()["grant"]["org_id"] is None, "frida grants support access for 1 hour " + r.text[:120])
GF = r.json()["grant"]["id"]
r = link(FID)
check(r.ok and r.json().get("link"), "with the grant: the operator makes a sign-in link " + r.text[:120])
TOK = r.json()["link"].split("#signin/")[1]
check(kt.dbx("SELECT COUNT(*) FROM user_invites u, support_grants s WHERE s.id=? AND u.user_id=? AND u.expires_at<=s.ends_at", (GF, FID)) == [(1,)],
      "the link made through the grant ends with it (not after 7 days)")
X = kt.sess(None)
r = X.post(B + "/api/auth/link", json={"token": TOK})
check(r.ok and X.get(B + "/api/state").ok, "the operator signs in as frida with the link " + r.text[:120])
check(kt.dbx("SELECT COUNT(*) FROM sessions t, support_grants s WHERE s.id=? AND t.user_id=? AND t.via='support' AND t.expires_at<=s.ends_at",
             (GF, FID)) == [(1,)], "that session is a support session and ends with the grant at the latest")
for meth, path, body in (("post", "/api/me/tokens", {"name": "ops"}), ("post", "/api/me/app-passwords", {"name": "ops"}),
                         ("post", "/api/me/2fa/totp", {}), ("post", "/api/support-access", {"hours": 168}),
                         ("patch", "/api/me", {"password": "taken-over-1", "current_password": "x"})):
    r = getattr(X, meth)(B + path, json=body)
    check(r.status_code == 403 and r.json().get("code") == "support_session", f"support session: {meth.upper()} {path} -> 403 " + r.text[:100])
check(X.patch(B + "/api/settings", json={"lang": "en"}).ok, "support session: ordinary settings work")
r = A.post(B + f"/api/users/{FID}/invite", json={"send": False})
check(r.ok and "link" not in r.json(), "with the grant: a password link goes to frida's address only, never to the operator " + r.text[:120])
for body in ({"email": "ops@example.com"}, {"password": "taken-over-1"}, {"reset_2fa": True}, {"proxy_login": "ops"}):
    r = A.patch(B + f"/api/users/{FID}", json=body)
    check(r.status_code == 403, f"with the grant: no sign-in data {list(body)} -> 403 " + r.text[:100])
check(kt.dbx("SELECT email FROM users WHERE id=?", (FID,)) == [("frida@example.com",)], "frida's address is unchanged")
r = A.patch(B + f"/api/users/{FID}", json={"display_name": "Frida F"})
check(r.ok, "with the grant: the operator fixes her display name " + r.text[:100])
check(link(uid["cara"]).status_code in (403, 404), "frida's grant opens no other account")
users = {u["id"]: u for u in A.get(B + "/api/users?all=1").json()["users"]}
check(not users[FID].get("apart") and users[FID].get("support_until") and users[uid["cara"]].get("apart") is True,
      "the operator's account list: frida open until ..., cara apart")
j = S["frida"].get(B + "/api/support-access").json()
uses = j["account"]["uses"]
check(j["account"]["id"] == GF and any(u["method"] == "POST" and u["route"] == "/api/users/<int:uid>/signin-link" and u["status"] == 200
                                       and u["by"] == "Alice" for u in uses)
      and any(u["route"] == "/api/users/<int:uid>/invite" for u in uses), f"frida sees what the operator did (method, route, who) {uses}")
check(all(set(u) == {"at", "by", "method", "route", "status"} for u in uses), "the log holds no values, only what kind of request")
n = len(uses)
A.get(B + "/api/users?all=1")
check(len(S["frida"].get(B + "/api/support-access").json()["account"]["uses"]) == n, "listing the accounts is no use of the grant")

# ---- a new grant replaces the open one; ending closes the door
r = S["frida"].post(B + "/api/support-access", json={"hours": 24})
GF2 = r.json()["grant"]["id"]
check(r.ok and GF2 != GF and kt.dbx("SELECT COUNT(*) FROM support_grants WHERE id=? AND ended_at IS NOT NULL", (GF,)) == [(1,)],
      "a new grant ends the open one")
check(S["carl"].delete(B + f"/api/support-access/{GF2}").status_code == 404, "somebody else cannot end frida's grant")
check(X.get(B + "/api/state").ok, "replaced by a longer grant: the support session lives on")
check(S["frida"].delete(B + f"/api/support-access/{GF2}").ok, "frida ends it")
check(X.get(B + "/api/state").status_code == 401 and S["frida"].get(B + "/api/state").ok,
      "ended early: the session started with the operator's link ends too, frida's own session stays")
r = link(FID)
check(r.status_code == 403, "ended: no new sign-in link")
check(link(FID).status_code == 403, "ended: no sign-in link again")
j = S["frida"].get(B + "/api/support-access").json()
check(j["account"] is None and {p["id"] for p in j["past"]} >= {GF, GF2}, "ended grants show as earlier support access")

# ---- the time passing (a real state: the end set into the past)
r = S["frida"].post(B + "/api/support-access", json={"hours": 72})
GF3 = r.json()["grant"]["id"]
check(link(FID).ok, "open again (3 days)")
dbw("UPDATE support_grants SET ends_at='2020-01-01T00:00:00Z' WHERE id=?", (GF3,))
check(link(FID).status_code == 403, "after its end time: closed without anybody ending it")

# ---- the organisation grant
r = S["carl"].post(B + "/api/support-access", json={"hours": 24, "org_id": CO})
check(r.ok and r.json()["grant"]["org_id"] == CO, "carl (admin) grants the organisation " + r.text[:120])
GO = r.json()["grant"]["id"]
r = A.patch(B + f"/api/admin/orgs/{CO}", json={"name": "Client Studio GmbH"})
check(r.ok and kt.dbx("SELECT name FROM orgs WHERE id=?", (CO,)) == [("Client Studio GmbH",)], "with the grant: the operator renames it " + r.text[:120])
check(link(uid["cara"]).status_code in (403, 404), "the organisation's grant opens no member's account")
r = A.post(B + "/api/users", json={"username": "opsmate", "password": "password123"})
OPS = r.json()["id"]
for body in ({"members_add": [OPS]}, {"admins_add": [OPS]}):
    r = A.patch(B + f"/api/admin/orgs/{CO}", json=body)
    check(r.status_code == 403, f"with the grant: nobody new into the organisation {list(body)} " + r.text[:100])
check(not kt.dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (CO, OPS)) and not kt.dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (CO, OPS)),
      "... no invitation, no membership")
r = A.post(B + "/api/admin/agents", json={"username": "intruder", "org_id": CO})
check(r.status_code == 403 and not kt.dbx("SELECT 1 FROM users WHERE username='intruder'"), "with the grant: no new agent in the organisation " + r.text[:100])
j = S["carl"].get(B + "/api/support-access").json()
og = {o["org_id"]: o for o in j["orgs"]}
check(og[CO]["grant"]["id"] == GO and any(u["method"] == "PATCH" for u in og[CO]["grant"]["uses"]), f"carl sees the organisation's grant and its use {og}")
check(S["cara"].get(B + "/api/support-access").json()["orgs"] == [], "a member sees no organisation grant")
check(S["cara"].delete(B + f"/api/support-access/{GO}").status_code == 404, "a member cannot end it")
# the grant holds only while its admin is still an admin
dbw("UPDATE org_members SET role='member' WHERE org_id=? AND user_id=?", (CO, uid["carl"]))
check(A.patch(B + f"/api/admin/orgs/{CO}", json={"name": "Again"}).status_code == 403, "the granting admin demoted: the grant stops")
dbw("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (CO, uid["carl"]))
check(S["carl"].delete(B + f"/api/support-access/{GO}").ok, "carl ends it")
check(A.patch(B + f"/api/admin/orgs/{CO}", json={"name": "Again"}).status_code == 403, "ended: the organisation is closed again")

# ---- self-hosted: nothing to grant
kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, keep=True)
F2 = login(B, "frida")
check(F2.get(B + "/api/support-access").json()["hosted"] is False, "self-hosted: hosted=false (the section stays hidden)")
check(F2.post(B + "/api/support-access", json={"hours": 1}).status_code == 409, "self-hosted: no grant (409)")
sys.exit(kt.done("p2485_a_support"))
