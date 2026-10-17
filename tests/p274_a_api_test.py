#!/usr/bin/env python3
"""2.74.0 API tests, part A (#338): the supporter licence (self-hosted only, unlocks nothing). Invented names only.
 - tools/supporter_key.py: genkey (mode 600, refuses a path in the repository, never overwrites), pubkey, sign, verify
 - a test key pair in a temp folder; its public key is trusted through KALMIDO_SUPPORTER_EXTRA_PUBKEYS
 - PUT /api/supporter/server (admins) + /person (every person for themself): a valid key -> the badge info {kind, date, id};
   tampered / broken / unknown signer / too long -> 400, nothing stored; the other kind -> 400; a member -> 403 for the
   server licence; DELETE + POST .../swap (undo / redo); the raw key never in /api/about, /api/supporter, /api/state,
   /api/export.json; agents 403
 - the yearly hint: admins only, not in the first 30 days, not with a licence, switchable off, "seen" = a year quiet
 - KALMIDO_SUPPORT_URL: only https
 - a hosted server: every route 404 and /api/about without the fields
usage: p274_a_api_test.py <datadir>"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import dbx as dbxm  # noqa: E402
import supporter_key as SK  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
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


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        return r.fetchall() if q.lstrip().upper().startswith("SELECT") else None
    finally:
        c.close()


def tool(*a):
    return subprocess.run([sys.executable, os.path.join(ROOT, "tools", "supporter_key.py"), *a], capture_output=True, text=True)


# ---- the key tool (a temp folder outside the repository)
TMP = tempfile.mkdtemp(prefix="p274a-")
KF = os.path.join(TMP, "test-signing.key")
r = tool("genkey", "--out", KF)
PUB = r.stdout.strip()
check(r.returncode == 0 and len(base64.b64decode(PUB)) == 32, f"genkey prints a 32-byte public key ({r.stderr[:200]})")
check(oct(os.stat(KF).st_mode & 0o777) == "0o600", "genkey: the private key file has mode 600")
check("PRIVATE KEY" not in r.stdout, "genkey prints only the public key")
r = tool("genkey", "--out", KF)
check(r.returncode != 0 and "exists" in r.stderr, "genkey never overwrites")
r = tool("genkey", "--out", os.path.join(ROOT, "tools", "x.key"))
check(r.returncode != 0 and not os.path.exists(os.path.join(ROOT, "tools", "x.key")), "genkey refuses a path inside the repository")
check(tool("pubkey", "--key", KF).stdout.strip() == PUB, "pubkey derives the same public key")
SRV = tool("sign", "--key", KF, "--type", "server", "--id", "srv-1", "--date", "2026-10-01").stdout.strip()
PER = tool("sign", "--key", KF, "--type", "person", "--id", "p-1", "--date", "2026-10-02").stdout.strip()
PER2 = tool("sign", "--key", KF, "--type", "person", "--id", "p-2").stdout.strip()
check(SRV.startswith("KSUP1.") and SRV.count(".") == 2, "sign prints KSUP1.<data>.<signature>")
r = tool("verify", "--pub", PUB, SRV)
check(r.returncode == 0 and json.loads(r.stdout) == {"t": "server", "d": "2026-10-01", "id": "srv-1"}, "verify: content")
check(tool("sign", "--key", KF, "--type", "server", "--id", "bad id!").returncode != 0, "sign: a label with spaces is refused")
# a second, untrusted signer and tampered keys
KF2 = os.path.join(TMP, "other.key")
tool("genkey", "--out", KF2)
OTHER = tool("sign", "--key", KF2, "--type", "server").stdout.strip()
check(tool("verify", "--pub", PUB, OTHER).returncode != 0, "verify: another signer is refused")
p = SRV.split(".")
FORGED = p[0] + "." + SK.b64u(json.dumps({"t": "server", "d": "2026-10-01", "id": "srv-9"}).encode()) + "." + p[2]
SWITCHED = p[0] + "." + SK.b64u(json.dumps({"t": "person", "d": "2026-10-01", "id": "srv-1"}, separators=(",", ":")).encode()) + "." + p[2]
BROKEN = SRV[:-4] + ("AAAA" if not SRV.endswith("AAAA") else "BBBB")

# ---- the server: the test key trusted through the environment
BASE = os.environ.get("EXTRA", "")
EXTRA = BASE + f" -e KALMIDO_SUPPORTER_EXTRA_PUBKEYS={PUB} -e KALMIDO_SUPPORT_URL=https://pay.example.com/kalmido"
env = dict(os.environ, EXTRA=EXTRA)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")

j = A.get(B + "/api/about").json()
check(j.get("supporter") is None and j.get("supporter_me") is None, "about: no licence yet")
check(j.get("support_url") == "https://pay.example.com/kalmido", "about: the payment link")
check(j.get("sup_nudge") is False, "a new server: no hint in the first 30 days")
jb = Bo.get(B + "/api/about").json()
check("support_url" in jb and "sup_nudge" not in jb and "sup_nudge_on" not in jb, "a member: no hint fields at all")

# ---- server licence
for bad, what in ((FORGED, "changed content"), (SWITCHED, "changed kind"), (BROKEN, "broken signature"), (OTHER, "unknown signer"),
                  ("KSUP1.abc", "two parts"), ("hello", "no key"), ("KSUP1." + "A" * 900 + ".B", "too long"), ("", "empty")):
    r = A.put(B + "/api/supporter/server", json={"key": bad})
    check(r.status_code == 400 and bad[:40] not in r.text or (bad == "" and r.status_code == 400), f"server licence: {what} -> 400 ({r.status_code})")
check(A.put(B + "/api/supporter/server", json={"key": 123}).status_code == 400, "a number -> 400")
check(A.get(B + "/api/about").json().get("supporter") is None, "nothing stored after the wrong keys")
r = A.put(B + "/api/supporter/server", json={"key": PER})
check(r.status_code == 400 and "personal" in r.json().get("error", ""), f"a personal key is no server licence ({r.status_code})")
r = Bo.put(B + "/api/supporter/server", json={"key": SRV})
check(r.status_code == 403, f"a member cannot enter the server licence ({r.status_code})")
r = A.put(B + "/api/supporter/server", json={"key": SRV[:30] + "\n" + SRV[30:] + "  "})
check(r.ok and r.json().get("supporter") == {"kind": "server", "date": "2026-10-01", "id": "srv-1"}, f"the admin enters it (line breaks ignored) ({r.text[:200]})")
check(SRV not in r.text and p[2] not in r.text, "the answer has no raw key")
jb = Bo.get(B + "/api/about").json()
check(jb.get("supporter", {}).get("kind") == "server", "a member sees the server licence badge")
check(Bo.delete(B + "/api/supporter/server").status_code == 403, "a member cannot remove it")
check(Bo.post(B + "/api/supporter/server/swap").status_code == 403, "a member cannot swap it")
check(A.put(B + "/api/supporter/other", json={"key": SRV}).status_code == 404, "an unknown kind -> 404")

# ---- personal licence (each for themself)
r = Bo.put(B + "/api/supporter/person", json={"key": SRV})
check(r.status_code == 400 and "server licence" in r.json().get("error", ""), "a server key is no personal licence")
r = Bo.put(B + "/api/supporter/person", json={"key": PER})
check(r.ok and r.json().get("supporter_me", {}).get("id") == "p-1", f"bob enters his personal licence ({r.text[:200]})")
check(A.get(B + "/api/about").json().get("supporter_me") is None, "alice's own licence stays empty")
for path in ("/api/about", "/api/supporter", "/api/state", "/api/export.json"):
    t = Bo.get(B + path).text
    check(PER.split(".")[2] not in t and SRV.split(".")[2] not in t, f"no raw key in {path}")
check("sup_key" not in json.dumps(Bo.get(B + "/api/state").json().get("settings", {})), "the state's settings leave the key out")
# replace, undo (swap) brings the old one back, redo the new one
r = Bo.put(B + "/api/supporter/person", json={"key": PER2})
check(r.json().get("supporter_me", {}).get("id") == "p-2", "a second personal key replaces the first")
r = Bo.post(B + "/api/supporter/person/swap")
check(r.ok and r.json().get("supporter_me", {}).get("id") == "p-1", "undo: the previous key is back")
r = Bo.post(B + "/api/supporter/person/swap")
check(r.json().get("supporter_me", {}).get("id") == "p-2", "redo: the new key again")
r = Bo.delete(B + "/api/supporter/person")
check(r.ok and r.json().get("supporter_me") is None, "remove")
r = Bo.post(B + "/api/supporter/person/swap")
check(r.json().get("supporter_me", {}).get("id") == "p-2", "undo of remove: back")
r = A.delete(B + "/api/supporter/server")
check(r.ok and r.json().get("supporter") is None, "the admin removes the server licence")
check(A.post(B + "/api/supporter/server/swap").json().get("supporter", {}).get("id") == "srv-1", "undo brings it back")
A.delete(B + "/api/supporter/server")

# ---- agents: none of it
r = A.post(B + "/api/admin/agents", json={"username": "supbot", "display_name": "Supbot"})
AGT = r.json().get("token") or ""
ag = requests.Session()
ag.headers.update({**H, "Authorization": "Bearer " + AGT})
check(ag.get(B + "/api/supporter").status_code in (401, 403, 404), "an agent: no supporter route")
check(ag.put(B + "/api/supporter/person", json={"key": PER}).status_code in (401, 403, 404), "an agent cannot enter a key")

# ---- the yearly hint (admins only)
sql("UPDATE users SET created_at='2025-01-01T00:00:00Z'")
check(A.get(B + "/api/about").json().get("sup_nudge") is True, "after 30 days without licence: the admin's hint is due")
check("sup_nudge" not in Bo.get(B + "/api/about").json(), "never for a member")
check(Bo.patch(B + "/api/supporter/nudge", json={"seen": True}).status_code == 403, "a member cannot touch the hint")
r = A.patch(B + "/api/supporter/nudge", json={"seen": True})
check(r.ok and r.json().get("sup_nudge") is False, "seen: quiet for a year")
sql("UPDATE user_settings SET value='2024-01-01' WHERE key='sup_nudge_at'")
check(A.get(B + "/api/about").json().get("sup_nudge") is True, "a year later: due again")
r = A.patch(B + "/api/supporter/nudge", json={"on": False})
check(r.ok and r.json().get("sup_nudge_on") is False and r.json().get("sup_nudge") is False, "switched off: never")
check(A.patch(B + "/api/supporter/nudge", json={"on": "no"}).status_code == 400, "on: a boolean")
A.patch(B + "/api/supporter/nudge", json={"on": True})
check(A.get(B + "/api/about").json().get("sup_nudge") is True, "on again: due")
A.put(B + "/api/supporter/person", json={"key": PER})
check(A.get(B + "/api/about").json().get("sup_nudge") is False, "with an own licence: no hint")
A.delete(B + "/api/supporter/person")
A.put(B + "/api/supporter/server", json={"key": SRV})
check(A.get(B + "/api/about").json().get("sup_nudge") is False, "with a server licence: no hint")

# ---- the payment link: https only
env2 = dict(os.environ, KEEP="1", EXTRA=BASE + f" -e KALMIDO_SUPPORTER_EXTRA_PUBKEYS={PUB} -e KALMIDO_SUPPORT_URL=http://pay.example.com/x")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env2)
A = sess("alice")
j = A.get(B + "/api/about").json()
check(j.get("support_url") == "", "an http:// payment link is not shown")
check(j.get("supporter", {}).get("id") == "srv-1", "the server licence survives a restart")

# ---- the built-in public key alone: the test key is no longer trusted
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=dict(os.environ, KEEP="1", EXTRA=BASE))
A = sess("alice")
check(A.get(B + "/api/about").json().get("supporter") is None, "without the extra key the test licence counts for nothing")
check(A.put(B + "/api/supporter/person", json={"key": PER}).status_code == 400, "... and cannot be entered")

# ---- a hosted server: nothing
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env=dict(os.environ, KEEP="1", EXTRA=BASE + f" -e KALMIDO_HOSTED=1 -e KALMIDO_SECRET_KEY={'A' * 43}= -e KALMIDO_SUPPORTER_EXTRA_PUBKEYS={PUB} -e KALMIDO_SUPPORT_URL=https://pay.example.com/k"))
A = sess("alice")
j = A.get(B + "/api/about").json()
check(not any(k in j for k in ("supporter", "supporter_me", "support_url", "sup_nudge", "sup_nudge_on")), f"hosted: /api/about has no supporter fields ({sorted(j)[:8]})")
check(A.get(B + "/api/supporter").status_code == 404, "hosted: GET 404")
check(A.put(B + "/api/supporter/server", json={"key": SRV}).status_code == 404, "hosted: PUT 404")
check(A.put(B + "/api/supporter/person", json={"key": PER}).status_code == 404, "hosted: PUT person 404")
check(A.delete(B + "/api/supporter/server").status_code == 404, "hosted: DELETE 404")
check(A.post(B + "/api/supporter/server/swap").status_code == 404, "hosted: swap 404")
check(A.patch(B + "/api/supporter/nudge", json={"seen": True}).status_code == 404, "hosted: hint 404")

shutil.rmtree(TMP, ignore_errors=True)
print(f"p274_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
