#!/usr/bin/env python3
"""2.40.0 API tests, part E (office settings), own container (start.sh, mode workspaces). Invented companies only.
 - #1378: no fetch() in static/js writes (POST / PUT / PATCH / DELETE) without the CSRF header X-Requested-With;
   the logo upload and the settings import work with the header and are refused without it
usage: p2400_e_api_test.py <datadir>"""
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
# a 1x1 PNG
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


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


# ---------------------------------------------------------------- #1378: the static check (no container needed)
def fetch_calls(src):
    """(line, argument text) of every fetch( call; strings and nested parentheses are skipped."""
    for m in re.finditer(r"\bfetch\(", src):
        i, d, q = m.end(), 1, None
        while i < len(src) and d:
            c = src[i]
            if q:
                if c == "\\":
                    i += 1
                elif c == q:
                    q = None
            elif c in "'\"`":
                q = c
            elif c == "(":
                d += 1
            elif c == ")":
                d -= 1
            i += 1
        yield src.count("\n", 0, m.start()) + 1, src[m.end():i - 1]


# fetch() calls whose options come from a variable: reviewed by hand
FETCH_VAR_OK = {
    ("core.js", "url, opt"),  # rawFetch0: opt is built with the header right above
}
JS = os.path.join(N, "..", "static", "js")
bad = []
for fn in sorted(os.listdir(JS)):
    if not fn.endswith(".js"):
        continue
    for ln, a in fetch_calls(open(os.path.join(JS, fn), encoding="utf-8").read()):
        a1 = " ".join(a.split())
        if "X-Requested-With" in a1:
            continue
        if re.fullmatch(r"[\w.]+\s*,\s*[\w.]+", a1):  # options from a variable
            if (fn, a1) not in FETCH_VAR_OK:
                bad.append(f"{fn}:{ln}: options from a variable, not reviewed: {a1}")
            continue
        if "method" not in a1 or re.search(r"method:\s*'GET'", a1):
            continue  # a GET needs no header
        bad.append(f"{fn}:{ln}: {a1[:90]}")
check(not bad, "#1378: every writing fetch() sends X-Requested-With " + repr(bad))

# ---------------------------------------------------------------- the container
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces"),
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
FEAT = "cal,comments,collab,office,clients"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
O = "/api/office"

# ---------------------------------------------------------------- #1378: logo + import with / without the header
naked = requests.Session()
naked.cookies.update(A.cookies)
r = naked.post(B + O + "/logo", files={"file": ("logo.png", PNG, "image/png")})
check(r.status_code in (400, 403), f"#1378: a logo upload without the header is refused {r.status_code}")
r = A.post(B + O + "/logo", files={"file": ("logo.png", PNG, "image/png")})
check(r.ok, "#1378: the logo upload with the header " + r.text[:160])
check(bool(A.get(B + O + "/settings").json()["settings"].get("logo")), "#1378: the logo is set")
exp = A.get(B + O + "/export")
check(exp.ok, "#1378: export")
r = A.post(B + O + "/import", files={"file": ("office.json", exp.content, "application/json")})
check(r.ok, "#1378: the settings import with the header " + r.text[:160])
r = naked.post(B + O + "/import", files={"file": ("office.json", exp.content, "application/json")})
check(r.status_code in (400, 403), f"#1378: an import without the header is refused {r.status_code}")

# ==== (more parts below)

print(f"p2400_e_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
