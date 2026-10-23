#!/usr/bin/env python3
"""2.191.0 tests, part B: static files without comments (#1824), start scripts with defer (#2505). Own container (start.sh).
freelancer-matrix: public
 - #1824 unit: the comment remover (kalmido/core/strip.py) keeps strings, template literals with nested ${...}, regular
   expressions (also with // or /* inside, after return / ( / =), divisions, // in URLs, CSS strings and url(...); line
   breaks stay (a comment line becomes an empty line, a comment over several lines keeps its line breaks); a/**/b stays
   two words; unsure input (unterminated string / comment / template, unbalanced braces) gives None = file unchanged;
   static/vendor/ and other kinds of files are never touched; every client file passes tools/strip_check.py
 - #1824 server: /static/js/core.js and /static/app.css go out without comments with the line count of the source, the
   ?v= hash of index.html is the hash of the served bytes, the hashed file is immutable, without ?v= revalidated, ETag +
   If-None-Match = 304, HEAD answers; images and static/vendor/ go out byte for byte; the same without signing in, for a
   person without an organisation and for an organisation's admin
 - #2505: every start script of index.html carries defer, the order is the order of the source; the app's start blocks
   wait through domReady (core.js is served with it)
usage: p2191_b_strip_test.py <datadir>      (P2191B_NOSTART=1 / KMT_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import glob
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer, login  # noqa: E402

ROOT = os.path.dirname(N)
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]

_SPEC = importlib.util.spec_from_file_location("p2191b_strip", os.path.join(ROOT, "kalmido", "core", "strip.py"))
st = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(st)


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


# ================================================================== #1824 unit: JavaScript
JS = [
    ("var r = /\\/\\/x/g; // c", "var r = /\\/\\/x/g;"),
    ('const s = "/* not */ a // b"; /* c */ x();', 'const s = "/* not */ a // b";  x();'),  # only the comment goes, the blanks around it stay
    ("const t = `a // b ${ a / b } /* c */ ${ `in ${x} // y` }`; // end", "const t = `a // b ${ a / b } /* c */ ${ `in ${x} // y` }`;"),
    ("const t = `${ {a: 1}.a /* c */ }`;", "const t = `${ {a: 1}.a  }`;"),
    ("a = b / c / d; // x", "a = b / c / d;"),
    ("function f() { return /x\\/*/.test(s); }", "function f() { return /x\\/*/.test(s); }"),
    ("if (/[/*]/.test(s)) go(); // c", "if (/[/*]/.test(s)) go();"),
    ("const u = 'https://x.example/a'; // c", "const u = 'https://x.example/a';"),
    ("a/**/b", "a b"),
    ("return /*\n*/ x", "return\n x"),
    ("x = a++ / 2; // c\ny = (1) / 2 /* c */;", "x = a++ / 2;\ny = (1) / 2 ;"),
    ("/**\n * doc\n */\nfunction f() {}\n// tail\n", "\n\n\nfunction f() {}\n\n"),
    ("s = 'a\\'b // c'; t = \"x\\\" /* y */\";", "s = 'a\\'b // c'; t = \"x\\\" /* y */\";"),
    ("x = y.filter(v => v) / 2;", "x = y.filter(v => v) / 2;"),
    ("const re = [/a/, /b\\//]; // c", "const re = [/a/, /b\\//];"),
    ("a = b\n/* c */\n/re/.test(d)", None),  # stays valid JS either way; only checked for the same line count below
]
for src, want in JS:
    got = st.strip_js(src)
    if want is not None:
        check(got == want, f"#1824 js: {src!r} -> {got!r} (want {want!r})")
    check(got is not None and got.count("\n") == src.count("\n"), f"#1824 js: line count kept for {src!r}")
for bad in ('x = "abc', "/* open", "t = `a ${b", "f() { a }}", "s = 'a\nb'", "r = /abc\n/"):
    check(st.strip_js(bad) is None, f"#1824 js: unsure input left alone {bad!r}")

# ================================================================== #1824 unit: CSS
CSS = [
    ('a { content: "/*"; } /* c */', 'a { content: "/*"; }'),
    ("b { background: url(//x.example/a.png); } /* c */", "b { background: url(//x.example/a.png); }"),
    ("b { background: url( '/*x' ); }", "b { background: url( '/*x' ); }"),
    ("div /* c */ .x {}", "div  .x {}"),
    ("div/**/.x {}", "div.x {}"),
    ("/* a\n   b */\n.k { color: red; } /* end */\n", "\n\n.k { color: red; }\n"),
]
for src, want in CSS:
    got = st.strip_css(src)
    check(got == want, f"#1824 css: {src!r} -> {got!r} (want {want!r})")
check(st.strip_css("a/**/b {}") is None, "#1824 css: two words kept apart by a comment: file left alone")
check(st.strip_css('a { content: "x }') is None, "#1824 css: unterminated string: file left alone")
check(st.strip_asset("vendor/pdfjs/pdf.min.js", b"/* c */ x();") is None, "#1824: static/vendor/ is not touched")
check(st.strip_asset("i18n/de.json", b'{"a": "/* b */"}') is None, "#1824: JSON is not touched")
check(st.strip_asset("js/x.js", b"\xff\xfe/* c */") is None, "#1824: not UTF-8: unchanged")
check(st.strip_asset("js/x.js", b"/* c */ x();") == b" x();" or st.strip_asset("js/x.js", b"/* c */ x();") == b"x();",
      f"#1824: a .js file is stripped {st.strip_asset('js/x.js', b'/* c */ x();')!r}")

# every client file (node --check after stripping, line counts, a second pass changes nothing)
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "strip_check.py")], capture_output=True, text=True)
check(r.returncode == 0, f"#1824: tools/strip_check.py over all client files: {(r.stdout + r.stderr)[-600:]}")

# ================================================================== server
if not (os.environ.get("P2191B_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FID, Fr = freelancer(B, A)  # freelancer-matrix: public (static files and the app page for a person without an organisation)
anon = requests.Session()

html = A.get(B + "/").text
src_html = open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read()
want_order = re.findall(r'<script src="(/static/[\w./-]+\.js)"', src_html)
tags = re.findall(r'<script src="(/static/[\w./-]+\.js)\?v=([0-9a-f]{12})" defer></script>', html)
check(len(want_order) > 100 and [u for u, _ in tags] == want_order,
      f"#2505: every start script with ?v= and defer, in the order of the source ({len(tags)} of {len(want_order)})")
check(not re.search(r'<script src="/static/[^"]*"></script>', html), "#2505: no start script without defer")
hashes = dict(tags)
css_v = (re.search(r'<link rel="stylesheet" href="/static/app\.css\?v=([0-9a-f]{12})"', html) or [None, None])[1]

for who, s in (("no cookie", anon), ("freelancer", Fr), ("admin", A)):
    for u, v in (("/static/js/core.js", hashes.get("/static/js/core.js")), ("/static/app.css", css_v)):
        src = open(os.path.join(ROOT, u.lstrip("/")), "rb").read()
        r = s.get(B + u)
        body = r.content
        check(r.ok and len(body) < len(src) and b"/*" not in body.split(b"\n", 3)[0], f"#1824: {u} without comments ({who}, {len(src)} -> {len(body)})")
        check(body.count(b"\n") == src.count(b"\n"), f"#1824: {u} keeps its line count ({who})")
        check(v == hashlib.sha256(body).hexdigest()[:12], f"#1824: {u}: the ?v= hash is the served bytes' ({who})")
        check("no-cache" in r.headers.get("Cache-Control", "") and "immutable" not in r.headers.get("Cache-Control", ""),
              f"#1824: {u} without ?v= is revalidated {r.headers.get('Cache-Control')!r}")
        ct = r.headers.get("Content-Type", "")
        check(("javascript" in ct if u.endswith(".js") else "text/css" in ct), f"#1824: {u} content type {ct!r}")
        r2 = s.get(B + u + "?v=" + (v or ""))
        cc = r2.headers.get("Cache-Control", "")
        check(r2.ok and "immutable" in cc and "max-age=31536000" in cc, f"#1824: {u}?v=<hash> immutable ({who}, {cc!r})")
        et = r.headers.get("ETag")
        r3 = s.get(B + u, headers={"If-None-Match": et or '"x"'})
        check(et and r3.status_code == 304 and not r3.content, f"#1824: {u} ETag {et!r} + If-None-Match = 304 ({r3.status_code})")
        r4 = s.head(B + u)
        check(r4.ok and int(r4.headers.get("Content-Length", -1)) == len(body), f"#1824: HEAD {u} ({r4.status_code} {r4.headers.get('Content-Length')})")
core = anon.get(B + "/static/js/core.js").text
check("function domReady(" in core and "'use strict';" in core, "#1824/#2505: the code itself is kept (core.js with domReady)")
css = anon.get(B + "/static/app.css").text
check(not re.search(r"/\*.*?\*/", css, re.S), "#1824: app.css has no comment left")

png = anon.get(B + "/static/icon-192.png")
check(png.ok and png.content == open(os.path.join(ROOT, "static", "icon-192.png"), "rb").read(), "#1824: an image goes out byte for byte")
vend = sorted(glob.glob(os.path.join(ROOT, "static", "vendor", "**", "*.js"), recursive=True) + glob.glob(os.path.join(ROOT, "static", "vendor", "**", "*.mjs"), recursive=True))
if vend:
    rel = os.path.relpath(vend[0], os.path.join(ROOT, "static")).replace(os.sep, "/")
    r = anon.get(B + "/static/" + rel)
    check(r.ok and r.content == open(vend[0], "rb").read(), f"#1824: static/vendor/ goes out byte for byte ({rel})")
r = anon.get(B + "/static/js/no-such-file.js")
check(r.status_code == 404, f"#1824: a missing file is 404 ({r.status_code})")
r = anon.get(B + "/static/%2e%2e/kalmido/core/strip.py", allow_redirects=False)
check(r.status_code in (303, 400, 404) and "def strip_js" not in r.text, f"#1824: no file outside static/ ({r.status_code})")
m = anon.get(B + "/sw-manifest.json").json().get("files") or {}
check(m.get("/static/js/core.js") == hashes.get("/static/js/core.js"), "#1824: the service worker manifest names the hash of the served bytes")
lazy = "/static/js/office.js"
if lazy in m:
    check(m[lazy] == hashlib.sha256(anon.get(B + lazy).content).hexdigest()[:12], "#1824: a module loaded on demand: hash of the served bytes")

print(f"p2191_b_strip: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
