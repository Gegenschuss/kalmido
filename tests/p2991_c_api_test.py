#!/usr/bin/env python3
"""2.99.1 API tests, part C (#1959, video sign-offs for agents: API v1 + MCP), own container (start.sh). Invented companies,
people and links only (example.com and made-up video ids).
tenant-matrix: video
freelancer-matrix: videos
 - an agent sees a sign-off only at a task / list shared with it: list (?task_id, ?list_id = the list and its tasks), read
   (versions, state, comments with timecode, customer, agent, done, replies), never the customer link
 - 404: another list, another organisation's agent, a client's sign-off, a deleted one, a list outside the agent's list
   limit, a health list; the app's routes stay closed to agents (create 404 too)
 - writing (scope comments; without it 403): a comment at a timecode (author = the agent), an answer, done / open; an answer
   to a customer's comment needs the right to change the list (a viewer agent: 403); done of someone else's comment too
 - a person's own token: the same routes; a person without an organisation and its own agent: a private list
usage: p2991_c_api_test.py <datadir>      (P2991C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients"
V1 = "/api/v1/videos"


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
    return s


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        rows = c.execute(q, args).fetchall() if not write else c.execute(q, args)
        if write:
            c.commit()
            return None
        return rows
    finally:
        c.close()


def app_log():
    out = subprocess.run(["docker", "logs", "--tail", "400", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True, text=True)
    text = out.stdout + out.stderr
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


def agent(name, scopes, org=None, owner=None):
    body = {"scopes": scopes, "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"], bearer(r.json()["token"])


def share(s, lid, uid, role="edit"):
    r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": role})
    assert r.ok, r.text


def review(s, **place):
    r = s.post(B + "/api/videos", json={"url": "https://vimeo.com/123456789", "title": "Imagefilm", **place})
    if not r.ok:
        print(r.status_code, r.text[:300])
        app_log()
    assert r.ok, r.text
    return r.json()


def customer_comment(rv, body, at=None):
    """A customer's comment as the public route stores it (author_id NULL, ext_name)."""
    sql("INSERT INTO video_comments(review_id, version_id, org_id, parent_id, at_sec, body, author_id, ext_name, done, created_at) "
        "VALUES(?,?,?,NULL,?,?,NULL,?,0,?)", (rv["id"], rv["versions"][-1]["id"], rv["org_id"], at, body, "Erika Beispiel",
                                              time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), write=True)
    return sql("SELECT MAX(id) FROM video_comments WHERE review_id=? AND ext_name IS NOT NULL", (rv["id"],))[0][0]


if os.environ.get("P2991C_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Ca = sess("carol")
for s in (A, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})

AG, ag = agent("cutbot", ["read", "comments"], org=ORG)
RO, ro = agent("readbot", ["read"], org=ORG)
VW, vw = agent("viewbot", ["read", "comments"], org=ORG)
BB, bb = agent("betabot", ["read", "comments"], org=ORG2)

L = A.post(B + "/api/lists", json={"name": "Imagefilm Frühling", "org_id": ORG}).json()["id"]
LX = A.post(B + "/api/lists", json={"name": "Geheimprojekt", "org_id": ORG}).json()["id"]
LV = A.post(B + "/api/lists", json={"name": "Nur lesen", "org_id": ORG}).json()["id"]
LR = A.post(B + "/api/lists", json={"name": "Werbespot", "org_id": ORG}).json()["id"]  # one agent per list: the read agent's own
L2 = Ca.post(B + "/api/lists", json={"name": "Fremdprojekt", "org_id": ORG2}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Schnitt Rohfassung", "list_id": L}).json()["id"]
TX = A.post(B + "/api/tasks", json={"title": "Geheim", "list_id": LX}).json()["id"]
T2 = Ca.post(B + "/api/tasks", json={"title": "Fremd", "list_id": L2}).json()["id"]
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH"}).json()["id"]
share(A, L, AG)
share(A, LR, RO)
share(A, LV, VW, "view")
share(Ca, L2, BB)

RT = review(A, task_id=T)          # at a task of a shared list
RL = review(A, list_id=L)          # at the shared list itself
RX = review(A, task_id=TX)         # at a task of a list not shared with the agent
RC = review(A, client_id=CL)       # at a client only
RV = review(A, list_id=LV)         # at a list the viewer agent reads
RR = review(A, list_id=LR)         # at the read agent's list (scope read only)
R2 = review(Ca, task_id=T2)        # another organisation
c1 = A.post(B + f"/api/videos/{RT['id']}/comments", json={"at_sec": 83.4, "body": "Schnitt hier zu hart"}).json()["comment_id"]
A.post(B + f"/api/videos/{RT['id']}/comments", json={"parent_id": c1, "body": "Schaue ich mir an"})
A.post(B + f"/api/videos/{RT['id']}/comments", json={"at_sec": 12, "body": "Titel zu klein"})
CC = customer_comment(RT, "Logo bitte größer", 42.0)
SIG = A.post(B + f"/api/videos/{RT['id']}/signoff", json={})
check(SIG.ok, f"setup: a customer link {SIG.status_code} {SIG.text[:200]}")
TOK = SIG.json()["url"].split("/s/q/")[1] if SIG.ok else "none"

# ---------------------------------------------------------------- reading
r = ag.get(B + V1, params={"task_id": T})
check(r.ok and [x["id"] for x in r.json()["data"]] == [RT["id"]] and r.json()["next_cursor"] is None, f"the agent lists the task's sign-off {r.status_code} {r.text[:200]}")
if not r.ok:
    app_log()
r = ag.get(B + V1, params={"list_id": L})
check(r.ok and sorted(x["id"] for x in r.json()["data"]) == sorted([RT["id"], RL["id"]]), "?list_id = the list's and its tasks' sign-offs")
d = r.json()["data"][0] if r.ok and r.json()["data"] else {}
check("comments" not in d and "signoffs" not in d and d.get("url", "").startswith("/api/v1/videos/") and d.get("open_comments") is not None,
      f"the list: no comments, no customer links {sorted(d)}")
r = ag.get(B + f"{V1}/{RT['id']}")
check(r.ok, f"the agent reads the sign-off {r.status_code} {r.text[:200]}")
R = r.json() if r.ok else {}
cm = R.get("comments") or []
check([x["timecode"] for x in cm] == ["00:12", "00:42", "01:23"] and all(x["version"] == 1 for x in cm), f"comments by timecode {[(x.get('timecode'), x.get('body')) for x in cm]}")
cust = next((x for x in cm if x["id"] == CC), {})
check(cust.get("customer") and cust.get("author") == "Erika Beispiel" and cust.get("author_id") is None and not cust.get("agent"), f"the customer's comment {cust}")
top = next((x for x in cm if x["id"] == c1), {})
check(top.get("author") == "Alice Admin" and [y["body"] for y in top.get("replies", [])] == ["Schaue ich mir an"] and top.get("at_sec") == 83.4,
      f"a team comment with its answer {top}")
check("signoffs" not in R and TOK not in r.text and R.get("versions") and R["versions"][0]["provider"] == "vimeo" and R.get("state") == "open"
      and R.get("can_write") is True, "versions and state, never the customer link")
check(vw.get(B + f"{V1}/{RV['id']}").ok and vw.get(B + f"{V1}/{RV['id']}").json()["can_write"] is False, "a viewer agent reads (can_write false)")
check(ro.get(B + f"{V1}/{RR['id']}").ok and ro.get(B + f"{V1}/{RT['id']}").status_code == 404, "the read agent: its list only")

# ---------------------------------------------------------------- what an agent never sees
for path, who in ((f"{V1}/{RX['id']}", "a list not shared"), (f"{V1}/{RC['id']}", "a client's sign-off"), (f"{V1}/{R2['id']}", "another organisation"),
                  (f"{V1}/999999", "unknown")):
    check(ag.get(B + path).status_code == 404, f"{who}: GET 404")
    check(ag.post(B + path + "/comments", json={"body": "x"}).status_code == 404, f"{who}: comment 404")
    check(ag.patch(B + path + f"/comments/{c1}", json={"done": True}).status_code == 404, f"{who}: done 404")
check(ag.get(B + V1, params={"task_id": TX}).json()["data"] == [] and ag.get(B + V1, params={"list_id": L2}).json()["data"] == [], "foreign lists: empty")
for path in (f"{V1}/{RT['id']}", f"{V1}/{RL['id']}"):
    check(bb.get(B + path).status_code == 404, f"another organisation's agent: 404 {path}")
check(bb.get(B + f"{V1}/{R2['id']}").ok, "the other organisation's agent sees its own")
check(Ca.get(B + f"/api/videos/{RT['id']}").status_code == 404, "control: Carol neither")
# the app's routes stay closed to agents (no creating at all)
AGH = {"Authorization": ag.headers["Authorization"], "X-Requested-With": "kalmido"}
web = (requests.get(B + f"/api/videos/{RT['id']}", headers=AGH).status_code,
       requests.post(B + "/api/videos", json={"task_id": T, "url": "https://vimeo.com/1234567"}, headers=AGH).status_code,
       requests.post(B + f"/api/videos/{RT['id']}/signoff", json={}, headers=AGH).status_code)
check(all(x in (401, 403, 404) for x in web), f"an agent through the app's routes: not let in {web}")
check(ag.post(B + V1, json={"task_id": T, "url": "https://vimeo.com/1"}).status_code in (403, 404, 405), "no creating through the API")
check(ag.delete(B + f"{V1}/{RT['id']}").status_code in (403, 404, 405), "no deleting through the API")
# the list limit of an agent
LA = A.post(B + "/api/lists", json={"name": "Anderes Projekt", "org_id": ORG}).json()["id"]
share(A, LA, AG)
r = A.patch(B + f"/api/admin/agents/{AG}", json={"list_ids": [LA]})
check(r.ok, f"setup: the agent limited to another list {r.status_code} {r.text[:200]}")
check(ag.get(B + f"{V1}/{RT['id']}").status_code == 404 and ag.get(B + V1, params={"list_id": L}).json()["data"] == [], "outside the list limit: 404")
A.patch(B + f"/api/admin/agents/{AG}", json={"list_ids": []})
check(ag.get(B + f"{V1}/{RT['id']}").ok, "the limit lifted: visible again")
# a deleted sign-off
check(A.delete(B + f"/api/videos/{RL['id']}").ok and ag.get(B + f"{V1}/{RL['id']}").status_code == 404
      and all(x["id"] != RL["id"] for x in ag.get(B + V1, params={"list_id": L}).json()["data"]), "in the trash: 404")
A.post(B + f"/api/videos/{RL['id']}/restore")
# a health list: never for an agent (even as a member)
LH = A.post(B + "/api/lists", json={"name": "Arzttermine", "org_id": ORG}).json()["id"]
share(A, LH, AG)
RH = review(A, list_id=LH)
check(ag.get(B + f"{V1}/{RH['id']}").ok, "setup: visible while it is a normal list")
sql("UPDATE lists SET life='health' WHERE id=?", (LH,), write=True)
check(ag.get(B + f"{V1}/{RH['id']}").status_code == 404 and ag.get(B + V1, params={"list_id": LH}).json()["data"] == [], "a health list: 404")

# ---------------------------------------------------------------- input
check(ag.get(B + V1).status_code == 400 and ag.get(B + V1, params={"task_id": T, "list_id": L}).status_code == 400, "exactly one of task_id / list_id")
check(ag.get(B + V1, params={"task_id": "x"}).status_code == 400 and ag.get(B + V1, params={"client_id": CL}).status_code == 400, "a bad / unknown parameter: 400")
check(ag.post(B + f"{V1}/{RT['id']}/comments", json={"body": "x", "kind": "y"}).status_code == 400, "an unknown field: 400")
check(ag.post(B + f"{V1}/{RT['id']}/comments", json={"body": "  "}).status_code == 400, "an empty comment: 400")
check(ag.post(B + f"{V1}/{RT['id']}/comments", json={"body": "x", "at_sec": 90000}).status_code == 400, "a timecode beyond 24 h: 400")
check(ag.patch(B + f"{V1}/{RT['id']}/comments/{c1}", json={"done": "yes"}).status_code == 400, "done must be a boolean")

# ---------------------------------------------------------------- writing
r = ag.post(B + f"{V1}/{RT['id']}/comments", json={"at_sec": 41.5, "body": "Zusammenfassung: Logo größer (00:42), Schnitt bei 01:23 weicher"})
check(r.status_code == 201, f"the agent comments at a timecode {r.status_code} {r.text[:200]}")
mine = r.json().get("comment") or {} if r.status_code == 201 else {}
check(mine.get("agent") and mine.get("author") == "Cutbot" and mine.get("author_id") == AG and mine.get("timecode") == "00:41" and not mine.get("customer"),
      f"author = the agent {mine}")
row = sql("SELECT author_id, ext_name FROM video_comments WHERE id=?", (mine.get("id", 0),))
check(len(row) == 1 and row[0][0] == AG and row[0][1] is None, "stored as the agent's")
r = ag.post(B + f"{V1}/{RT['id']}/comments", json={"parent_id": c1, "body": "Vorschlag: zwei Frames länger"})
check(r.status_code == 201 and r.json()["comment"]["parent_id"] == c1 and r.json()["comment"]["at_sec"] is None, "an answer to a team comment")
r = ag.post(B + f"{V1}/{RT['id']}/comments", json={"parent_id": CC, "body": "Wird im nächsten Schnitt größer"})
check(r.status_code == 201, f"an editing agent answers the customer {r.status_code}")
check(any(y["body"] == "Wird im nächsten Schnitt größer" for x in r.json()["review"]["comments"] if x["id"] == CC for y in x["replies"]), "the answer sits at the customer's comment")
r = ag.patch(B + f"{V1}/{RT['id']}/comments/{c1}", json={"done": True})
check(r.ok and next(x for x in r.json()["comments"] if x["id"] == c1)["done"], "done (someone else's comment, the agent may change the list)")
r = ag.patch(B + f"{V1}/{RT['id']}/comments/{c1}", json={"done": False})
check(r.ok and not next(x for x in r.json()["comments"] if x["id"] == c1)["done"], "open again")
check(any(x["author"] == "Cutbot" for x in A.get(B + f"/api/videos/{RT['id']}").json()["comments"]), "the app sees the agent's comments")
# the customer page shows the agent's answer (the team's answer), never its internal comment
pg = requests.get(B + "/s/q/" + TOK, allow_redirects=False)
check(pg.status_code == 200 and "Wird im nächsten Schnitt größer" in pg.text and "Zusammenfassung" not in pg.text, "customer page: the answer only")
# scope comments missing
check(ro.post(B + f"{V1}/{RR['id']}/comments", json={"body": "x"}).status_code == 403, "without the scope comments: 403")
cr = A.post(B + f"/api/videos/{RR['id']}/comments", json={"body": "Ton prüfen"}).json()["comment_id"]
check(ro.patch(B + f"{V1}/{RR['id']}/comments/{cr}", json={"done": True}).status_code == 403, "done without the scope: 403")
# a viewer agent: comments, but no answer to the customer and no done of others' comments
CV = customer_comment(RV, "Musik zu laut", 10.0)
cv_team = A.post(B + f"/api/videos/{RV['id']}/comments", json={"body": "Farben prüfen"}).json()["comment_id"]
r = vw.post(B + f"{V1}/{RV['id']}/comments", json={"body": "Notiz für den Schnitt", "at_sec": 3})
check(r.status_code == 201, f"a viewer agent comments (like viewers in the app) {r.status_code}")
VMINE = r.json()["comment"]["id"] if r.status_code == 201 else 0
check(vw.post(B + f"{V1}/{RV['id']}/comments", json={"parent_id": CV, "body": "x"}).status_code == 403, "a viewer agent: no answer to the customer (403)")
check(vw.post(B + f"{V1}/{RV['id']}/comments", json={"parent_id": cv_team, "body": "ok"}).status_code == 201, "but an answer to a team comment")
check(vw.patch(B + f"{V1}/{RV['id']}/comments/{cv_team}", json={"done": True}).status_code == 403, "a viewer agent: done of another's comment 403")
check(vw.patch(B + f"{V1}/{RV['id']}/comments/{VMINE}", json={"done": True}).ok, "its own comment: done")
check(vw.get(B + f"{V1}/{RT['id']}").status_code == 404, "the viewer agent sees nothing of the other list")

# ---------------------------------------------------------------- a person's own token: the same routes
tok = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "comments"]}).json().get("token")
pt = bearer(tok)
check(pt.get(B + f"{V1}/{RX['id']}").ok, "a person's token: what the person sees")
check(pt.get(B + f"{V1}/{RC['id']}").status_code == 404, "a client's sign-off: for the app only (also a person's token)")
check(pt.post(B + f"{V1}/{RX['id']}/comments", json={"body": "per Skript"}).status_code == 201, "a person's token comments")

# ---------------------------------------------------------------- a person without an organisation and its own agent
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Hochzeitsfilm", "org_id": None}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Schnitt", "list_id": FL}).json()["id"]
FA, fa = agent("fridabot", ["read", "comments"], owner=FID)
share(Fr, FL, FA)
RF = review(Fr, task_id=FT)
check(RF["org_id"] is None, "setup: a private sign-off")
r = fa.get(B + f"{V1}/{RF['id']}")
check(r.ok and r.json()["space"] == "private", f"the freelancer's agent reads it {r.status_code} {r.text[:200]}")
check(fa.post(B + f"{V1}/{RF['id']}/comments", json={"body": "Musik passt", "at_sec": 5}).status_code == 201, "and comments")
check(fa.get(B + f"{V1}/{RT['id']}").status_code == 404 and ag.get(B + f"{V1}/{RF['id']}").status_code == 404, "no way across: 404 both ways")
check(Ca.get(B + f"/api/videos/{RF['id']}").status_code == 404, "control: a stranger neither")

print(f"p2991_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
