#!/usr/bin/env python3
"""2.58.0 API tests, part F (#1803, #1804, #1805). Invented names only.
 - #1803 a job's own name: POST /api/v1/agent/jobs {name} is shown as the job's name; without it the "Name: " start of the
   title is the fallback, but ordinary words ("Release: 2.56", "Fix: Login") are no name; a name with digits, a colon, a
   plain word or too long = 400; PATCH cannot set it
 - #1804 an organisation admin who sets a picture and changes the name in one go: the owner gets ONE news item
 - #1805 a list's own picture in an organisation with encryption is sealed on disk (private lists stay plain); a plain
   picture from before is still served and sealed by the encryption pass; the picture is served decrypted
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY.
usage: p258_f_api_test.py <datadir>"""
import base64
import os
import struct
import subprocess
import sys
import time
import zlib

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def png(w=4, h=4):
    """A tiny valid PNG (red square), no image library needed."""
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def icon_file(lid):
    v = dbx("SELECT icon FROM lists WHERE id=?", (lid,))[0][0] or ""
    return os.path.join(DATA, "attachments", "listicons", f"l{lid}-{v[2:]}.png"), v


def head(p):
    with open(p, "rb") as f:
        return f.read(6)


env = dict(os.environ, EXTRA="-e KALMIDO_SECRET_KEY=" + KEY)
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en"})
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=(SELECT id FROM users WHERE username='alice')", (ORG,), write=True)

# ================================================================== #1803 the job's own name
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
AG = {"Authorization": "Bearer " + r.json()["token"]}
AID = r.json()["id"]
A.patch(B + f"/api/admin/agents/{AID}", json={"org_id": ORG})
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": AID, "role": "edit"}).ok, "setup: claude in alice's list")


def job(body):
    return requests.post(V + "/agent/jobs", headers=AG, json=body)


r = job({"title": "Release 2.50", "name": "Clara", "user_id": 1})
check(r.status_code == 201 and r.json().get("name") == "Clara" and r.json().get("title") == "Release 2.50", "#1803: the own name " + r.text[:200])
JN = r.json().get("id")
r = job({"title": "Part A", "name": "  Frida   B ", "user_id": 1})
check(r.status_code == 201 and r.json().get("name") == "Frida B", "#1803: the name is trimmed (spaces joined) " + r.text[:200])
check(dbx("SELECT name FROM agent_jobs WHERE id=?", (r.json().get("id"),))[0][0] == "Frida B", "#1803: stored in agent_jobs.name")
for t, want in (("Release: 2.56", None), ("Fix: Login", None), ("Clara: Release 2.50", "Clara"), ("Frida B: Part A", "Frida B"),
                ("release notes", None), ("Bugfix: x", None), ("Fehler: Anmeldung", None)):
    r = job({"title": t})
    check(r.status_code == 201 and r.json().get("name") == want, f"#1803: title {t!r} -> name {want!r}: {r.text[:200]}")
r = job({"title": "Release 2.50", "name": None})
check(r.status_code == 201 and r.json().get("name") is None, "#1803: name null = none")
r = job({"title": "Fix: Login", "name": ""})
check(r.status_code == 201 and r.json().get("name") is None, "#1803: an empty name = none, and the title gives none either")
for bad in ("Job 5", "a:b", "Clara2", "Release", "fix", "x" * 25, 5, ["Clara"], "-Clara", "Cla\x00ra"):
    r = job({"title": "T", "name": bad})
    check(r.status_code == 400, f"#1803: name {bad!r} -> 400 ({r.status_code})")
r = requests.patch(V + f"/agent/jobs/{JN}", headers=AG, json={"name": "Other"})
check(r.status_code == 400 and dbx("SELECT name FROM agent_jobs WHERE id=?", (JN,))[0][0] == "Clara", "#1803: PATCH cannot set the name " + str(r.status_code))
r = requests.get(V + "/agent/jobs", headers=AG)
check(r.ok and any(j["id"] == JN and j.get("name") == "Clara" for j in r.json()["data"]), "#1803: the list carries the name")
r = A.get(B + "/api/agents/jobs?state=all")
check(r.ok and any(j["id"] == JN and j.get("name") == "Clara" for j in r.json()["jobs"]), "#1803: the person's job list carries it")

# ================================================================== #1805 sealed list pictures
TEAM = Bo.post(B + "/api/lists", json={"name": "Team", "org_id": ORG}).json()["id"]
PRIV = Bo.post(B + "/api/lists", json={"name": "Private", "org_id": None}).json()["id"]
check(A.put(B + "/api/admin/orgcrypt", json={"org_encrypt": False}).ok, "setup: encryption off for a while")
r = Bo.post(B + f"/api/lists/{TEAM}/icon", files={"file": ("i.png", png(), "image/png")}, headers=H)
check(r.ok, "#1805: a picture while the encryption is off " + r.text[:160])
p_old, v_old = icon_file(TEAM)
check(os.path.isfile(p_old) and head(p_old) == b"\x89PNG\r\n", "#1805: stored plain while off (the state before 2.58)")
url = r.json().get("icon", "") if r.ok else ""
r = Bo.get(B + url)
check(r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n", "#1805: a plain picture is served as before")
check(A.put(B + "/api/admin/orgcrypt", json={"org_encrypt": True}).ok, "setup: encryption on again")
for _ in range(60):  # the encryption pass runs in the background
    if head(p_old) == b"KENC1\n":
        break
    time.sleep(0.5)
check(head(p_old) == b"KENC1\n", "#1805: the encryption pass seals the older picture too")
r = Bo.get(B + url)
check(r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n", "#1805: ... and it is still served decrypted")
r = Bo.post(B + f"/api/lists/{TEAM}/icon", files={"file": ("i.png", png(6, 6), "image/png")}, headers=H)
check(r.ok, "#1805: a new picture " + r.text[:160])
p_new, _v = icon_file(TEAM)
check(p_new != p_old and head(p_new) == b"KENC1\n" and not os.path.exists(p_old), "#1805: the new picture is sealed, the old file gone")
r = Bo.get(B + r.json().get("icon", ""))
check(r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n" and r.headers.get("Content-Type", "").startswith("image/png"),
      "#1805: the sealed picture is served as a PNG")
r = Bo.post(B + f"/api/lists/{PRIV}/icon", files={"file": ("i.png", png(), "image/png")}, headers=H)
pp, _v = icon_file(PRIV)
check(r.ok and head(pp) == b"\x89PNG\r\n" and Bo.get(B + r.json()["icon"]).status_code == 200, "#1805: a private list's picture stays plain (as attachments)")
base = f"/api/orgs/{ORG}/lists/{TEAM}"
r = A.post(B + base + "/icon", files={"file": ("i.png", png(5, 5), "image/png")}, headers=H)
pa, _v = icon_file(TEAM)
check(r.ok and head(pa) == b"KENC1\n", "#1805: the organisation admin's way seals as well " + r.text[:160])
check(A.get(B + r.json().get("icon", "")).status_code == 200 if r.ok else False, "#1805: the admin sees it decrypted")

# ================================================================== #1804 one news item for picture + name
A.delete(B + base + "/icon")
LIST2 = Bo.post(B + "/api/lists", json={"name": "\U0001F680 Rockets", "org_id": ORG}).json()["id"]
b2 = f"/api/orgs/{ORG}/lists/{LIST2}"


def news2():
    return [x.get("data") or {} for x in Bo.get(B + "/api/news").json().get("items", []) if x["kind"] == "orglist" and x.get("list_id") == LIST2]


check(A.post(B + b2 + "/icon", files={"file": ("i.png", png(), "image/png")}, headers=H).ok, "#1804: the admin sets a picture")
check(A.patch(B + b2, json={"name": "Rockets"}).ok, "#1804: ... and the emoji leaves the name")
n = news2()
check(len(n) == 1 and n[0].get("action") == "rename" and n[0].get("old") == "\U0001F680 Rockets" and n[0].get("name") == "Rockets",
      f"#1804: the owner gets one item (rename, old -> new): {n}")
check(A.patch(B + b2, json={"color": "#f87171"}).ok and len(news2()) == 1, "#1804: a colour change right after joins it too")
check(A.patch(B + b2, json={"name": "Rockets two"}).ok, "#1804: a second rename")
n = news2()
check(len(n) == 1 and n[0].get("old") == "\U0001F680 Rockets" and n[0].get("name") == "Rockets two", f"#1804: still one, from the first name: {n}")
Bo.post(B + "/api/news/read", json={"all": True})
check(A.patch(B + b2, json={"color": "#6d8cff"}).ok, "#1804: a change after the owner read it")
check(len(news2()) == 2, "#1804: ... is a new item " + str(news2()))

print(f"p258_f_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
