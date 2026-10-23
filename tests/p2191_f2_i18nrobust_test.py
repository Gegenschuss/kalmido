#!/usr/bin/env python3
"""2.191.0 API tests, part F2 (#2518): the split of the language files stays robust. Own container (start.sh).
freelancer-matrix: public
 - the key reader (kalmido/core/i18nkeys.py) reads JavaScript literals itself: escaped quotes, \\x41, \\0, \\u{1F600}, a raw
   tab, a surrogate pair, template literals without ${}; an unreadable literal (octal, a line break, a code point out of
   range, Python "\\N") gives no key and is reported (bad list, tools/i18n_check.py fails with it); no exception
 - a string literal of a start file / i18n.js / sw.js / the server that is a key keeps it in the core (areas.js:
   tr(open ? 'Collapse' : 'Expand')); the literal scanner sees every tr key of the start files and the server's JS
 - module_keys without lazyload.js / without LD_MODS: an error (the server turns the split off)
 - the parts carry an ETag: If-None-Match -> 304 without a body (also de.core.json without ?v=, the service worker's precache)
 - a part asked with another version (a page of the code before an update) holds every key its module uses, revalidated
 - the split off (LD_MODS unreadable in the container): the page works and names no version, <code>.core.json is the whole
   file (no _mods), the parts 404; back on: the version again
 - a person without an organisation gets the same
usage: p2191_f2_i18nrobust_test.py <datadir>   (KMT_NOSTART=1: the container runs already)"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
from freelancer_fixture import freelancer, login  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


_spec = importlib.util.spec_from_file_location("i18nkeys", os.path.join(ROOT, "kalmido", "core", "i18nkeys.py"))
K = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(K)

# ================= the key reader (no app needed)
src = r"""tr('a \"b\"'); tr('\x41'); tr('\0'); tr('\u{1F600}'); tr('a	tab'); tr("it\'s"); tr(`tpl`); tr(`x${y}`);
tr('\uD83D\uDE00'); tr('a\
b'); tr('\01'); tr('\u{110000}'); tr('x
y'); trn('{0} item', '{0} items', n);"""
bad = []
keys = [c[1] for c in K.key_calls(src, False, bad)]
check(keys[:10] == ['a "b"', "A", "\0", "\U0001F600", "a\ttab", "it's", "tpl", None, "\U0001F600", "ab"], f"JS literals read {keys[:10]}")
check(keys[10:13] == [None, None, None] and len(bad) == 3, f"unreadable JS literals: no key, reported {keys[10:13]} {bad}")
check(keys[13] == "{0} item", "trn after them still read")
bad = []
keys = [c[1] for c in K.key_calls(r'''tr("\N") ; tr('ok\n'); tr(f'x {y}'); tr("""doc""")''', True, bad)]
check(keys[:3] == [None, "ok\n", None] and len(bad) == 1, f"Python: a SyntaxError is one unreadable literal {keys} {bad}")
check(K.str_literals("a = 'x' // 'no'\nb = `t${ {a: 1}['k'] + `in` }tail`; c = /'/.test(s) ? \"q\" : `w`; /* 'n' */", False) == {"x", "k", "in", "q", "w"},
      "the literal scanner: comments, nested templates, a regular expression with a quote")
check(K.str_literals("x = 'a'  # 'no'\ny = f\"{tr('b')} c\" + r'\\d' + rb'z' + '''d'''\n", True) >= {"a", "b", "d"} and "no" not in K.str_literals("# 'no'\n", True),
      "the Python literals (f-string insides, triple quotes), comments skipped")
MOD_OF, MODS = K.module_keys(ROOT)
check("Collapse" not in MOD_OF and "Expand" not in MOD_OF, f"Collapse / Expand stay in the core ({MOD_OF.get('Collapse')}, {MOD_OF.get('Expand')})")
start = re.findall(r'<script src="/static/js/([\w-]+\.js)', open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read())
lost = []
for f in start:
    s = open(os.path.join(ROOT, "static", "js", f), encoding="utf-8").read()
    lits = K.str_literals(s, False)
    lost += [(f, k) for _, k, _, _ in K.key_calls(s, False) if k is not None and k not in lits]
    lost += [(f, k) for k in lits if k in MOD_OF]
check(start and not lost, f"every key of the start files is a literal the scanner sees, none in a part {lost[:3]}")
for f in ("i18n.js", "sw.js"):
    lits = K.str_literals(open(os.path.join(ROOT, "static", f), encoding="utf-8").read(), False)
    check(lits and not lits & set(MOD_OF), f"{f}: its literals stay in the core")
tmp = tempfile.mkdtemp()
try:
    os.makedirs(os.path.join(tmp, "static", "js"))
    try:
        K.module_keys(tmp)
        check(False, "without lazyload.js: an error")
    except OSError:
        check(True, "without lazyload.js: an error")
    with open(os.path.join(tmp, "static", "js", "lazyload.js"), "w", encoding="utf-8") as f:
        f.write("const LD_MODZ = {\n  a: ['a'],\n};\n")
    try:
        K.module_keys(tmp)
        check(False, "LD_MODS unreadable: an error")
    except ValueError:
        check(True, "LD_MODS unreadable: an error")
    # the checker reports an unreadable literal as an error (CI)
    for rel in ("tools/i18n_check.py", "kalmido/core/i18nkeys.py", "static/js/lazyload.js", "static/index.html"):
        os.makedirs(os.path.join(tmp, os.path.dirname(rel)), exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), os.path.join(tmp, rel))
    os.makedirs(os.path.join(tmp, "static", "i18n"))
    with open(os.path.join(tmp, "static", "js", "zz.js"), "w", encoding="utf-8") as f:
        f.write("const zz = () => tr('\\01');\n")
    r = subprocess.run([sys.executable, os.path.join(tmp, "tools", "i18n_check.py")], capture_output=True, text=True)
    check(r.returncode != 0 and "static/js/zz.js:1: tr() with a string the key reader cannot read" in r.stdout, f"i18n_check fails on it {r.stdout[-300:]}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ================= the server
if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"lang": "de", "collab_all": True})
FID, Fr = freelancer(B, A)  # freelancer-matrix: public
anon = requests.Session()


def ver(s=anon):
    r = s.get(B + "/")
    m = re.search(r'<meta name="kalmido-i18n" content="([^"]*)">', r.text)
    return r.status_code, (m.group(1) if m else None)


st, V = ver()
check(st == 200 and re.fullmatch(r"[0-9a-f]{12}", V or ""), f"the page names the version {V!r}")
core = anon.get(B + f"/static/i18n/de.core.json?v={V}").json()
de = json.load(open(os.path.join(ROOT, "static", "i18n", "de.json"), encoding="utf-8"))
check(core.get("Collapse") == de.get("Collapse") and core.get("Expand") == de.get("Expand"), "the server's core holds Collapse / Expand")

# ETag + 304
for q in ("", f"?v={V}"):
    r = anon.get(B + "/static/i18n/de.core.json" + q, headers={"Accept-Encoding": "gzip"})
    et = r.headers.get("ETag", "")
    check(r.ok and re.fullmatch(r'W/"[0-9a-f]{20}"', et), f"de.core.json{q}: an ETag {et!r}")
    r2 = anon.get(B + "/static/i18n/de.core.json" + q, headers={"If-None-Match": et, "Accept-Encoding": "gzip"})
    check(r2.status_code == 304 and not r2.content and r2.headers.get("ETag") == et, f"de.core.json{q}: 304 on If-None-Match ({r2.status_code}, {len(r2.content)} bytes)")
r = Fr.get(B + f"/static/i18n/de.mod-office.json?v={V}")
r2 = Fr.get(B + f"/static/i18n/de.mod-office.json?v={V}", headers={"If-None-Match": r.headers.get("ETag", "-")})
check(r.ok and r2.status_code == 304 and r.headers.get("ETag") != anon.get(B + "/static/i18n/fr.mod-office.json").headers.get("ETag"),
      "a part: 304 for a person without an organisation too, another language another ETag")
r3 = anon.get(B + "/static/i18n/de.core.json", headers={"If-None-Match": 'W/"00000000000000000000"'})
check(r3.status_code == 200 and r3.content, "another ETag: the whole answer")

# a part for a page of another version
uses = {}
K.module_keys(ROOT, uses)
newp = anon.get(B + f"/static/i18n/de.mod-timeline.json?v={V}").json()
r = anon.get(B + "/static/i18n/de.mod-timeline.json?v=000000000000")
oldp = r.json() if r.ok else {}
want = {k: de[k] for k in uses.get("timeline", ()) if k in de}
check(r.ok and "immutable" not in r.headers.get("Cache-Control", "") and oldp == {**want, **newp},
      f"another version: the part holds every key the module uses ({len(oldp)} vs {len(newp)} keys)")
check(oldp.get("Collapse") == de["Collapse"] and "Collapse" not in newp, "another version: also the keys that moved into the core (Collapse)")
check(anon.get(B + "/static/i18n/de.mod-nope.json?v=000000000000").status_code == 404, "an unknown module stays 404")

# the split off: LD_MODS unreadable inside the container, then back
LZ = "/app/static/js/lazyload.js"


def dx(*cmd):
    return subprocess.run(["docker", "exec", "-u", "0", CT, *cmd], capture_output=True, text=True)


r = dx("sed", "-i", "s/^const LD_MODS = {/const LD_MODZ = {/", LZ)
check(r.returncode == 0, f"lazyload.js changed in the container {r.stderr}")
time.sleep(6.5)
try:
    st, v0 = ver()
    check(st == 200 and v0 == "", f"split off: the page works and names no version ({st}, {v0!r})")
    st, v1 = ver(Fr)
    check(st == 200 and v1 == "", "split off: also for a person without an organisation")
    r = anon.get(B + "/static/i18n/de.core.json")
    whole = r.json() if r.ok else {}
    check(r.ok and "_mods" not in whole and len(whole) == len(de), f"split off: de.core.json is the whole file ({r.status_code}, {len(whole)} keys)")
    check(anon.get(B + f"/static/i18n/de.mod-office.json?v={V}").status_code == 404, "split off: the parts 404")
    check(anon.get(B + "/static/i18n/de.json").ok, "split off: the whole file stays")
    man = anon.get(B + "/sw-manifest.json")
    check(man.ok and "/static/i18n/de.core.json" not in man.json().get("files", {}), "split off: the manifest names no version of the core")
finally:
    dx("sed", "-i", "s/^const LD_MODZ = {/const LD_MODS = {/", LZ)
time.sleep(6.5)
st, v2 = ver()
check(st == 200 and v2 == V, f"back on: the same version ({v2!r})")
check(anon.get(B + f"/static/i18n/de.mod-office.json?v={V}").ok, "back on: the parts again")

print(f"\np2191_f2_i18nrobust: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
