#!/usr/bin/env python3
"""2.126.2 B API tests (own container, org encryption on):
 - #2358 a: a public link of an organisation's page whose maker left the organisation / was disabled: the dialog shows it
   ended (one query for the list), the link answers 404, it no longer counts as a live share (mark, count); back in the
   organisation it works again; private spaces unchanged
 - #2358 b: a sealed page text whose key is gone: GET 409 wiki_unreadable (with wiki_encrypt off and on), PATCH refused
   (the stored text stays), search / history / export / guest page / public link do not fail; a plain text that only
   starts like a sealed one ("kenc1: …", short) stays readable
 - #2355: a person share gives exactly that person one News item (wiki_shared, path only), not again for the same live
   share, not for oneself or others, also by e-mail address; it stays after a revoke; the sharing row of the notification
   settings turns it off; a person without an organisation (freelancer-matrix: wiki) shares and receives the same way
usage: p21262_b_api_test.py <datadir>      (P21262B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import io
import os
import subprocess
import sys
import time
import zipfile

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall() if not write else c.execute(q, args)
        if write:
            c.commit()
            return None
        return r
    finally:
        c.close()


def setting(k, v):
    sql("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT (key) DO UPDATE SET value=excluded.value", (k, v), write=True)


def page(s, space, path, body=""):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def share(s, **b):
    return s.post(B + "/api/wiki/shares", json=b)


def raw(pid):
    return sql("SELECT body FROM wiki_pages WHERE id=?", (pid,))[0][0]


def news(s, kind="wiki_shared"):
    return [x for x in s.get(B + "/api/news").json().get("items", []) if x["kind"] == kind]


def anon(path):
    return requests.get(B + path, allow_redirects=False)


if os.environ.get("P21262B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Customer")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
FEAT = "cal,comments,collab,wiki"
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
DAVE = Da.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
SP = f"org:{ORG}"

# ---------------------------------------------------------------- #2358 a: a link whose maker left the organisation
op = page(A, SP, "Handbook", "for customers")
r = share(Bo, page_id=op, kind="link")
check(r.status_code == 201 and r.json().get("ended") is False, "#2358: a member's new link is not ended " + r.text[:200])
blink = r.json()
btok = blink.get("url", "").rsplit("/", 1)[-1]
r = share(A, page_id=op, kind="link")
alink = r.json()
check(anon(f"/s/w/{btok}").status_code == 200, "#2358: the member's link works while the member is in the organisation")
check(A.get(B + f"/api/wiki/pages/{op}").json().get("shares") == 2, "#2358: two live links counted")
sql("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG, BOB), write=True)
r = A.get(B + "/api/wiki/shares", params={"page": op})
sh = {x["id"]: x for x in r.json().get("shares", [])} if r.ok else {}
check(r.ok and sh.get(blink["id"], {}).get("ended") is True and sh.get(alink["id"], {}).get("ended") is False,
      "#2358: the dialog shows the link of the person who left as ended, the admin's link not " + r.text[:400])
check(anon(f"/s/w/{btok}").status_code == 404, "#2358: the ended link does not open")
check(A.get(B + f"/api/wiki/pages/{op}").json().get("shares") == 1, "#2358: an ended link is no live share any more (count)")
r = A.get(B + "/api/wiki/shares", params={"space": SP})
check(r.ok and {x["id"]: x["ended"] for x in r.json()["shares"]}.get(blink["id"]) is True, "#2358: the list of the space marks it too")
r = A.patch(B + f"/api/wiki/shares/{blink['id']}", json={"expires": None})
check(r.ok and r.json().get("ended") is True, "#2358: a single share answer carries ended " + r.text[:200])
r = A.delete(B + f"/api/wiki/shares/{blink['id']}")
check(r.ok and r.json().get("revoked") is True, "#2358: an admin can still turn the ended link off")
assert A.post(B + f"/api/wiki/shares/{blink['id']}/restore").ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
r = A.get(B + "/api/wiki/shares", params={"page": op})
check(r.ok and not any(x["ended"] for x in r.json()["shares"]) and anon(f"/s/w/{btok}").status_code == 200,
      "#2358: back in the organisation the link is live again")
sql("UPDATE users SET disabled=1 WHERE id=?", (BOB,), write=True)
r = A.get(B + "/api/wiki/shares", params={"page": op})
check(r.ok and {x["id"]: x["ended"] for x in r.json()["shares"]}.get(blink["id"]) is True and anon(f"/s/w/{btok}").status_code == 404,
      "#2358: a disabled maker ends the link too")
sql("UPDATE users SET disabled=0 WHERE id=?", (BOB,), write=True)
# private space: unchanged (the owner's own links never end this way)
pp = page(A, "private", "Notes", "private")
r = share(A, page_id=pp, kind="link")
check(r.status_code == 201 and r.json().get("ended") is False and anon("/s/w/" + r.json()["url"].rsplit("/", 1)[-1]).status_code == 200,
      "#2358: a private link is unchanged")

# ---------------------------------------------------------------- #2358 b: a sealed text whose key is gone
ORG3 = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ALICE}).json()["id"]
SP3 = f"org:{ORG3}"
setting("wiki_encrypt", "1")
lost = page(A, SP3, "Lost/Page", "Kumquat secret words")
keep = page(A, SP3, "Lost/Other", "Holunder readable")
check(raw(lost).startswith("kenc1:") and "Kumquat" not in raw(lost), "#2358: the page text is sealed (setup)")
sealed_lost = raw(lost)
# a readable page whose stored text is plain but starts like a sealed one (written while sealing was off)
setting("wiki_encrypt", "0")
look = page(A, SP3, "Lookalike", "kenc1: this is a plain note")
short = page(A, SP3, "Short", "kenc1:abc")
check(raw(look) == "kenc1: this is a plain note", "#2358: with wiki_encrypt off a new text stays plain (setup)")
# the key is gone: the other page is written again in plain words first (it stays readable), then the key row goes
assert A.patch(B + f"/api/wiki/pages/{keep}", json={"body": "Holunder readable"}).ok
sql("DELETE FROM org_keys WHERE org_id=?", (ORG3,), write=True)
for sw in ("0", "1"):
    setting("wiki_encrypt", sw)
    r = A.get(B + f"/api/wiki/pages/{lost}")
    check(r.status_code == 409 and r.json().get("code") == "wiki_unreadable" and "kenc1:" not in r.text,
          f"#2358: wiki_encrypt={sw}: an unreadable page is an error, never the ciphertext {r.status_code} {r.text[:200]}")
    r = A.patch(B + f"/api/wiki/pages/{lost}", json={"body": "overwritten"})
    check(r.status_code == 409 and raw(lost) == sealed_lost, f"#2358: wiki_encrypt={sw}: a save does not overwrite it silently {r.status_code}")
setting("wiki_encrypt", "0")
r = A.get(B + f"/api/wiki/pages/{look}")
check(r.ok and r.json().get("body") == "kenc1: this is a plain note", "#2358: a plain text that starts like a sealed one stays readable " + r.text[:200])
r = A.get(B + f"/api/wiki/pages/{short}")
check(r.ok and r.json().get("body") == "kenc1:abc", "#2358: a short text after the prefix stays readable " + r.text[:200])
r = A.get(B + f"/api/wiki/pages/{keep}")
check(r.ok and r.json().get("body") == "Holunder readable", "#2358: a plain page of the same space reads " + r.text[:200])
r = A.get(B + "/api/wiki/search", params={"space": SP3, "q": "Holunder"})
# 2.138.0 (#1972): the word index key follows the organisation's key (a renewed key indexes with the new one); with the key
# row gone the words indexed under it no longer match - as before after a restart. The search itself must not fail.
check(r.ok and isinstance(r.json().get("pages"), list), f"#2358: the search does not fail on an unreadable page {r.status_code} {r.text[:200]}")
r = A.get(B + "/api/wiki/search", params={"space": SP3, "q": "Lost"})
check(r.ok, f"#2358: a search that matches the unreadable page by its name does not fail {r.status_code}")
r = A.get(B + f"/api/wiki/pages/{lost}/versions")
check(r.ok and r.json().get("versions") is not None, f"#2358: the history of an unreadable page lists {r.status_code} {r.text[:200]}")
r = A.get(B + "/api/wiki/export", params={"space": SP3})
names = []
if r.ok and r.content[:2] == b"PK":
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
check(r.ok and "Lost/Other.md" in names and "Lost/Page.md" not in names, f"#2358: the export leaves the unreadable page out {r.status_code} {names}")
r = share(A, page_id=lost, kind="link")
if r.status_code == 201:
    check(anon("/s/w/" + r.json()["url"].rsplit("/", 1)[-1]).status_code == 404, "#2358: the public link of an unreadable page answers 404, not 500")
r = A.patch(B + f"/api/wiki/pages/{keep}", json={"path": "Lost/Renamed"})
check(r.ok, f"#2358: renaming a page beside an unreadable one (relink) works {r.status_code} {r.text[:200]}")

# ---------------------------------------------------------------- #2355: News for the person a page is shared with
mp = page(A, "private", "Customer/Plan", "the plan")
r = share(A, page_id=mp, kind="person", user_id=BOB)
check(r.status_code == 201, "#2355: a person share " + r.text[:200])
sid = r.json().get("id")
it = news(Bo)
check(len(it) == 1 and it[0]["data"].get("path") == "Customer/Plan" and it[0]["data"].get("folder") is False and it[0]["actor_id"] == ALICE
      and it[0].get("to_me") is True, "#2355: the person gets one News item with the path " + str(it)[:300])
check(set(it[0]["data"]) <= {"path", "folder"} if it else False, "#2355: no page content in the item")
share(A, page_id=mp, kind="person", user_id=BOB)
check(len(news(Bo)) == 1, "#2355: sharing the same page again (still live) adds no second item")
check(not news(A) and not news(Ca) and not news(Da), "#2355: nobody else gets an item (not the one who shares)")
r = share(A, page_id=mp, kind="person", email="dave@example.com")
it = news(Da)
check(r.ok and r.json().get("by_email") is True and len(it) == 1 and it[0]["data"].get("path") == "Customer/Plan",
      "#2355: by e-mail address the account gets the item (the answer reveals nothing) " + str(it)[:300])
share(A, page_id=mp, kind="person", email="dave@example.com")
check(len(news(Da)) == 1, "#2355: by e-mail address again: no second item")
r = share(A, space="private", folder="Customer", kind="person", email="carol@example.com")
it = news(Ca)
check(r.ok and len(it) == 1 and it[0]["data"].get("folder") is True and it[0]["data"].get("path") == "Customer", "#2355: a folder share " + str(it)[:300])
assert A.delete(B + f"/api/wiki/shares/{sid}").ok
# 2.360.0 (#2496): the item ends with its share (it named a path the person may no longer read)
check(len(news(Bo)) == 0, "#2496: the item is gone after a revoke")
# the sharing row of the notification settings turns it off
r = Bo.patch(B + "/api/settings", json={"notify": {"share": {"news": 0}}})
check(r.ok, "#2355: the sharing row can be switched off " + r.text[:200])
mp2 = page(A, "private", "Other/Page", "x")
check(share(A, page_id=mp2, kind="person", user_id=BOB).status_code == 201 and len(news(Bo)) == 0, "#2355: with the sharing row off no item")  # 2.360.0 (#2496): 0, the revoked one is gone
# a person without an organisation (freelancer-matrix: wiki)
FID, Fr = freelancer(B, A, features="cal,comments,collab,wiki")
fp = page(Fr, "private", "Offer", "the offer")
r = share(Fr, page_id=fp, kind="person", email="dave@example.com")
it = [x for x in news(Da) if x["actor_id"] == FID]
check(r.ok and len(it) == 1 and it[0]["data"].get("path") == "Offer", "#2355: a freelancer's share gives an item " + r.text[:200] + str(it)[:200])
share(A, page_id=mp2, kind="person", email="frida@example.com")
it = news(Fr)
check(len(it) == 1 and it[0]["data"].get("path") == "Other/Page", "#2355: a freelancer receives the item " + str(it)[:200])
check("Other/Page" in [p["path"] for p in Fr.get(B + "/api/wiki/shared").json().get("pages", [])], "#2355: the item's target (Shared with me) lists the page")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
