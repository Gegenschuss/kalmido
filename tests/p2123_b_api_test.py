#!/usr/bin/env python3
"""2.123.0 B (#2104) API tests: read-only shares of knowledge pages and folders (own container, org encryption on).
 - person share (private space only): a folder "Customer A" covers its own page and every page below it, also one made
   later; never "Customer AB/…" (prefix trick) nor another page; the guest reads only through /api/wiki/shared* (index,
   page, files of shared pages), never the space's index, search, backlinks or the normal page routes; [[links]] to pages
   that are not shared stay text; by e-mail address without revealing the account; oneself 404; in an organisation 409
 - public link: /s/w/<token> without an account (noindex, no caching), the page / the folder's page list, files of shared
   pages only; unknown / expired / revoked = the same 404, Undo (restore) brings it back; the expiry in the past refused
 - rename (page, folder) takes the shares along; the trash hides a shared page; moving to the other workspace ends shares
 - rights (tenant-matrix: wiki): another organisation 404 (list, create, change, revoke); a member manages the
   organisation's links; a locked space (encrypted in the browser) shares nothing (409) and its links stop
 - a person without an organisation (freelancer-matrix: wiki): shares pages of the own private space (person + link)
usage: p2123_b_api_test.py <datadir>      (P2123B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import re
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


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


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def page(s, space, path, body=""):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(s, pid, name, data, mime):
    r = s.post(B + f"/api/wiki/pages/{pid}/files", files={"file": (name, data, mime)})
    assert r.status_code == 201, r.text
    return r.json()["files"][0]["id"]


def share(s, **b):
    return s.post(B + "/api/wiki/shares", json=b)


def shared(s):
    return {p["path"]: p["id"] for p in s.get(B + "/api/wiki/shared").json().get("pages", [])}


def anon(path):
    return requests.get(B + path, allow_redirects=False)


if os.environ.get("P2123B_NOSTART") != "1":
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
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
DAVE = Da.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
SP, SP2 = f"org:{ORG}", f"org:{ORG2}"

# ---------------------------------------------------------------- the private space of Alice
start = page(A, "private", "Customer A", "# Overview\nThe folder's own page.")
plan = page(A, "private", "Customer A/Plan", "")
intro = page(A, "private", "Customer A/Intro", "Hello **customer**.\n\n- [x] kick-off\n- [ ] sign-off\n")
ab = page(A, "private", "Customer AB/Note", "Another customer.")
secret = page(A, "private", "Secret", "internal only")
pic = upload(A, plan, "sketch.png", PNG, "image/png")
spdf = upload(A, secret, "secret.pdf", PDF, "application/pdf")
body = (f"# Plan\n\n![Sketch](/api/wiki/files/{pic}/sketch.png) and the [secret file](/api/wiki/files/{spdf}/secret.pdf).\n\n"
        "See [[Customer A/Intro]], [[Secret|the secret page]] and #12.\n\n<script>alert(1)</script>\n\n[x](javascript:alert(2)) [y](javascript:void)\n")
assert A.patch(B + f"/api/wiki/pages/{plan}", json={"body": body}).ok

# ---------------------------------------------------------------- person share of a folder
r = share(A, space="private", folder="Customer A", kind="person", email="dave@example.com")
# 2.123.0 (#2104, review): by e-mail address the answer is the same as for an unknown address (no account id / name)
check(r.ok and r.json().get("by_email") is True and "user" not in r.json(), "#2104: a folder shared with a person by e-mail address, nothing revealed " + r.text[:300])
r = share(A, space="private", folder="Customer A", kind="person", email="nobody@example.com")
check(r.ok and r.json().get("by_email") is True, "#2104: an unknown address is not revealed " + r.text[:200])
check(share(A, page_id=plan, kind="person", user_id=ALICE).status_code == 404, "#2104: no share with oneself")
got = shared(Da)
check(set(got) == {"Customer A", "Customer A/Plan", "Customer A/Intro"}, f"#2104: the guest sees the folder's pages only (not Customer AB, not Secret) {sorted(got)}")
later = page(A, "private", "Customer A/Later", "made after the share")
check("Customer A/Later" in shared(Da), "#2104: a page made later in the folder is shared too")
r = Da.get(B + f"/api/wiki/shared/pages/{plan}")
j = r.json() if r.ok else {}
h = j.get("html", "")
check(r.ok and f'href="#wsh/{intro}"' in h and "the secret page" in h and f"#wsh/{secret}" not in h,
      "#2104: a link to a shared page is a link, one to a page not shared is text " + h[:400])
check(f'src="/api/wiki/shared/files/{pic}/sketch.png"' in h and f"/files/{spdf}" not in h and "secret file" in h,
      "#2104: the shared page's picture through the guest route, a file of another page only as text " + h[:400])
check("<script" not in h and 'href="javascript' not in h and "&lt;script&gt;" in h, "#2104: the text is escaped, no script address " + h[:400])
check(j.get("owner_name") == "Alice Admin" and [f["id"] for f in j.get("files", [])] == [pic], "#2104: owner name and the page's files " + str(j)[:300])
r = Da.get(B + f"/api/wiki/shared/pages/{intro}")
check(r.ok and 'type="checkbox" disabled checked' in r.json().get("html", "") and "<strong>customer</strong>" in r.json().get("html", ""),
      "#2104: check boxes and emphasis " + r.text[:300])
r = Da.get(B + f"/api/wiki/shared/files/{pic}/sketch.png")
check(r.ok and r.content == PNG, f"#2104: the guest reads the shared picture {r.status_code}")
for x in (f"/api/wiki/shared/files/{spdf}", f"/api/wiki/shared/pages/{secret}", f"/api/wiki/shared/pages/{ab}", f"/api/wiki/pages/{plan}",
          f"/api/wiki/files/{pic}"):
    check(Da.get(B + x).status_code == 404, "#2104: the guest gets nothing else: " + x)
check(not Da.get(B + "/api/wiki/search", params={"q": "customer"}).json().get("pages"), "#2104: the guest's search does not find shared pages")
check(not Da.get(B + "/api/wiki", params={"space": "private"}).json().get("pages"), "#2104: the guest's own index stays his own")
check(Bo.get(B + f"/api/wiki/shared/pages/{plan}").status_code == 404 and not shared(Bo), "#2104: somebody else sees nothing")
# the mark in the owner's index and on the page
idx = {p["path"]: p for p in A.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]}
check(idx["Customer A/Plan"].get("shared") and idx["Customer A"].get("shared") and not idx["Customer AB/Note"].get("shared") and not idx["Secret"].get("shared"),
      "#2104: the mark in the index covers the folder only")
check(A.get(B + f"/api/wiki/pages/{plan}").json().get("shares") == 1 and A.get(B + f"/api/wiki/pages/{secret}").json().get("shares") == 0,
      "#2104: the page's share count")
r = A.get(B + "/api/wiki/shares", params={"page": plan})
j = r.json()
check(r.ok and j.get("person") is True and len(j["shares"]) == 1 and j["shares"][0]["direct"] is False and j["shares"][0]["folder"] is True,
      "#2104: the page's dialog shows the folder's share as inherited " + r.text[:300])
pshare = j["shares"][0]["id"] if j.get("shares") else 0
check(j["shares"][0]["user"] == {"id": None, "name": "dave@example.com", "by_email": True} if j.get("shares") else False,
      "#2104: a share made by e-mail address shows the typed address, not the account " + r.text[:300])
deep = page(A, "private", "Customer A/Deep", ">" * 3000 + " deep\n\n" + "**" * 1500 + "x" + "**" * 1500)
r = Da.get(B + f"/api/wiki/shared/pages/{deep}")
check(r.ok and "deep" in r.json().get("html", ""), f"#2104: deeply nested quotes / emphasis render (no recursion error) {r.status_code}")
# case and expiry
r = share(A, space="private", folder="customer a", kind="person", user_id=DAVE, expires="2000-01-01")
check(r.status_code == 400, "#2104: an expiry in the past is refused " + r.text[:200])

# ---------------------------------------------------------------- public link of a page and of a folder
r = share(A, page_id=plan, kind="link")
check(r.status_code == 201 and re.search(r"/s/w/[A-Za-z0-9_-]{30,}$", r.json().get("url", "")), "#2104: a public link of a page " + r.text[:200])
L1 = r.json()
tok1 = L1["url"].rsplit("/", 1)[-1]
r = anon(f"/s/w/{tok1}")
t = r.text
check(r.status_code == 200 and "<h1>Plan</h1>" in t and "noindex" in r.headers.get("X-Robots-Tag", "") and "no-store" in r.headers.get("Cache-Control", ""),
      f"#2104: the page without an account, noindex, no caching {r.status_code} {r.headers}")
check(f'src="/s/w/{tok1}/file/{pic}"' in t and f"/file/{spdf}" not in t and "the secret page" in t and "Intro" in t and f"/p/{intro}" not in t
      and f"/p/{secret}" not in t and "<script" not in t.split("</head>")[1], "#2104: page link: only the page, its picture, other pages as text " + t[:600])
r = anon(f"/s/w/{tok1}/file/{pic}")
check(r.ok and r.content == PNG and "no-store" in r.headers.get("Cache-Control", ""), "#2104: the picture through the link")
check(anon(f"/s/w/{tok1}/file/{spdf}").status_code == 404 and anon(f"/s/w/{tok1}/p/{intro}").status_code == 404, "#2104: nothing else through a page link")
r = share(A, space="private", folder="Customer A", kind="link")
tok2 = r.json().get("url", "").rsplit("/", 1)[-1]
r = anon(f"/s/w/{tok2}")
check(r.ok and f"/s/w/{tok2}/p/{plan}" in r.text and f"/p/{later}" in r.text and "Customer AB" not in r.text and "Secret" not in r.text,
      "#2104: the folder link lists its pages only " + r.text[:500])
r = anon(f"/s/w/{tok2}/p/{intro}")
check(r.ok and "<strong>customer</strong>" in r.text and f'href="/s/w/{tok2}"' in r.text, "#2104: a page of the folder link with the way back")
r = anon(f"/s/w/{tok2}/p/{plan}")
check(r.ok and f'href="/s/w/{tok2}/p/{intro}"' in r.text, "#2104: links between pages of the folder link work")
for x in (f"/s/w/{tok2}/p/{ab}", f"/s/w/{tok2}/p/{secret}", f"/s/w/{tok2}/file/{spdf}", "/s/w/" + "x" * 32, "/s/w/short"):
    check(anon(x).status_code == 404, "#2104: 404 through the folder link: " + x)
# revoke, Undo, expiry
r = A.delete(B + f"/api/wiki/shares/{L1['id']}")
check(r.ok and r.json().get("revoked") and anon(f"/s/w/{tok1}").status_code == 404, "#2104: a revoked link is gone at once")
r = A.post(B + f"/api/wiki/shares/{L1['id']}/restore")
check(r.ok and anon(f"/s/w/{tok1}").status_code == 200, "#2104: Undo of the revoke brings the same link back")
sql("UPDATE wiki_shares SET expires_at='2001-01-01T00:00:00+00:00' WHERE id=?", (L1["id"],), write=True)
check(anon(f"/s/w/{tok1}").status_code == 404, "#2104: an expired link is gone (the same answer)")
r = A.patch(B + f"/api/wiki/shares/{L1['id']}", json={"expires": None})
check(r.ok and anon(f"/s/w/{tok1}").status_code == 200, "#2104: the expiry removed, the link works again")
check(sql("SELECT COUNT(*) FROM wiki_shares WHERE token_hash IS NOT NULL AND (token LIKE ? OR token_hash=?)", (f"%{tok1}%", tok1))[0][0] == 0,
      "#2104: the token is never stored in plain text")

# ---------------------------------------------------------------- rename and move take the shares along
r = A.post(B + "/api/wiki/move", json={"space": "private", "from": "Customer A", "to": "Client X"})
check(r.ok, "#2104: folder renamed " + r.text[:200])
got = shared(Da)
check({"Client X", "Client X/Plan", "Client X/Intro", "Client X/Later"} <= set(got) and not any(k.startswith("Customer A") for k in got),
      f"#2104: the person share follows the folder's new name {sorted(got)}")
check(anon(f"/s/w/{tok2}/p/{plan}").ok and anon(f"/s/w/{tok1}").ok, "#2104: the links follow too")
assert A.patch(B + f"/api/wiki/pages/{plan}", json={"path": "Client X/Plan 2"}).ok
check(anon(f"/s/w/{tok1}").ok and "Plan 2" in anon(f"/s/w/{tok1}").text, "#2104: a page link follows the page's new name")
assert A.delete(B + f"/api/wiki/pages/{intro}").ok
check("Client X/Intro" not in shared(Da) and anon(f"/s/w/{tok2}/p/{intro}").status_code == 404, "#2104: a page in the trash is not shared")
assert A.post(B + "/api/wiki/restore", json={"ids": [intro]}).ok
check("Client X/Intro" in shared(Da), "#2104: back from the trash, shared again")
wander = page(A, "private", "Wander", "moves to the organisation")
r = share(A, page_id=wander, kind="person", user_id=DAVE)
check(r.status_code in (201, 404), "#2104: share by id (404 when the person is not visible) " + r.text[:200])
if r.status_code != 201:
    r = share(A, page_id=wander, kind="person", email="dave@example.com")
wtok = share(A, page_id=wander, kind="link").json().get("url", "").rsplit("/", 1)[-1]
check("Wander" in shared(Da) and anon(f"/s/w/{wtok}").ok, "#2104: shared before the move")
r = A.post(B + "/api/wiki/move-space", json={"space": "private", "to": SP, "pages": [wander]})
check(r.ok, "#2104: moved to the organisation " + r.text[:200])
check("Wander" not in shared(Da) and anon(f"/s/w/{wtok}").status_code == 404 and
      sql("SELECT COUNT(*) FROM wiki_shares WHERE path='Wander' AND revoked_at IS NULL")[0][0] == 0,
      "#2104: moving to the other workspace ends the page's shares")

# ---------------------------------------------------------------- organisation (tenant-matrix: wiki)
hb = page(A, SP, "Docs/Handbook", "For the customer.")
r = share(A, page_id=hb, kind="person", email="dave@example.com")
check(r.status_code == 409 and r.json().get("code") == "wiki_share_org", "#2104: no person share in an organisation " + r.text[:200])
r = A.get(B + "/api/wiki/shares", params={"page": hb})
check(r.ok and r.json().get("person") is False, "#2104: the dialog knows: no person shares here")
r = share(Bo, page_id=hb, kind="link")
check(r.status_code == 201, "#2104: a member makes a link of the organisation's page " + r.text[:200])
ol = r.json()
otok = ol.get("url", "").rsplit("/", 1)[-1]
check(anon(f"/s/w/{otok}").ok and "For the customer." in anon(f"/s/w/{otok}").text, "#2104: the organisation's page through the link")
for what, rr in (("list", Ca.get(B + "/api/wiki/shares", params={"page": hb})), ("create", share(Ca, page_id=hb, kind="link")),
                 ("folder", share(Ca, space=SP, folder="Docs", kind="link")), ("change", Ca.patch(B + f"/api/wiki/shares/{ol['id']}", json={"expires": None})),
                 ("revoke", Ca.delete(B + f"/api/wiki/shares/{ol['id']}")), ("restore", Ca.post(B + f"/api/wiki/shares/{ol['id']}/restore")),
                 ("private page", share(Ca, page_id=secret, kind="link")), ("private share", Ca.delete(B + f"/api/wiki/shares/{pshare}")),
                 ("guest page", Ca.get(B + f"/api/wiki/shared/pages/{hb}"))):
    check(rr.status_code == 404, f"#2104: another organisation / person: 404 ({what}) {rr.status_code}")
check(anon(f"/s/w/{otok}").ok, "#2104: the link still works after the foreign attempts")
r = A.delete(B + f"/api/wiki/shares/{ol['id']}")
check(r.ok and anon(f"/s/w/{otok}").status_code == 404, "#2104: the organisation's admin revokes a member's link")
A.post(B + f"/api/wiki/shares/{ol['id']}/restore")
# a locked space (encrypted in the browser)
FID, Fr = freelancer(B, A)
fp = page(Fr, "private", "Offer/Terms", "Terms for the customer.")
r = share(Fr, page_id=fp, kind="link")
check(r.status_code == 201, "#2104: a person without an organisation shares a page by link (freelancer-matrix: wiki) " + r.text[:200])
ftok = r.json().get("url", "").rsplit("/", 1)[-1]
r = share(Fr, space="private", folder="Offer", kind="person", email="dave@example.com")
check(r.ok and r.json().get("by_email") is True and "Offer/Terms" in shared(Da), "#2104: the freelancer shares a folder with a person " + r.text[:200])  # 2.123.0 (#2104, review): by e-mail = 200 by_email
r = Fr.get(B + "/api/wiki/shares", params={"space": "private"})
check(r.ok and len(r.json().get("shares", [])) == 2, "#2104: the freelancer lists the shares of the private space")
fsid = r.json()["shares"][0]["id"]
check(Fr.delete(B + f"/api/wiki/shares/{fsid}").ok and Fr.post(B + f"/api/wiki/shares/{fsid}/restore").ok, "#2104: the freelancer revokes and restores")
check(Fr.patch(B + f"/api/wiki/shares/{fsid}", json={"expires": time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400 * 3))}).ok,
      "#2104: the freelancer sets an expiry")
check(Fr.get(B + "/api/wiki/shared").ok and Fr.get(B + "/api/wiki/shared/pages/999999").status_code == 404, "#2104: the freelancer's own Shared with me")
sql("INSERT INTO wiki_spaces(owner_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (FID,), write=True)
r = share(Fr, page_id=fp, kind="link")
check(r.status_code == 409 and r.json().get("code") == "wiki_e2e_share", "#2104: a locked space shares nothing " + r.text[:200])
check(anon(f"/s/w/{ftok}").status_code == 404 and "Offer/Terms" not in shared(Da), "#2104: shares of a locked space stop serving")
r = Fr.get(B + "/api/wiki/shares", params={"space": "private"})
check(r.ok and r.json().get("locked") is True and r.json().get("shares") == [], "#2104: the dialog of a locked space: locked, no shares")
# tenancy: the nightly boundary check finds nothing
check(sql("SELECT COUNT(*) FROM wiki_shares s JOIN users u ON u.id=s.user_id WHERE s.kind='person' AND (s.org_id IS NOT NULL OR u.kind='agent')")[0][0] == 0,
      "#2104: no person share crosses a boundary")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
