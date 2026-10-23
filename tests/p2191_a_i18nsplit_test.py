#!/usr/bin/env python3
"""2.191.0 API tests, part A (#1410 #2518): the language files split per module loaded on demand. Own container (start.sh).
freelancer-matrix: public
 - the page names the version of the split texts (meta kalmido-i18n, 12 hex digits); /static/i18n/<code>.json stays the
   whole file (server, translators, older clients)
 - /static/i18n/<code>.core.json + /static/i18n/<code>.mod-<name>.json for every language: the core names the modules with
   a part (_mods); core + parts = the whole file without a loss, no key twice; a part holds only keys that tr / trn use in
   that module's files alone (the same split as kalmido/core/i18nkeys.py on the checked-out code); keys of the start
   scripts, of the server and keys a module only marks with N_ stay in the core
 - like a static file: no sign-in, no database statement (also with a wrong cookie, also for a person without an
   organisation), ?v=<version> immutable, another / no ?v= revalidated, gzip on request; unknown language / module 404
 - /sw-manifest.json names the precached core texts (de) with the version
usage: p2191_a_i18nsplit_test.py <datadir>   (KMT_NOSTART=1: the container runs already)"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
from freelancer_fixture import freelancer, login  # noqa: E402

from kt import FAILS, OKS, check, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
STARTED = not os.environ.get("KMT_NOSTART")


_spec = importlib.util.spec_from_file_location("i18nkeys", os.path.join(ROOT, "kalmido", "core", "i18nkeys.py"))
KEYS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(KEYS)

if STARTED:
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"lang": "de", "collab_all": True})
FID, Fr = freelancer(B, A)  # freelancer-matrix: public (the same files without an organisation)
anon = requests.Session()
bad = requests.Session()
bad.cookies.set("kalmido_session", "not-a-session")

html = A.get(B + "/").text
m = re.search(r'<meta name="kalmido-i18n" content="([^"]*)">', html)
V = m.group(1) if m else ""
check(re.fullmatch(r"[0-9a-f]{12}", V) is not None, f"the page names the version of the split texts {V!r}")
check(anon.get(B + "/").text.count(f'content="{V}"') == 1, "the same version without signing in")

# the split of the checked-out code (the container runs the same code)
MOD_OF, MODS = KEYS.module_keys(ROOT)
check(len(MODS) > 30 and len(MOD_OF) > 1000, f"the modules loaded on demand are read ({len(MODS)} modules, {len(MOD_OF)} keys in parts)")
I18N = os.path.join(ROOT, "static", "i18n")
LANGS = sorted(f[:-5] for f in os.listdir(I18N) if f.endswith(".json"))
check(set(LANGS) >= {"de", "fr"}, f"languages {LANGS}")

# keys that must stay in the core: the start scripts, the server, keys a module only marks with N_
start = re.findall(r'<script src="/static/js/([\w-]+\.js)', open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read())
lazy_files = {f + ".js" for fs in MODS.values() for f in fs}
check(start and not set(start) & lazy_files, f"start scripts read ({len(start)}), none is a module file")
must_core, server_keys, marked = set(), set(), set()
for rel in KEYS.key_sources(ROOT):
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    py = rel.endswith(".py")
    in_mod = not py and os.path.basename(rel) in lazy_files
    for fn, key, _, _ in KEYS.key_calls(src, py):
        if key is None:
            continue
        if not in_mod:
            must_core.add(key)
            if py:
                server_keys.add(key)
        elif fn in ("N_", "Nn_"):
            marked.add(key)
must_core |= marked
check(not must_core & set(MOD_OF), f"no key of a start script / the server / a N_ mark is in a part {sorted(must_core & set(MOD_OF))[:3]}")

sizes = {}
for code in LANGS:
    full = anon.get(B + f"/static/i18n/{code}.json").json()
    r = anon.get(B + f"/static/i18n/{code}.core.json?v={V}", headers={"Accept-Encoding": "gzip"})
    cc = r.headers.get("Cache-Control", "")
    check(r.ok and "json" in r.headers.get("Content-Type", "") and "immutable" in cc and "max-age=31536000" in cc,
          f"{code}: the core texts with the version: immutable JSON ({r.status_code} {cc!r})")
    check(r.headers.get("Content-Encoding") == "gzip", f"{code}: the core goes out gzip-compressed ({r.headers.get('Content-Encoding')!r})")
    core = r.json()
    mods = core.pop("_mods", None)
    check(isinstance(mods, list) and mods and set(mods) <= set(MODS), f"{code}: the core names the modules with a part ({mods and len(mods)})")
    check(core.get("_meta") == full.get("_meta") and core.get("_weekdays") == full.get("_weekdays"), f"{code}: _meta and the names stay in the core")
    seen = dict(core)
    total = len(r.content)
    dup, wrong = [], []
    for mname in mods or []:
        rp = bad.get(B + f"/static/i18n/{code}.mod-{mname}.json?v={V}")
        part = rp.json() if rp.ok else {}
        check(rp.ok and part and "immutable" in rp.headers.get("Cache-Control", ""), f"{code}: the part of {mname} ({rp.status_code})")
        total += len(rp.content)
        for k, v in part.items():
            if k in seen:
                dup.append(k)
            if MOD_OF.get(k) != mname:
                wrong.append((mname, k))
            seen[k] = v
    check(not dup, f"{code}: no key in two files {dup[:3]}")
    check(not wrong, f"{code}: a part holds only the keys of its module {wrong[:3]}")
    check(seen == full, f"{code}: core + parts = the whole file ({len(seen)} vs {len(full)} keys)")
    check(all(k in core for k in must_core if k in full), f"{code}: every start / server / marked key is in the core")
    check(any(k in core for k in server_keys if k in full), f"{code}: server texts in the core")
    sizes[code] = (len(json.dumps(full, ensure_ascii=False, separators=(",", ":")).encode()),
                   len(json.dumps(dict(core, _mods=mods), ensure_ascii=False, separators=(",", ":")).encode()), len(mods or []))
    for mname in sorted(set(MODS) - set(mods or [])):  # a module without keys of its own: an empty part, no 404
        rp = anon.get(B + f"/static/i18n/{code}.mod-{mname}.json?v={V}")
        check(rp.ok and rp.json() == {}, f"{code}: {mname} has no part of its own: {{}} ({rp.status_code})")
print("sizes (whole file / core bytes, parts):", sizes, flush=True)
check(sizes["de"][1] < sizes["de"][0] * 0.8, f"de: the core is clearly smaller than the whole file {sizes['de']}")
check(anon.get(B + "/static/i18n/de.core.json?v=" + V).json() == A.get(B + "/static/i18n/de.core.json?v=" + V).json(),
      "the same core with and without signing in")
r = Fr.get(B + "/static/i18n/de.mod-office.json?v=" + V)
check(r.ok and r.json() and all(MOD_OF.get(k) == "office" for k in r.json()), f"a person without an organisation gets the same part ({r.status_code})")

# like a static file: no statement, revalidated without the version
for who, s in (("signed in", A), ("freelancer", Fr), ("wrong cookie", bad), ("no cookie", anon)):
    r = s.get(B + "/static/i18n/fr.core.json?v=" + V)
    t = re.match(r'^app;dur=[\d.]+, db;dur=[\d.]+;desc="n=(\d+)"$', r.headers.get("Server-Timing", ""))
    check(r.ok and (t is None or t.group(1) == "0"), f"no database statement ({who}: {r.headers.get('Server-Timing')!r})")
for q in ("", "?v=000000000000", "?v=2.191.0"):
    r = anon.get(B + "/static/i18n/de.core.json" + q)
    check(r.ok and "immutable" not in r.headers.get("Cache-Control", ""), f"de.core.json{q}: revalidated {r.headers.get('Cache-Control')!r}")
r = anon.get(B + "/static/i18n/de.mod-office.json", headers={"Accept-Encoding": "identity"})
check(r.ok and not r.headers.get("Content-Encoding"), "without gzip asked: plain JSON")
for u in ("/static/i18n/xx.core.json", "/static/i18n/en.core.json", "/static/i18n/de.mod-nope.json", "/static/i18n/xx.mod-office.json",
          "/static/i18n/DE.core.json", "/static/i18n/de.mod-.json"):
    check(anon.get(B + u).status_code == 404, f"{u}: 404")
r = anon.get(B + "/static/i18n/de.json")
check(r.ok and len(r.json()) == len(json.load(open(os.path.join(I18N, "de.json"), encoding="utf-8"))), "the whole file stays (older clients, the server)")
man = anon.get(B + "/sw-manifest.json").json().get("files", {})
check(man.get("/static/i18n/de.core.json") == V, f"sw-manifest: the precached core texts with the version {man.get('/static/i18n/de.core.json')!r}")
check("/static/i18n/de.json" not in man, "sw-manifest: the whole file is no longer precached")

print(f"\np2191_a_i18nsplit: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
