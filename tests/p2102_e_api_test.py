#!/usr/bin/env python3
"""2.102.0 API tests, part E (#1999, #1995): the layer check of the server package, the type-check guard of the web client
and the browser's own error reports. Invented names only.
 - tools/check_layers.py: green on the code; on a small invented package it finds a new upward import at module level, lets
   a function-local one pass, reports a package without a layer and a KNOWN entry that is gone
 - tools/check_tscheck.py: green on the code; a new static/js file without "// @ts-check" fails, one with it passes
 - POST /api/client-errors: off until the admin picks a project list with error reports on (204, nothing stored); the choice
   only offers / accepts such lists the admin manages; a person's report becomes a bug ticket created by nobody, with the
   message cut of data (quoted texts, addresses, links with ids, long numbers), only /static/ places, version and area; the
   same error again only counts; at most 5 per person and minute; never for a request without a session; a freelancer (a
   person without an organisation) reports into the operator's list too, and sees nothing of it; error reports off in that
   list stops it; GET /api/about tells everyone only whether reports are on
tenant-matrix: clienterr
freelancer-matrix: own
usage: p2102_e_api_test.py <datadir>      (a fresh container; P2102E_NOSTART=1: the container runs already)"""
import os
import shutil
import subprocess
import sys
import tempfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

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


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def run(*cmd, cwd=None):
    r = subprocess.run([sys.executable, *cmd], cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# ================================================================ 1. the layer check (static, no container)
rc, out = run(os.path.join(ROOT, "tools", "check_layers.py"), "-v")
check(rc == 0 and "known upward imports" in out, f"check_layers: green on the code ({out[-300:]})")

INIT = '''import importlib
LAYERS = (
    ("core", ("core",)),
    ("accounts", ("accounts",)),
    ("domain", ("tasks",)),
    ("integrations", ("api",)),
    ("agents", ("agents",)),
)
LAYER_OF = {"tasks.low": "core"}
ORDER = (
    "core.a",
    "tasks.low",
    "accounts.b",
    "tasks.c",
    "api.d",
    "agents.e",
)
'''
FILES = {
    "core/a.py": "X = 1\n",
    "tasks/low.py": "from ..core.a import X\n",  # LAYER_OF: core, only core below it
    "accounts/b.py": "from ..core.a import X\n\n\ndef f():\n    from ..agents.e import Y  # function-local: allowed\n    return Y\n",
    "tasks/c.py": "from ..accounts.b import f\nfrom kalmido.core import a\n",
    "api/d.py": "from ..tasks.c import f\n",
    "agents/e.py": "from ..api.d import f\nY = 2\n",
}


def fake(extra=None, known=None, init=INIT):
    """A small invented package with tools/check_layers.py beside it; -> (exit code, output)."""
    d = tempfile.mkdtemp(prefix="p2102e-")
    try:
        os.makedirs(os.path.join(d, "tools"))
        src = open(os.path.join(ROOT, "tools", "check_layers.py"), encoding="utf-8").read()
        if known is not None:  # replace the KNOWN set of the real code with the given one
            a = src.index("KNOWN = {")
            b = src.index("\n}\n", a) + 3
            src = src[:a] + "KNOWN = " + repr(set(known)) + "\n" + src[b:]
        open(os.path.join(d, "tools", "check_layers.py"), "w", encoding="utf-8").write(src)
        files = dict(FILES, **(extra or {}))
        for p, body in files.items():
            os.makedirs(os.path.join(d, "kalmido", os.path.dirname(p)), exist_ok=True)
            open(os.path.join(d, "kalmido", os.path.dirname(p), "__init__.py"), "w").close()
            open(os.path.join(d, "kalmido", p), "w", encoding="utf-8").write(body)
        open(os.path.join(d, "kalmido", "__init__.py"), "w", encoding="utf-8").write(init)
        return run(os.path.join(d, "tools", "check_layers.py"), "-v")
    finally:
        shutil.rmtree(d, ignore_errors=True)


rc, out = fake(known=set())
check(rc == 0 and "0 known upward imports" in out, f"check_layers: a clean package passes, function-local imports count ({out})")
check("1 function-local" in out, f"check_layers: the function-local import is counted ({out})")
rc, out = fake({"tasks/low.py": "from ..core.a import X\nfrom ..accounts.b import f\n"}, known=set())
check(rc == 1 and "tasks/low.py:2" in out and "accounts.b" in out, f"check_layers: LAYER_OF moves a module down ({out})")
rc, out = fake({"accounts/b.py": "from ..agents.e import Y\n"}, known=set())
check(rc == 1 and "kalmido/accounts/b.py:1: module-level import of agents.e (agents) from layer accounts" in out,
      f"check_layers: a new upward import at module level fails ({out})")
rc, out = fake({"accounts/b.py": "from ..agents.e import Y\n"}, known={("accounts.b", "agents.e")})
check(rc == 0, f"check_layers: a KNOWN upward import passes ({out})")
rc, out = fake(known={("tasks.c", "agents.e")})
check(rc == 1 and "tasks.c -> agents.e is no upward import any more" in out, f"check_layers: a stale KNOWN entry fails ({out})")
rc, out = fake({"misc/z.py": "X = 3\n"}, known=set(), init=INIT.replace('    "agents.e",\n', '    "agents.e",\n    "misc.z",\n'))
check(rc == 1 and "package 'misc'" in out, f"check_layers: a package without a layer fails ({out})")

# ================================================================ 2. the @ts-check guard (static, no container)
TSG = os.path.join(ROOT, "tools", "check_tscheck.py")
if os.path.exists(TSG):
    rc, out = run(TSG)
    check(rc == 0, f"check_tscheck: green on the code ({out[-300:]})")
    d = tempfile.mkdtemp(prefix="p2102e-ts-")
    try:
        shutil.copytree(os.path.join(ROOT, "static", "js"), os.path.join(d, "static", "js"))
        os.makedirs(os.path.join(d, "tools"))
        shutil.copy(TSG, os.path.join(d, "tools"))
        if os.path.exists(os.path.join(ROOT, "jsconfig.json")):
            shutil.copy(os.path.join(ROOT, "jsconfig.json"), d)
        open(os.path.join(d, "static", "js", "zzneu.js"), "w").write("'use strict';\nfunction zz_x() { return 1; }\n")
        rc, out = run(os.path.join(d, "tools", "check_tscheck.py"))
        check(rc == 1 and "zzneu.js" in out, f"check_tscheck: a new file without // @ts-check fails ({out})")
        open(os.path.join(d, "static", "js", "zzneu.js"), "w").write("// @ts-check\n'use strict';\nfunction zz_x() { return 1; }\n")
        rc, out = run(os.path.join(d, "tools", "check_tscheck.py"))
        check(rc == 0, f"check_tscheck: with // @ts-check it passes ({out})")
    finally:
        shutil.rmtree(d, ignore_errors=True)
else:
    check(False, "tools/check_tscheck.py exists")

# ================================================================ 3. the browser's error reports (container)
if not os.environ.get("P2102E_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
P = A.post(B + "/api/lists", json={"name": "Kalmido errors", "kind": "project"}).json()["id"]
Q = A.post(B + "/api/lists", json={"name": "Other project", "kind": "project"}).json()["id"]
BP = Bo.post(B + "/api/lists", json={"name": "Bob's project", "kind": "project"}).json()["id"]
ERR = {"msg": "TypeError: x.y is not a function", "src": "https://kalmido.example/static/js/render.js?v=2", "line": 120, "col": 7,
       "stack": "at drawRow (https://kalmido.example/static/js/render.js:120:7)\nat https://other.example/x.js:1:1", "ver": "2.102.0",
       "view": "tasks", "kind": "error"}


def report(s, **kw):
    return s.post(B + "/api/client-errors", json=dict(ERR, **kw))


def tickets():
    return dbx("SELECT id, title, content, created_by FROM tasks WHERE list_id=? AND deleted_at IS NULL ORDER BY id", (P,))


check(A.get(B + "/api/about").json().get("client_errors") is False, "off by default: about says so")
check(report(Bo).status_code == 204 and not tickets(), "off: a report is dropped (204, nothing stored)")
check(requests.post(B + "/api/client-errors", json=ERR, headers=H).status_code in (401, 403), "no session: refused")
# the choice: only project lists with error reports on, which the admin manages
check(A.patch(B + "/api/admin/settings", json={"client_errors_list": P}).status_code == 400, "a list without error reports cannot be chosen")
check(A.patch(B + f"/api/lists/{P}/error-hook", json={"state": "on"}).ok, "setup: error reports on in the list")
check(Bo.patch(B + f"/api/lists/{BP}/error-hook", json={"state": "on"}).ok, "setup: bob's list has error reports too")
ab = A.get(B + "/api/about").json()
ids = [x["id"] for x in ab.get("client_errors_lists", [])]
check(P in ids and BP not in ids and Q not in ids, f"the choice: only the admin's lists with error reports ({ab.get('client_errors_lists')})")
check(A.patch(B + "/api/admin/settings", json={"client_errors_list": BP}).status_code == 400, "a list the admin does not manage: refused")
check(A.patch(B + "/api/admin/settings", json={"client_errors_list": "x"}).status_code == 400, "an invalid value: refused")
check(Bo.patch(B + "/api/admin/settings", json={"client_errors_list": BP}).status_code == 403, "not an admin: refused")
r = A.patch(B + "/api/admin/settings", json={"client_errors_list": P})
check(r.ok and r.json().get("client_errors_list") == P and r.json().get("client_errors") is True, f"the admin picks the list ({r.text[:200]})")
jb = Bo.get(B + "/api/about").json()
check(jb.get("client_errors") is True and "client_errors_list" not in jb and "client_errors_lists" not in jb,
      f"a person only learns that reports are on ({jb})")
check(Bo.get(B + "/api/state").json().get("about", {}).get("client_errors") is True, "the state carries it (the client reads S.about)")

# a report -> a bug ticket created by nobody
check(report(Bo).status_code == 204, "bob reports an error")
t = tickets()
check(len(t) == 1 and t[0]["created_by"] is None and t[0]["title"] == ERR["msg"], f"a ticket created by nobody ({t})")
body = t[0]["content"] if t else ""
check("/static/js/render.js:120:7" in body and "kalmido.example" not in body and "other.example" not in body and "?v=2" not in body,
      f"only /static/ places, origin and query dropped ({body})")
check("2.102.0" in body and "tasks" in body and "Browser" in body, f"version, area and the source in the ticket ({body})")
check("bob" not in body.lower(), f"no name of the person ({body})")
# the same error again only counts (another column: the same place)
check(report(Ca, col=9).status_code == 204 and len(tickets()) == 1, "the same error at the same line again: still one ticket")
cnt = dbx("SELECT count FROM issue_reports WHERE list_id=? AND fp LIKE 'cl:%'", (P,))
check(cnt and cnt[0]["count"] == 2, f"... counted ({cnt})")
# data is cut out of the message
report(Ca, msg="Error: cannot save 'Anniversary dinner with Mrs Example' for anna.example@example.com "
               "at https://kalmido.example/#t/48213?token=s3cr3tvalue id 9a8b7c6d5e4f3a2b1c0d9e8f order 123456", line=5)
t = tickets()
last = t[-1]["title"] if len(t) == 2 else ""
check(len(t) == 2 and "Anniversary" not in last and "anna.example" not in last and "s3cr3t" not in last and "48213" not in last
      and "9a8b7c6d5e4f" not in last and "123456" not in last and "cannot save" in last,
      f"quoted texts, addresses, links, ids and long numbers are cut ({last})")
report(Ca, msg="TypeError: cannot read properties of undefined (reading 'title')", line=6)
t = tickets()
check(any("(reading 'title')" in x["title"] for x in t), f"a plain name in quotes stays (reading 'title') ({[x['title'] for x in t]})")
check(report(Ca, msg="   ").status_code == 400, "an empty message: 400")
check(report(Ca, msg="Odd", src="https://evil.example/static/../../x.js", line=1, view="tasks/48213", ver="<b>").status_code == 204, "odd fields: taken")
odd = [x for x in tickets() if x["title"] == "Odd"]
check(odd and "evil.example" not in odd[0]["content"] and "48213" not in odd[0]["content"] and "<b>" not in odd[0]["content"],
      f"odd place / view / version are dropped ({odd and odd[0]['content']})")
# at most 5 per person and minute: carol sent 5 above (the limit counts before the check of the message)
n0 = len(tickets())
for i in range(4):
    report(Ca, msg=f"Limit test {chr(65 + i)}", line=200 + i)
made = len(tickets()) - n0
check(made < 4, f"carol's reports past 5 per minute are dropped ({made} new of 4)")
# a freelancer (no organisation) reports into the operator's list and sees nothing of it
FID, Fr = freelancer(B, A)
n0 = len(tickets())
check(report(Fr, msg="Freelancer error", line=300).status_code == 204 and len(tickets()) == n0 + 1, "freelancer: the report arrives")
check(Fr.get(B + f"/api/lists/{P}/error-hook").status_code in (403, 404)
      and P not in [x["id"] for x in Fr.get(B + "/api/state").json().get("lists", [])], "freelancer: sees nothing of the list")
check(Fr.get(B + "/api/about").json().get("client_errors") is True and "client_errors_lists" not in Fr.get(B + "/api/about").json(),
      "freelancer: only the flag")
# error reports off in the list stops it
check(A.patch(B + f"/api/lists/{P}/error-hook", json={"state": "off"}).ok, "error reports off in the list")
check(A.get(B + "/api/about").json().get("client_errors") is False, "... reports are off for everyone")
n0 = len(tickets())
check(report(Bo, msg="After off", line=400).status_code == 204 and len(tickets()) == n0, "... and nothing arrives")
check(A.patch(B + "/api/admin/settings", json={"client_errors_list": None}).ok, "the admin switches it off")

print(f"p2102_e_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
