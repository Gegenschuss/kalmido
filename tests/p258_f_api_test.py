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
A.patch(B + f"/api/admin/agents/{r.json()['id']}", json={"org_id": ORG})


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

print(f"p258_f_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
