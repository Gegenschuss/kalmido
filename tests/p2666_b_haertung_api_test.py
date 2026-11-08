#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.666.0 part B API test (#4074 points 7, 9, 11): security hardening. Own container (kt.fresh), invented names only; the
person without an organisation (tests/freelancer_fixture.py) does every step that exists for her.
freelancer-matrix: office, wiki, files
 - 7: the end of a session clears the browser's HTTP cache (card previews ?v= keep "private, max-age"): the logout (as before),
   ending the own current session in the sessions list (another one of the own: no), and the first API answer to a session
   that ended elsewhere / expired (401 with the old cookie) answer Clear-Site-Data "cache"; a request without any cookie not
 - 9: the sign-in mark sgen (GET /api/state, GET /api/me) changes when a knowledge folder is shared with the person and again
   when the share is taken back (the offline copy of the knowledge pages goes at the next /api/state, core.js sessGuard);
   a share of someone else does not change it; for the person without an organisation it stays the same between two calls
 - 11: the card statement PDF (GET /api/office/cards/statements/<id>/file) comes with Content-Security-Policy: sandbox, for
   the person without an organisation too
usage: p2666_b_haertung_api_test.py <datadir>      (P2666B_NOSTART=1: use a running server)"""
import os
import sys
from datetime import date

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, done, sess  # noqa: E402

kt.fresh(prefix="P2666B")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": kt.PASSWORD, "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, Fr = freelancer(B, A)
D = date.today().isoformat()
CSD = "Clear-Site-Data"

# ================================================================== 7: the end of a session clears the HTTP cache
for who, mk in (("bob", lambda: sess("bob")), ("frida", lambda: sess("frida"))):
    s1 = mk()
    r = s1.post(B + "/api/auth/logout")
    check(r.ok and r.headers.get(CSD) == '"cache"', f"7 {who}: logout answers {CSD} (was so before) {r.headers.get(CSD)}")
    r = s1.get(B + "/api/state")  # the cookie is gone after the logout: no cookie, no header
    check(r.status_code == 401 and CSD not in r.headers, f"7 {who}: a request without a session cookie: 401 without {CSD} ({r.status_code} {r.headers.get(CSD)})")

    s2, _ = mk(), mk()
    old = s2.cookies.copy()
    ses = s2.get(B + "/api/me/sessions").json()["sessions"]
    other = next(x for x in ses if not x["current"])
    r = s2.delete(B + f"/api/me/sessions/{other['sid']}")
    check(r.ok and not r.json().get("current") and CSD not in r.headers, f"7 {who}: ending another own session clears nothing here {r.headers.get(CSD)}")
    s3 = mk()
    cur = next(x for x in ses if x["current"])
    r = s2.delete(B + f"/api/me/sessions/{cur['sid']}")
    check(r.ok and r.json().get("current") and r.headers.get(CSD) == '"cache"', f"7 {who}: ending the own current session answers {CSD} {r.status_code} {r.headers.get(CSD)}")

    # the ended session's cookie used again (another tab, the browser kept it): the 401 clears the cache
    s4 = sess(None)
    s4.cookies.update(old)
    r = s4.get(B + "/api/state")
    check(r.status_code == 401 and r.headers.get(CSD) == '"cache"', f"7 {who}: the first answer to an ended session's cookie: 401 + {CSD} ({r.status_code} {r.headers.get(CSD)})")
    r = s4.get(B + "/api/auth/info")
    check(r.ok and CSD not in r.headers, f"7 {who}: an open route with the old cookie clears nothing ({r.status_code})")
    check(s3.get(B + "/api/state").ok, f"7 {who}: the other session of the person goes on")

# ================================================================== 9: folder shares are part of the sign-in mark
WS = A.get(B + "/api/state").json()["me"]["workspaces"]
ORG = WS[0]["id"]
for s in (A, Bo, Ca):
    f = (s.get(B + "/api/state").json().get("settings", {}).get("features") or "").split(",")
    if "wiki" not in f:
        s.patch(B + "/api/settings", json={"features": ",".join([x for x in f if x] + ["wiki", "files"])})


def sgen(s):
    j = s.get(B + "/api/state").json()["me"]
    m = s.get(B + "/api/me").json()
    check(j.get("sgen") and j.get("sgen") == m.get("sgen"), f"9: /api/state and /api/me give the same sgen {j.get('sgen')} {m.get('sgen')}")
    return j.get("sgen")


Bo, Fr = sess("bob"), sess("frida")  # the loop above may have ended their first sessions
g0, c0 = sgen(Bo), sgen(Ca)
check(sgen(Bo) == g0, "9: the mark stays the same between two calls (nothing changed)")
r = A.post(B + "/api/wiki/folders", json={"space": f"org:{ORG}", "name": "Handbook 2666"})
check(r.status_code == 201, f"9: a knowledge folder {r.status_code} {r.text[:200]}")
fid = r.json()["folder"]["id"] if r.status_code == 201 else 0
r = A.post(B + f"/api/files/nodes/{fid}/shares", json={"user_id": uid["bob"], "role": "view"})
check(r.status_code == 201, f"9: share the folder with bob {r.status_code} {r.text[:200]}")
sid = (r.json() if r.ok else {}).get("id")
g1 = sgen(Bo)
check(g1 and g1 != g0, f"9: bob's mark changes with the share ({g0} -> {g1})")
check(sgen(Ca) == c0, "9: carol's mark stays (the share is not hers)")
r = A.post(B + f"/api/files/nodes/{fid}/shares", json={"user_id": uid["bob"], "role": "edit"})
g2 = sgen(Bo)
check(r.ok and g2 != g1, f"9: bob's mark changes when the role of the share changes ({g1} -> {g2})")
r = A.delete(B + f"/api/files/shares/{sid}")
check(r.ok, f"9: take the share back {r.status_code} {r.text[:200]}")
g3 = sgen(Bo)
check(g3 != g2, f"9: bob's mark changes when the share is taken back ({g2} -> {g3}): the offline copy goes")
f0 = sgen(Fr)
check(sgen(Fr) == f0, "9 frida: the mark of the person without an organisation stays the same between two calls")

# ================================================================== 11: the card statement PDF runs in a sandbox
for who, s, holder in (("alice", A, kt.me_id(A)), ("frida", Fr, FID)):
    if who == "alice":
        A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
    f = (s.get(B + "/api/state").json().get("settings", {}).get("features") or "").split(",")
    if "office" not in f:
        s.patch(B + "/api/settings", json={"features": ",".join([x for x in f if x] + ["office"])})
    card = s.post(B + "/api/office/cards", json={"holder_id": holder, "last4": "2666"})
    check(card.ok, f"11 {who}: a card {card.status_code} {card.text[:160]}")
    if not card.ok:
        continue
    st = s.post(B + f"/api/office/cards/{card.json()['id']}/statements", files={"file": ("stmt.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")}, data={"month": D[:7]})
    check(st.ok, f"11 {who}: a statement {st.status_code} {st.text[:160]}")
    if not st.ok:
        continue
    r = s.get(B + f"/api/office/cards/statements/{st.json()['statement']['id']}/file")
    csp = r.headers.get("Content-Security-Policy", "")
    check(r.ok and r.content.startswith(b"%PDF") and csp == "sandbox" and r.headers.get("X-Content-Type-Options") == "nosniff",
          f"11 {who}: the statement PDF inline with CSP sandbox ({r.status_code} {csp!r})")

sys.exit(done("p2666_b_haertung_api"))
