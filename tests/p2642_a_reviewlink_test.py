#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.642.0 part A API test (#4772): the client link of a sign-off for clients without an account (office_signoffs kind
video, videos/vdlink.py). Own container (org encryption on). Invented companies, people and links only.
tenant-matrix: video
freelancer-matrix: videos
 - several live links per sign-off (each its own expiry, each switched off alone), at most ten at once (409)
 - only who may change the sign-off makes / stops a link: a viewer of the project 403, another organisation 404
 - the page without an account: only this sign-off (no task, project, other sign-off, internal comment)
 - a comment at a timecode with the name; the name stays for this link (cookie on the link's path) and fills both forms
 - in the app the comment is the client's (customer, author = the typed name, no account)
 - Approve -> the state of the sign-off, the record, the decision line, a bell item for the creator
 - a new version: the same link shows it and decides again; the decided record stays (history), the new one is open;
   the undo of the new version gives the link its decision back
 - older versions only on a link made with "older versions too" (read-only, no comment / decision form)
 - switched off / expired / unknown = the same answer; a version of another sign-off through a link: 409, nothing stored
 - a person without an organisation: private sign-off, link, comment, decision
 - comments limited per address
usage: p2642_a_reviewlink_test.py <datadir>      (a fresh container; P2642A_NOSTART=1 = the server already runs)"""
import base64
import os
import re
import sys
from datetime import date, timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
import requests  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check, dbx, sess  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2642A")
FEAT = "cal,comments,collab,office,clients,videos"
V = "/api/videos"


def write(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    try:
        c.execute(q, args)
        c.commit()
    finally:
        c.close()


def guest():
    s = requests.Session()
    s.headers.update({"Accept-Language": "en", "User-Agent": "TestBrowser/1.0"})
    return s


def tok(link):
    return link["url"].split("/s/q/")[1]


def keys(text):
    return re.findall(r'name="f" value="([0-9a-f]+)"', text), re.findall(r'name="v" value="(\d+)"', text)


A = kt.setup()
for u, n in (("bob", "Bob Viewer"), ("carol", "Carol Other")):
    assert A.post(B + "/api/users", json={"username": u, "display_name": n, "password": kt.PASSWORD, "email": f"{u}@example.com"}).ok
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Film", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
L = A.post(B + "/api/lists", json={"name": "Imagefilm Projekt Geheim", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "view"})
T = A.post(B + "/api/tasks", json={"title": "Schnitt Aufgabe Intern", "list_id": L}).json()["id"]
r = A.post(B + V, json={"task_id": T, "title": "Imagefilm Rohschnitt", "url": "https://www.youtube.com/watch?v=AbCdEfGhI_9"})
check(r.ok, f"a sign-off at a task {r.status_code} {r.text[:200]}")
VID = r.json()["id"]
V1 = r.json()["versions"][0]["id"]
OTHER = A.post(B + V, json={"task_id": T, "title": "Anderer Film Zweitabnahme", "url": "https://vimeo.com/123456789"}).json()
check(A.post(B + f"{V}/{VID}/comments", json={"body": "Interne Notiz Ton", "version_id": V1}).ok, "an internal comment")

# ---------------------------------------------------------------- several links, rights
S1 = A.post(B + f"{V}/{VID}/signoff", json={"expires": None}).json()
tomorrow = (date.today() + timedelta(days=2)).isoformat()
r = A.post(B + f"{V}/{VID}/signoff", json={"expires": tomorrow, "show_old": True})
S2 = r.json()
check(r.ok and S2["live"] and S2["show_old"] and S2["expires_at"] and not S1["show_old"], f"a second link with expiry and older versions {r.text[:200]}")
R = A.get(B + f"{V}/{VID}").json()
check(sum(1 for x in R["signoffs"] if x["live"]) == 2, "both links run at once (several links per sign-off)")
n0 = dbx("SELECT COUNT(*) FROM office_signoffs WHERE video_id=?", (VID,))[0][0]
check(Bo.post(B + f"{V}/{VID}/signoff", json={}).status_code in (403, 404) and dbx("SELECT COUNT(*) FROM office_signoffs WHERE video_id=?", (VID,))[0][0] == n0,
      "a viewer of the project makes no link (only who may change the sign-off)")
check(Ca.post(B + f"{V}/{VID}/signoff", json={}).status_code == 404, "another organisation: 404")
check(Ca.post(B + f"{V}/{VID}/signoffs/{S1['id']}/revoke").status_code == 404, "another organisation stops no link")
extra = [A.post(B + f"{V}/{VID}/signoff", json={}).json() for _ in range(8)]
r = A.post(B + f"{V}/{VID}/signoff", json={})
check(r.status_code == 409, f"the eleventh running link: 409 ({r.status_code})")
for x in extra:
    A.post(B + f"{V}/{VID}/signoffs/{x['id']}/revoke")
check(sum(1 for x in A.get(B + f"{V}/{VID}").json()["signoffs"] if x["live"]) == 2, "switched off one by one, the two first ones run on")

# ---------------------------------------------------------------- the page without an account
T1, T2 = tok(S1), tok(S2)
G = guest()
UNKNOWN = guest().get(B + "/s/q/" + "z" * 43)
pg = G.get(B + "/s/q/" + T1)
check(pg.status_code == 200 and "Imagefilm Rohschnitt" in pg.text and "Version 1" in pg.text, f"the link opens without an account {pg.status_code}")
check(all(x not in pg.text for x in ("Schnitt Aufgabe Intern", "Imagefilm Projekt Geheim", "Anderer Film Zweitabnahme", "Interne Notiz Ton", "Alpha Film")),
      "only this sign-off: no task, project, other sign-off, internal comment or organisation")
check("default-src 'none'" in pg.headers.get("Content-Security-Policy", "") and pg.headers.get("Cache-Control", "").startswith("no-store"),
      "the strict CSP of the customer page")
check('class="vdr-vers"' not in pg.text, "a link without older versions shows no version list")
fk, vk = keys(pg.text)
r = G.post(B + f"/s/q/{T1}/comments", data={"f": fk[0], "v": vk[0], "name": "Erika Gast", "text": "Logo <b>größer</b>", "at": "00:42"}, allow_redirects=False)
check(r.status_code == 303 and "kgn=" in r.headers.get("Set-Cookie", "") and f"Path=/s/q/{T1}" in r.headers.get("Set-Cookie", "")
      and "HttpOnly" in r.headers.get("Set-Cookie", ""), f"a comment at 00:42; the name is kept on this link only {r.headers.get('Set-Cookie')}")
row = dbx("SELECT at_sec, ext_name, author_id, version_id FROM video_comments WHERE review_id=? AND ext_name IS NOT NULL", (VID,))
check(len(row) == 1 and row[0][0] == 42.0 and row[0][1] == "Erika Gast" and row[0][2] is None and row[0][3] == V1, f"stored at the second as a guest {row}")
pg = G.get(B + "/s/q/" + T1)
check(pg.text.count('value="Erika Gast"') == 2 and "Logo &lt;b&gt;größer&lt;/b&gt;" in pg.text,
      "the name once: it fills the comment and the decision form; the comment escaped")
check(guest().get(B + "/s/q/" + T1).text.count('value="Erika Gast"') == 0, "another browser does not get the name")
R = A.get(B + f"{V}/{VID}").json()
c1 = [x for x in R["comments"] if x["customer"]]
check(len(c1) == 1 and c1[0]["author"] == "Erika Gast" and c1[0]["author_id"] is None and c1[0]["at_sec"] == 42.0,
      "in the app: the client's comment (customer, the typed name, no account)")
# a version of another sign-off through this link: refused, nothing stored there
ov = OTHER["versions"][0]["id"]
r = G.post(B + f"/s/q/{T1}/comments", data={"f": fk[0], "v": str(ov), "name": "Erika Gast", "text": "fremd"}, allow_redirects=False)
check(r.status_code == 409 and not dbx("SELECT 1 FROM video_comments WHERE review_id=? AND ext_name IS NOT NULL", (OTHER["id"],)),
      f"a version of another sign-off: 409, nothing stored there ({r.status_code})")
pg = G.get(B + "/s/q/" + T1 + "?v=1")
check("Anderer Film" not in pg.text, "?v= never reaches another sign-off")

# ---------------------------------------------------------------- the decision
pg = G.get(B + "/s/q/" + T1)
fk, vk = keys(pg.text)
r = G.post(B + "/s/q/" + T1, data={"f": fk[1], "v": vk[1] if len(vk) > 1 else vk[0], "do": "accept", "name": "Erika Gast", "ok": "1"}, allow_redirects=False)
check(r.status_code == 303, f"Approve {r.status_code}")
R = A.get(B + f"{V}/{VID}").json()
rec = next(x for x in R["signoffs"] if x["id"] == S1["id"])
check(R["state"] == "approved" and rec["state"] == "accepted" and rec["signer_name"] == "Erika Gast", f"the state of the sign-off and the record {R['state']} {rec['state']}")
check(any(x["customer"] and x["body"] == "Approved" and x["version_id"] == V1 for x in R["comments"]), "the decision line at version 1")
bell = kt.until(lambda: dbx("SELECT data FROM notifications WHERE user_id=? AND kind='signoff'", (ALICE,)), 10)
check(bell and '"accepted"' in bell[-1][0], f"the creator hears of it (bell item 'signoff') {bell}")
pg = G.get(B + "/s/q/" + T1)
check("Approved" in pg.text and 'name="text"' not in pg.text, "after the decision: the confirmation")

# ---------------------------------------------------------------- a new version at the same link
r = A.post(B + f"{V}/{VID}/versions", json={"url": "https://vimeo.com/987654321"})
check(r.ok, f"version 2 {r.status_code}")
V2 = r.json()["new_version"]
pg = G.get(B + "/s/q/" + T1)
check(pg.status_code == 200 and "Version 2" in pg.text and "player.vimeo.com/video/987654321" in pg.text and 'name="text"' in pg.text and 'name="do"' in pg.text,
      "the same link shows the new version and takes comments and the decision again")
check(pg.text.count('value="Erika Gast"') == 2, "the name is still there")
pg1 = G.get(B + "/s/q/" + T1 + "?v=1")
check("Version 2" in pg1.text.split("</header>")[0] and "youtube-nocookie.com/embed/AbCdEfGhI_9" not in pg1.text, "without the tick ?v=1 stays on the newest version")
R = A.get(B + f"{V}/{VID}").json()
old = next(x for x in R["signoffs"] if x["id"] == S1["id"])
new = [x for x in R["signoffs"] if x.get("carried_from") == S1["id"]]
check(R["state"] == "open" and old["state"] == "accepted" and old["signer_name"] == "Erika Gast" and not old["live"]
      and len(new) == 1 and new[0]["live"] and new[0]["url"] == S1["url"], "the decided record stays (history), the link goes on open with the same URL")
check(any(x["customer"] and x["body"] == "Approved" and x["version_id"] == V1 for x in R["comments"]), "the old decision stays at version 1")
fk, vk = keys(pg.text)
r = G.post(B + "/s/q/" + T1, data={"f": fk[1], "v": str(V2), "do": "decline", "name": "Erika Gast", "reason": "Musik tauschen"}, allow_redirects=False)
check(r.status_code == 303 and A.get(B + f"{V}/{VID}").json()["state"] == "changes", f"Request changes on version 2 {r.status_code}")
# a third version and its undo: the link gives the decision back
V3 = A.post(B + f"{V}/{VID}/versions", json={"url": "https://vimeo.com/987654322"}).json()["new_version"]
check("Version 3" in G.get(B + "/s/q/" + T1).text, "version 3 at the same link")
check(A.delete(B + f"{V}/{VID}/versions/{V3}").ok, "undo of version 3")
pg = G.get(B + "/s/q/" + T1)
check("Changes requested" in pg.text and 'name="text"' not in pg.text, "after the undo the link shows its decision again")
check(not [x for x in A.get(B + f"{V}/{VID}").json()["signoffs"] if x.get("carried_from") and x["state"] == "open" and x["live"] and x["url"] == S1["url"]],
      "no open record of the link is left")

# ---------------------------------------------------------------- older versions only with the tick
pg = G.get(B + "/s/q/" + T1 + "?v=1")
check(pg.status_code == 200 and "youtube-nocookie.com/embed/AbCdEfGhI_9" not in pg.text and 'class="vdr-vers"' not in pg.text,
      "a link without the tick: ?v=1 shows nothing older")
pg = G.get(B + "/s/q/" + T2)
check('class="vdr-vers"' in pg.text and f'href="/s/q/{T2}?v=1"' in pg.text and "Version 2" in pg.text, "the link with the tick lists the versions")
pg = G.get(B + "/s/q/" + T2 + "?v=1")
head = pg.text.split("</header>")[0]
check(pg.status_code == 200 and "Version 1" in head and "youtube-nocookie.com/embed/AbCdEfGhI_9" in pg.text and "Logo &lt;b&gt;" in pg.text,
      "version 1 with its player and the client's comment there")
check('name="text"' not in pg.text and 'name="do"' not in pg.text and "older version" in pg.text, "an older version is read-only (no comment, no decision)")

# ---------------------------------------------------------------- the same answer for switched off / expired / unknown
# 2.642.0 (#4772, review): a digit outside 0-9 in ?v= is no error page
check(guest().get(B + "/s/q/" + T2 + "?v=%C2%B2").status_code == 200, "?v= with a superscript digit shows the newest version")
# 2.642.0 (#4772, review): a decided link can be switched off and then does not come back with a new version
D1 = next(x for x in A.get(B + f"{V}/{VID}").json()["signoffs"] if x.get("carried_from") == S1["id"] and x["state"] == "declined")
check(A.post(B + f"{V}/{VID}/signoffs/{D1['id']}/revoke").ok and guest().get(B + "/s/q/" + T1).text == UNKNOWN.text, "a decided link switched off answers like an unknown one")
V4 = A.post(B + f"{V}/{VID}/versions", json={"url": "https://vimeo.com/987654323"}).json()["new_version"]
check(guest().get(B + "/s/q/" + T1).text == UNKNOWN.text, "a new version does not bring the switched-off link back")
check(A.delete(B + f"{V}/{VID}/versions/{V4}").ok, "undo of version 4")
check(A.post(B + f"{V}/{VID}/signoffs/{S2['id']}/revoke").ok, "switch the second link off")
off = guest().get(B + "/s/q/" + T2)
S3 = A.post(B + f"{V}/{VID}/signoff", json={}).json()
write("UPDATE office_signoffs SET expires_at=? WHERE id=?", ("2020-01-01T00:00:00+00:00", S3["id"]))
exp = guest().get(B + "/s/q/" + tok(S3))
check(off.status_code == exp.status_code == UNKNOWN.status_code == 404 and off.text == exp.text == UNKNOWN.text, "switched off = expired = unknown")

# ---------------------------------------------------------------- a person without an organisation
FID, Fr = freelancer(B, A, features="cal,comments,collab,office,clients,videos")
FL = Fr.post(B + "/api/lists", json={"name": "Frida privat"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Hochzeitsfilm", "list_id": FL}).json()["id"]
r = Fr.post(B + V, json={"task_id": FT, "title": "Hochzeit Schnitt", "url": "https://vimeo.com/55555555"})
check(r.ok and r.json()["org_id"] is None, f"a private sign-off {r.status_code} {r.text[:200]}")
FV = r.json()["id"]
F1, F2 = Fr.post(B + f"{V}/{FV}/signoff", json={}).json(), Fr.post(B + f"{V}/{FV}/signoff", json={"show_old": True}).json()
check(F1.get("live") and F2.get("live") and F2["show_old"], "two links of a private sign-off")
check(A.post(B + f"{V}/{FV}/signoff", json={}).status_code == 404, "nobody else makes a link there")
FG = guest()
pg = FG.get(B + "/s/q/" + tok(F1))
fk, vk = keys(pg.text)
r = FG.post(B + f"/s/q/{tok(F1)}/comments", data={"f": fk[0], "v": vk[0], "name": "Paul Gast", "text": "Schöner Anfang", "at": "0:10"}, allow_redirects=False)
check(r.status_code == 303, f"the guest comments on the private sign-off {r.status_code}")
pg = FG.get(B + "/s/q/" + tok(F1))
fk, vk = keys(pg.text)
r = FG.post(B + "/s/q/" + tok(F1), data={"f": fk[1], "v": vk[-1], "do": "accept", "name": "Paul Gast", "ok": "1"}, allow_redirects=False)
FR = Fr.get(B + f"{V}/{FV}").json()
check(r.status_code == 303 and FR["state"] == "approved" and any(x["customer"] and x["author"] == "Paul Gast" for x in FR["comments"]),
      "decided; the comment shows as the guest's")
check(Fr.post(B + f"{V}/{FV}/versions", json={"url": "https://vimeo.com/55555556"}).ok and "Version 2" in FG.get(B + "/s/q/" + tok(F1)).text,
      "a new version at the same private link")

# ---------------------------------------------------------------- comments limited per address
S4 = A.post(B + f"{V}/{OTHER['id']}/signoff", json={}).json()
pg = guest().get(B + "/s/q/" + tok(S4))
fk, vk = keys(pg.text)
codes = [requests.post(B + f"/s/q/{tok(S4)}/comments", data={"f": fk[0], "v": vk[0], "name": "Erika", "text": f"Nr {i}"}, allow_redirects=False).status_code
         for i in range(12)]
check(429 in codes, f"guest comments are limited per address {codes}")

sys.exit(kt.done("p2642_a_reviewlink"))
