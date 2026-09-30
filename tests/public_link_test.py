#!/usr/bin/env python3
"""Public list links (/s/<token>) and checklist mode: owner-only management (IDOR, roles, inbox), token entropy and
storage (SHA-256 lookup, sealed copy for the owner), the page (only that list: open tasks, subtasks, sections, recently
completed / every done item of a checklist; never comments, assignees, tags, files, fields or other lists; notes only
when switched on; titles escaped), headers (strict CSP, noindex, no-store, no-referrer), modes (view only / tick off),
ticking via the same completion code (history + News "via the public link", no completer for the statistics, webhooks
unaffected), password (hashed, unlock cookie bound to the password version, rate limit), expiry, revoke / regenerate, the
same 404 for unknown / expired / revoked / switched-off links, rate limits per address, the burst alert, the admin
switch and KALMIDO_PUBLIC_LINKS=0, disabled owners, and the checklist actions (uncheck all / clear done).
Starts its OWN test containers (start.sh).
usage: public_link_test.py <datadir>"""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
BP = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PROXY_PORT", "3041")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
T = date.today()


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def start(env=()):
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=" ".join(env)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def path_of(url):
    return url[url.index("/s/"):]


def page(p, **kw):
    return requests.get(B + p, allow_redirects=False, **kw)


def tick(p, tid, to="done", **kw):
    return requests.post(B + p + "/tick", data={"task": str(tid), "to": to}, allow_redirects=False, **kw)


# ================================================================== 1. KALMIDO_PUBLIC_LINKS=0
start(["-e KALMIDO_PUBLIC_LINKS=0"])
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "password": "password123"}).ok
A = sess("alice")
lid = A.post(B + "/api/lists", json={"name": "L"}).json()["id"]
check(A.get(B + "/api/state").json()["public_links"] is False, "env off: state")
check(A.put(B + f"/api/lists/{lid}/public-link", json={"mode": "view"}).status_code == 409, "env off: creating refused")
check(A.get(B + "/api/about").json()["public_links_env"] is False, "env off: shown to admins")
dbx("INSERT INTO public_links(list_id,token_hash,token,mode,created_at) VALUES(?,?,'x','view','2026')",
    (lid, hashlib.sha256(b"A" * 32).hexdigest()))
check(page("/s/" + "A" * 32).status_code == 404, "env off: stored links do not open")

# ================================================================== 2. main container
start(["-e KALMIDO_PUBLIC_RATE=100", "-e KALMIDO_PUBLIC_BURST=25", "-e KALMIDO_ADMIN_ALERTS=1", "-e KALMIDO_ADMIN_ALERT_WINDOW=3"])
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
for u in ("bob", "carol"):
    assert A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"}).ok
A.patch(B + "/api/users/1", json={"ntfy_topic": "admintopic"})
Bo, Ca = sess("bob"), sess("carol")
# 1.9.0: "completed by others" News are off by default; this suite checks them for bob
Bo.patch(B + "/api/settings", json={"news_kinds": "mention,assign,comment,unblock,share,status,complete"})
st = A.get(B + "/api/state").json()
check(st["public_links"] is True and A.get(B + "/api/about").json()["public_links"] is True, "state + about: public links on")
inbox = next(l["id"] for l in st["lists"] if l["is_inbox"])
L = A.post(B + "/api/lists", json={"name": "Weekend <b>trip</b>"}).json()["id"]
P = A.post(B + "/api/lists", json={"name": "Secret plans"}).json()["id"]
sec = A.post(B + "/api/sections", json={"list_id": L, "name": "Before"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": 2, "role": "edit"})
A.put(B + f"/api/lists/{L}/members", json={"user_id": 3, "role": "view"})
mk = lambda s, **b: s.post(B + "/api/tasks", json={"list_id": L, **b}).json()  # noqa: E731
t_open = mk(A, title="Book <script>alert(1)</script> hotel", content="Booking code 4711 <img src=x onerror=alert(1)>",
            due=str(T), tags=["privatetag"], assignee_id=2, section_id=sec)
t_sub = A.post(B + "/api/tasks", json={"parent_id": t_open["id"], "title": "Compare prices"}).json()
t_bob = mk(Bo, title="Pack the tent")
t_done = mk(A, title="Buy tickets")
A.post(B + f"/api/tasks/{t_done['id']}/complete", json={})
t_old = mk(A, title="Old finished thing")
A.post(B + f"/api/tasks/{t_old['id']}/complete", json={})
dbx("UPDATE tasks SET completed_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds"), t_old["id"]))
t_trash = mk(A, title="Trashed idea")
A.delete(B + f"/api/tasks/{t_trash['id']}")
A.post(B + f"/api/tasks/{t_open['id']}/comments", json={"body": "comment text xyz"})
A.post(B + f"/api/tasks/{t_open['id']}/attachments", files={"file": ("receipt-file.txt", b"hello", "text/plain")})
pt = A.post(B + "/api/tasks", json={"list_id": P, "title": "Surprise party"}).json()

# ---- management: owner only
check(Bo.put(B + f"/api/lists/{L}/public-link", json={"mode": "view"}).status_code == 403, "edit member cannot create a link")
check(Ca.put(B + f"/api/lists/{L}/public-link", json={"mode": "view"}).status_code == 403, "view member cannot create a link")
check(Bo.get(B + f"/api/lists/{L}/public-link").status_code == 403 and Bo.get(B + f"/api/lists/{P}/public-link").status_code == 404,
      "members / strangers cannot read the link")
check(Bo.put(B + f"/api/lists/{P}/public-link", json={}).status_code == 404, "IDOR: foreign private list 404")
check(A.put(B + f"/api/lists/{inbox}/public-link", json={}).status_code == 400, "the inbox cannot be shared publicly")
check(A.put(B + f"/api/lists/{L}/public-link", json={}, headers={"X-Requested-With": ""}).status_code == 403, "CSRF header needed")
check(A.get(B + f"/api/lists/{L}/public-link").json() == {"enabled": True, "link": None}, "no link yet")
for bad, what in (({"mode": "edit"}, "mode"), ({"notes": "yes"}, "notes"), ({"expires": "2020-01-01"}, "expiry in the past"),
                  ({"expires": "tomorrow"}, "expiry format"), ({"password": "abc"}, "password too short"), ({"password": 1234}, "password type")):
    check(A.put(B + f"/api/lists/{L}/public-link", json=bad).status_code == 400, "validation: " + what)
check(not dbx("SELECT 1 FROM public_links"), "nothing stored after invalid input")
r = A.put(B + f"/api/lists/{L}/public-link", json={"mode": "view"})
k = r.json()["link"]
tokn = k["url"].rsplit("/", 1)[1]
check(r.ok and k["mode"] == "view" and not k["has_password"] and not k["notes"] and k["expires_at"] is None and k["url"].startswith("https://kalmido.example/s/"),
      "link created " + str(k))
check(re.fullmatch(r"[A-Za-z0-9_-]{32,}", tokn) and len(tokn) * 6 >= 128, f"token: {len(tokn) * 6} bits")
row = dbx("SELECT token_hash, token FROM public_links WHERE list_id=?", (L,))[0]
check(row[0] == hashlib.sha256(tokn.encode()).hexdigest() and tokn not in row[1], "stored: SHA-256 lookup + sealed copy")
check(A.get(B + f"/api/lists/{L}/public-link").json()["link"]["url"] == k["url"], "owner can copy the link again")
toks = {A.put(B + f"/api/lists/{P}/public-link", json={}).json()["link"]["url"]} | {k["url"]}
check(len(toks) == 2, "every list its own token")
PP = path_of(k["url"])

# ---- the page
r = page(PP)
h = r.text
check(r.status_code == 200 and r.headers["Content-Type"].startswith("text/html"), "page opens without login")
csp = r.headers.get("Content-Security-Policy", "")
check("default-src 'none'" in csp and "script-src" not in csp and "frame-ancestors 'none'" in csp and "form-action 'self'" in csp, "strict CSP " + csp)
check(r.headers.get("X-Robots-Tag", "").startswith("noindex") and 'name="robots" content="noindex' in h, "noindex (header + meta)")
check("no-store" in r.headers.get("Cache-Control", "") and r.headers.get("Referrer-Policy") == "no-referrer", "no-store + no-referrer")
check("<script" not in h.replace("&lt;script", "") and "&lt;script&gt;alert(1)&lt;/script&gt;" in h and "Weekend &lt;b&gt;trip&lt;/b&gt;" in h, "titles escaped (XSS)")
check("Compare prices" in h and "Pack the tent" in h and "Before" in h, "open tasks, subtasks, sections")
check("Buy tickets" in h and "Recently completed" in h and "Old finished thing" not in h and "Trashed idea" not in h, "recently completed only; no trash")
for leak, what in (("Booking code", "notes (off)"), ("comment text xyz", "comments"), ("privatetag", "tags"), ("Bob", "assignee"),
                   ("receipt-file", "attachments"), ("Surprise party", "other lists"), ("Secret plans", "other list names"), ("Alice", "owner name")):
    check(leak not in h, "no leak: " + what)
check('<form' not in h and 'class="chk' in h, "view only: no forms")
check(tick(PP, t_bob["id"]).status_code == 403 and dbx("SELECT status FROM tasks WHERE id=?", (t_bob["id"],))[0][0] == 0, "view only: ticking refused")
r = page(PP, headers={"Accept-Language": "de-DE,de;q=0.9"})
check("Kürzlich erledigt" in r.text and 'lang="de"' in r.text, "page in the browser's language")
check(page(PP, headers={"Remote-User": "alice"}).text.count("Secret plans") == 0, "a proxy header changes nothing")
check(requests.get(BP + PP, headers={"Remote-User": "alice"}).status_code == 200, "proxy port: same public page")
# notes on
A.put(B + f"/api/lists/{L}/public-link", json={"notes": True})
h = page(PP).text
check("Booking code 4711 &lt;img src=x onerror=alert(1)&gt;" in h and "<img" not in h, "notes on: shown as escaped plain text")
check(dbx("SELECT token_hash FROM public_links WHERE list_id=?", (L,))[0][0] == row[0], "changing settings keeps the token")

# ---- tick off
A.put(B + f"/api/lists/{L}/public-link", json={"mode": "tick"})
h = page(PP).text
check(h.count("<form") >= 4 and f'name="task" value="{t_bob["id"]}"' in h, "tick mode: a form per task")
r = tick(PP, t_bob["id"])
check(r.status_code == 303 and r.headers["Location"] == PP + f"#t{t_bob['id']}", "tick: 303 back to the page")
row = dbx("SELECT status, completed_by, completed_at FROM tasks WHERE id=?", (t_bob["id"],))[0]
check(row[0] == 2 and row[1] is None and row[2], "ticked: done, no completer (statistics)")
act = dbx("SELECT kind, user_id, data FROM activity WHERE task_id=? ORDER BY id DESC LIMIT 1", (t_bob["id"],))[0]
check(act[0] == "complete" and act[1] is None and json.loads(act[2]).get("via") == "public_link", "history: via the public link " + str(act))
nw = dbx("SELECT user_id, kind, actor_id, data FROM notifications WHERE task_id=?", (t_bob["id"],))
check(nw and nw[0][0] == 2 and nw[0][1] == "complete" and nw[0][2] is None and json.loads(nw[0][3]).get("via") == "public_link",
      "News for the creator (bob): completed via the public link " + str(nw))
news = Bo.get(B + "/api/news").json()["items"]
check(news and news[0]["kind"] == "complete" and news[0]["data"].get("via") == "public_link", "bob's News shows it")
tl = Bo.get(B + f"/api/tasks/{t_bob['id']}/timeline").json()
check(any(a["kind"] == "complete" and a["data"].get("via") == "public_link" for a in tl["activity"]), "timeline shows it")
r = tick(PP, t_bob["id"], "open")
check(r.status_code == 303 and dbx("SELECT status, completed_at FROM tasks WHERE id=?", (t_bob["id"],))[0] == (0, None), "put back on the list")
check(tick(PP, pt["id"]).status_code == 404 and dbx("SELECT status FROM tasks WHERE id=?", (pt["id"],))[0][0] == 0, "tick a task of another list: 404, unchanged")
check(tick(PP, t_trash["id"]).status_code == 404, "tick a trashed task: 404")
check(tick(PP, t_old["id"], "open").status_code == 404, "an old completion (not on the page) cannot be reopened")
check(tick(PP, t_bob["id"], "delete").status_code == 404 and tick(PP, "x").status_code == 404, "tick: bad input")
r = tick(PP, t_bob["id"], headers={"Sec-Fetch-Site": "cross-site"})
check(r.status_code == 403 and dbx("SELECT status FROM tasks WHERE id=?", (t_bob["id"],))[0][0] == 0, "cross-site form post refused")
r = requests.post(B + PP + "/tick", data={"task": str(t_bob["id"]), "to": "done", "title": "hacked"}, allow_redirects=False)
check(dbx("SELECT title FROM tasks WHERE id=?", (t_bob["id"],))[0][0] == "Pack the tent", "tick changes nothing else")
tick(PP, t_bob["id"], "open")
check(requests.post(B + PP, data={}).status_code in (404, 405), "no other methods on the page")

# ---- password
r = A.put(B + f"/api/lists/{L}/public-link", json={"password": "sesame123"})
check(r.json()["link"]["has_password"], "password set")
pw_hash = dbx("SELECT password_hash FROM public_links WHERE list_id=?", (L,))[0][0]
check(pw_hash and "sesame123" not in pw_hash, "password stored hashed")
r = page(PP)
check(r.status_code == 200 and 'type="password"' in r.text and "Pack the tent" not in r.text and "Weekend" not in r.text, "locked page: form, no list data")
check(tick(PP, t_bob["id"]).status_code == 303 and dbx("SELECT status FROM tasks WHERE id=?", (t_bob["id"],))[0][0] == 0, "locked: ticking does nothing")
r = requests.post(B + PP + "/unlock", data={"password": "wrong"}, allow_redirects=False)
check(r.status_code == 401 and "Wrong password" in r.text and not r.cookies, "wrong password: 401, no cookie")
s = requests.Session()
r = s.post(B + PP + "/unlock", data={"password": "sesame123"}, allow_redirects=False)
ck = r.headers.get("Set-Cookie", "")
check(r.status_code == 303 and "HttpOnly" in ck and "SameSite=Strict" in ck and f"Path={PP}" in ck, "unlock: cookie (HttpOnly, Strict, path) " + ck)
check("Pack the tent" in s.get(B + PP).text, "unlocked: the list shows")
check("Pack the tent" not in page(PP.replace(tokn, tokn), cookies={}).text, "other browsers stay locked")
r = s.post(B + PP + "/tick", data={"task": str(t_bob["id"]), "to": "done"}, allow_redirects=False)
check(r.status_code == 303 and dbx("SELECT status FROM tasks WHERE id=?", (t_bob["id"],))[0][0] == 2, "unlocked: ticking works")
s.post(B + PP + "/tick", data={"task": str(t_bob["id"]), "to": "open"})
A.put(B + f"/api/lists/{L}/public-link", json={"password": "another1"})
check('type="password"' in s.get(B + PP).text, "new password: the old unlock cookie stops working")
forged = requests.Session()
forged.cookies.set("kalmido_pub1", "0" * 64, path=PP)
check('type="password"' in forged.get(B + PP).text, "forged cookie refused")
A.put(B + f"/api/lists/{L}/public-link", json={"password": ""})
check("Pack the tent" in page(PP).text, "password removed: open again")
A.put(B + f"/api/lists/{L}/public-link", json={"password": "sesame123"})
codes = [requests.post(B + PP + "/unlock", data={"password": f"guess{i}"}, allow_redirects=False).status_code for i in range(11)]
check(codes.index(429) == 9 and set(codes[9:]) == {429}, "password guessing: 10 per address (incl. the earlier one), then 429 " + str(codes))
r = requests.post(B + PP + "/unlock", data={"password": "sesame123"}, allow_redirects=False)
check(r.status_code == 429, "blocked even with the right password (15 min)")
A.put(B + f"/api/lists/{L}/public-link", json={"password": ""})

# ---- expiry, revoke, regenerate, disabled owner, admin switch
r = A.put(B + f"/api/lists/{L}/public-link", json={"expires": str(T)})
check(r.ok and r.json()["link"]["expires_at"] and page(PP).status_code == 200, "expires end of today: still open")
gone = page("/s/" + "Q" * 32).text
dbx("UPDATE public_links SET expires_at=? WHERE list_id=?", ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds"), L))
r = page(PP)
check(r.status_code == 404 and r.text == gone, "expired: the same 404 as an unknown link")
check(A.get(B + f"/api/lists/{L}/public-link").json()["link"]["expired"] is True, "owner sees 'expired'")
A.put(B + f"/api/lists/{L}/public-link", json={"expires": None})
check(page(PP).status_code == 200, "expiry removed")
r = A.post(B + f"/api/lists/{L}/public-link/regenerate")
NP = path_of(r.json()["link"]["url"])
check(r.ok and NP != PP and page(PP).status_code == 404 and page(NP).status_code == 200, "regenerate: old 404, new works")
check(Bo.post(B + f"/api/lists/{L}/public-link/regenerate").status_code == 403, "regenerate: owner only")
A.patch(B + "/api/admin/settings", json={"public_links": False})
r = page(NP)
check(r.status_code == 404 and r.text == gone, "admin switch off: 404")
check(A.put(B + f"/api/lists/{L}/public-link", json={}).status_code == 409 and A.get(B + "/api/state").json()["public_links"] is False, "switch off: no new links")
A.patch(B + "/api/admin/settings", json={"public_links": True})
check(page(NP).status_code == 200, "switch on again: the link works again (kept)")
time.sleep(1.5)
check(any("Public links to lists" in m for (m,) in dbx("SELECT message FROM admin_alerts WHERE kind='security'")), "switch change: security alert")
check(Bo.delete(B + f"/api/lists/{L}/public-link").status_code == 403, "revoke: owner only")
r = A.delete(B + f"/api/lists/{L}/public-link")
check(r.ok and r.json()["link"] is None and page(NP).status_code == 404 and not dbx("SELECT 1 FROM public_links WHERE list_id=?", (L,)), "revoked")
cl = Ca.post(B + "/api/lists", json={"name": "Carol list"}).json()["id"]
Ca.post(B + "/api/tasks", json={"list_id": cl, "title": "carol task"})
cp = path_of(Ca.put(B + f"/api/lists/{cl}/public-link", json={}).json()["link"]["url"])
check("carol task" in page(cp).text, "carol's link works")
A.patch(B + "/api/users/3", json={"disabled": True})
check(page(cp).status_code == 404, "owner disabled: 404")
A.patch(B + "/api/users/3", json={"disabled": False})
check(page(cp).status_code == 200, "owner enabled again: works")
Ca = sess("carol")
Ca.patch(B + f"/api/lists/{cl}", json={"archived": 1})  # 1.5: deleting for good only from the archive
check(Ca.delete(B + f"/api/lists/{cl}").ok and not dbx("SELECT 1 FROM public_links WHERE list_id=?", (cl,)) and page(cp).status_code == 404,
      "list deleted: link gone (cascade)")

# ---- checklist mode
C = A.post(B + "/api/lists", json={"name": "Groceries", "checklist": True}).json()
check(C["checklist"] == 1, "list created in checklist mode")
items = [A.post(B + "/api/tasks", json={"list_id": C["id"], "title": n}).json()["id"] for n in ("Milk", "Bread", "Eggs", "Apples")]
for i in items[:3]:
    A.post(B + f"/api/tasks/{i}/complete", json={})
dbx("UPDATE tasks SET completed_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds"), items[0]))
stt = A.get(B + "/api/state").json()
check({t["id"] for t in stt["tasks"] if t["list_id"] == C["id"]} == set(items), "state: every done item of a checklist (also old ones)")
check(t_old["id"] not in {t["id"] for t in stt["tasks"]}, "normal lists: old completions still left out")
cpath = path_of(A.put(B + f"/api/lists/{C['id']}/public-link", json={"mode": "tick"}).json()["link"]["url"])
h = page(cpath).text
check("Milk" in h and "<details class=\"donegrp\" open>" in h and ">Done <" in h, "public page of a checklist: all done items, section open")
check(A.patch(B + f"/api/lists/{C['id']}", json={"checklist": False}).ok and dbx("SELECT checklist FROM lists WHERE id=?", (C["id"],))[0][0] == 0, "checklist off")
check(Bo.patch(B + f"/api/lists/{L}", json={"checklist": True}).status_code == 403, "checklist: owner only")
A.patch(B + f"/api/lists/{C['id']}", json={"checklist": True})
check(Ca.post(B + f"/api/lists/{C['id']}/checklist", json={"action": "uncheck_all"}).status_code == 404, "checklist action: IDOR")
A.put(B + f"/api/lists/{C['id']}/members", json={"user_id": 3, "role": "view"})
check(Ca.post(B + f"/api/lists/{C['id']}/checklist", json={"action": "uncheck_all"}).status_code == 403, "checklist action: view only 403")
check(A.post(B + f"/api/lists/{C['id']}/checklist", json={"action": "nuke"}).status_code == 400, "checklist action: validation")
r = A.post(B + f"/api/lists/{C['id']}/checklist", json={"action": "uncheck_all"})
check(r.json()["count"] == 3 and all(s == 0 for (s,) in dbx("SELECT status FROM tasks WHERE list_id=?", (C["id"],))), "uncheck all")
check(dbx("SELECT COUNT(*) FROM activity WHERE kind='reopen' AND task_id IN (?,?,?)", tuple(items[:3]))[0][0] == 3, "uncheck all: history lines")
for i in items[1:3]:
    A.post(B + f"/api/tasks/{i}/complete", json={})
r = A.post(B + f"/api/lists/{C['id']}/checklist", json={"action": "clear_done"})
check(r.json()["count"] == 2 and dbx("SELECT COUNT(*) FROM tasks WHERE list_id=? AND deleted_at IS NOT NULL", (C["id"],))[0][0] == 2, "clear done: to the trash")

# ---- rate limits and the burst alert (last: they block this address)
views = [page(cpath).status_code for _ in range(105)]
check(views.count(200) <= 100 and views[-1] == 429, f"page views per address: {views.count(200)} ok, then 429")
time.sleep(5)
al = dbx("SELECT message FROM admin_alerts WHERE kind='security'")
check(any("public link of list" in m and str(C["id"]) in m for (m,) in al), "burst alert for one link " + str(al)[-300:])
check(not any("Groceries" in m or cpath in m for (m,) in al), "the alert names no list name / token")
time.sleep(61)
bad = [page(f"/s/{'R' * 31}{i}").status_code for i in range(10)] + [page(f"/s/{'S' * 32}").status_code for _ in range(25)]
check(bad.count(404) <= 30 and bad[-1] == 429, f"unknown links: at most 30 per address, then 429 ({bad.count(404)} x 404)")
check(page(cpath).status_code == 429, "then blocked for valid links too")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
