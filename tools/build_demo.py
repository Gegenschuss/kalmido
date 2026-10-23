#!/usr/bin/env python3
"""Builds the browser demo of Kalmido ("Try it without an account") from the current sources: a static folder that runs
the real app (static/js/*.js, app.css, i18n) without any server. tools/demo/shim.js stands in for the API and keeps the
data in the visitor's browser (localStorage); tools/demo/texts.js holds the demo's own texts and the sample data in the
six app languages. The page forbids every network connection (CSP connect-src 'none'), has no analytics and no service
worker, and is marked noindex.

usage: build_demo.py [out_dir]     (default: demo/ next to app.py; the folder is replaced)
       build_demo.py --site URL    base URL of the website for the install links (default: "../", the demo lives in /demo/)

Every text replacement in the copied app must match (else the app changed and this script needs a look): the build
fails instead of shipping a demo that silently talks to a server."""
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
DEMO_SRC = os.path.join(ROOT, "tools", "demo")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; "
       "connect-src 'none'; manifest-src 'none'; worker-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; "
       "base-uri 'none'; form-action 'none'")


def fail(msg):
    sys.exit("build_demo: " + msg)


def replace(text, old, new, name, count=1, at_least=False):
    n = text.count(old)
    if (n < count) if at_least else (n != count):
        fail(f"{name}: expected {'at least ' if at_least else ''}{count}x {old[:70]!r}, found {n} -> the app changed, check this script")
    return text.replace(old, new)


# 2.125.0 D (#1653): keeping the demo current. The client's API calls (api / rawFetch with a literal method and path) against
# the routes of tools/demo/shim.js (on('METHOD', 'regex', ...), crud('/api/...', ...), the QUIET answers, the GATED pattern and
# the office's gated reads): what is left is listed as a warning after every build, the build itself goes on.
CALL_RE = re.compile(r"""(?:api|rawFetch|apiQ|apiRaw)\(\s*'(GET|POST|PATCH|PUT|DELETE)'\s*,\s*([`'"])(/api/(?:(?!\2).)*)\2""")


def shim_unknown(js, shim):
    """-> [(method, path, n)] of the client's API calls no route of the shim answers (path with ${...} as 1, no query)."""
    unesc = lambda r: r.replace("\\\\", "\\")  # noqa: E731 (a JS string: \\d = the regex \d)
    routes = [(m, re.compile("^" + unesc(r) + "$")) for m, r in re.findall(r"\bon\('(GET|POST|PATCH|PUT|DELETE)',\s*'([^']*)'", shim)]
    for base in re.findall(r"\bcrud\('(/api/[^']*)'", shim):
        b = unesc(base)
        routes += [("GET", re.compile("^" + b + "$")), ("POST", re.compile("^" + b + "$"))]
        routes += [(m, re.compile("^" + b + r"/(\d+)$")) for m in ("GET", "PATCH", "PUT", "DELETE")]
        routes.append(("POST", re.compile("^" + b + r"/(\d+)/restore$")))
    quiet = set(re.findall(r"'((?:GET|POST|PATCH|PUT|DELETE) /api/[^']*)'\s*:", shim))
    g = re.search(r"const GATED = /(.*)/;", shim)
    gated = re.compile(g.group(1).replace("\\/", "/")) if g else None
    calls = {}
    for m, _, p in CALL_RE.findall(js):
        p = re.sub(r"\$\{[^}]*\}", "1", p).split("?")[0]
        calls[(m, p)] = calls.get((m, p), 0) + 1
    out = []
    for (m, p), n in sorted(calls.items()):
        if f"{m} {p}" in quiet or (gated and gated.search(p)) or p.startswith("/api/office/") and m == "GET":
            continue
        if not any(rm == m and r.match(p) for rm, r in routes):
            out.append((m, p, n))
    return out


def main(argv):
    out, site = os.path.join(ROOT, "demo"), "../"
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--site":
            site = args.pop(0)
        elif a.startswith("-"):
            fail(f"unknown option {a}")
        else:
            out = os.path.abspath(a)
    if os.path.exists(out):
        if not os.path.isfile(os.path.join(out, "static", "shim.js")) and os.listdir(out):
            fail(f"{out} exists and is no demo build, not replacing it")
        shutil.rmtree(out)
    st = os.path.join(out, "static")
    os.makedirs(os.path.join(st, "i18n"))
    read = lambda p: open(p, encoding="utf-8").read()  # noqa: E731
    write = lambda p, s: open(p, "w", encoding="utf-8").write(s)  # noqa: E731

    # the app, with absolute /static/ paths made relative (the demo lives in a subfolder) and without the service worker
    # 2.20.0 (#646): the client's modules (static/js, order of the script tags in index.html) become ONE app.js here
    src_html = read(os.path.join(STATIC, "index.html"))
    mods = re.findall(r'<script src="/static/js/([\w-]+\.js)"(?: defer)?></script>', src_html)  # 2.191.0 B (#2505): defer
    if not mods:
        fail("index.html loads no static/js/ modules")
    app = "\n".join(read(os.path.join(STATIC, "js", m)) for m in mods)
    app = replace(app, "navigator.serviceWorker.register('/sw.js').catch(() => {});",
                  "Promise.resolve().catch(() => {});  /* demo build: no service worker */", "app.js")
    app = replace(app, "/static/", "static/", "app.js", count=5, at_least=True)
    if re.search(r"""['"`]/sw\.js""", app):
        fail("app.js still references /sw.js")
    # 2.125.0 D (#1653): the intro's "Start" (account.js setupChoices) reloads the page itself, not the site's root
    app = replace(app, "      else return;\n      location.replace('/');", "      else return;\n      location.reload();  /* demo build: the demo page itself */", "app.js")
    write(os.path.join(st, "app.js"), app)
    js_all = app
    # 2.53.1 (#1410): the modules loaded on demand (LAZY in sw.js, no script tag in index.html) stay own files: loadModule
    # fetches static/js/<name>.js relative to the demo page
    lazy = re.findall(r"'/static/js/([\w-]+\.js)'", (re.search(r"const LAZY = \[([^\]]*)\]", read(os.path.join(STATIC, "sw.js"))) or fail("sw.js has no LAZY list")).group(1))
    os.makedirs(os.path.join(st, "js"), exist_ok=True)
    for m in lazy:
        write(os.path.join(st, "js", m), read(os.path.join(STATIC, "js", m)))
        js_all += "\n" + read(os.path.join(STATIC, "js", m))
    # 2.65.0 (#1824): their stylesheets (LAZY_CSS in sw.js, static/css/) stay own files as well: loadModule loads them
    # beside the module, and a missing one would stop the module from loading in the demo
    lcss = re.search(r"const LAZY_CSS = \[([^\]]*)\]", read(os.path.join(STATIC, "sw.js")))
    if lcss:
        os.makedirs(os.path.join(st, "css"), exist_ok=True)
        for f in re.findall(r"'/static/css/([\w-]+\.css)'", lcss.group(1)):
            write(os.path.join(st, "css", f), read(os.path.join(STATIC, "css", f)))
    i18n = read(os.path.join(STATIC, "i18n.js"))
    write(os.path.join(st, "i18n.js"), replace(i18n, "/static/i18n/", "static/i18n/", "i18n.js"))
    css = read(os.path.join(STATIC, "app.css"))
    write(os.path.join(st, "app.css"), replace(css, 'url("/static/', 'url("', "app.css", count=2, at_least=True))
    # 2.18.0 (#394): + the favicons and the Apple touch icon that index.html links
    for f in ("icon.svg", "icon-192.png", "favicon.svg", "favicon-16.png", "favicon-32.png", "apple-touch-icon.png"):
        shutil.copy2(os.path.join(STATIC, f), st)
    for d in ("fonts", "avatars"):
        shutil.copytree(os.path.join(STATIC, d), os.path.join(st, d))
    # translations + celebration one-liners as scripts (the page may not fetch anything; the shim loads them as <script>)
    langs = []
    for f in sorted(os.listdir(os.path.join(STATIC, "i18n"))):
        if f.endswith(".json"):
            code = f[:-5]
            data = json.load(open(os.path.join(STATIC, "i18n", f), encoding="utf-8"))
            write(os.path.join(st, "i18n", code + ".js"),
                  f"(window.KDEMO_I18N = window.KDEMO_I18N || {{}})[{json.dumps(code)}] = {json.dumps(data, ensure_ascii=False, separators=(',', ':'))};\n")
            langs.append(code)
    quips = json.load(open(os.path.join(STATIC, "quips.json"), encoding="utf-8"))
    write(os.path.join(st, "demo-quips.js"), "window.KDEMO_QUIPS = " + json.dumps(quips, ensure_ascii=False, separators=(",", ":")) + ";\n")
    write(os.path.join(st, "demo-site.js"), "window.KDEMO_SITE = " + json.dumps(site) + ";\n")
    for f in ("shim.js", "texts.js", "demo.css"):
        shutil.copy2(os.path.join(DEMO_SRC, f), st)
    texts = read(os.path.join(DEMO_SRC, "texts.js"))
    for code in ["en"] + langs:
        if not re.search(rf"^  {code}: \{{", texts, re.M):
            fail(f"tools/demo/texts.js has no texts for {code}")

    # the page: the app's index.html, relative paths, no manifest, CSP + noindex, the demo scripts before the app
    html = src_html.replace('.js" defer></script>', '.js"></script>')  # 2.191.0 B (#2505): the demo keeps plain script tags
    html = replace(html, "".join(f'<script src="/static/js/{m}"></script>\n' for m in mods), '<script src="/static/app.js"></script>\n', "index.html")
    html = replace(html, '<link rel="manifest" href="/manifest.json" crossorigin="use-credentials">\n', "", "index.html")
    html = replace(html, "<title>Kalmido</title>",
                   f'<title>Kalmido Demo</title>\n<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
                   '<meta name="robots" content="noindex, nofollow">\n<meta name="referrer" content="no-referrer">', "index.html")
    html = replace(html, '"/static/', '"static/', "index.html", count=5, at_least=True)
    html = replace(html, '<link rel="stylesheet" href="static/app.css">',
                   '<link rel="stylesheet" href="static/app.css">\n<link rel="stylesheet" href="static/demo.css">', "index.html")
    html = replace(html, '<script src="static/i18n.js"></script>',
                   '<script src="static/demo-site.js"></script>\n<script src="static/demo-quips.js"></script>\n'
                   '<script src="static/texts.js"></script>\n<script src="static/shim.js"></script>\n<script src="static/i18n.js"></script>', "index.html")
    if "/static/" in html or 'rel="manifest"' in html:
        fail("index.html still has absolute paths or the manifest")
    write(os.path.join(out, "index.html"), html)
    # Apache (the website): the same policy as a header, replacing the site's own CSP for this folder
    write(os.path.join(out, ".htaccess"),
          "# Kalmido browser demo (generated by tools/build_demo.py): no network connections, no indexing\n"
          "<IfModule mod_headers.c>\n"
          f'  Header always set Content-Security-Policy "{CSP}; frame-ancestors \'none\'"\n'
          '  Header always set X-Robots-Tag "noindex, nofollow"\n'
          '  Header always set Cache-Control "no-cache"\n'
          "</IfModule>\n")
    unknown = shim_unknown(js_all, read(os.path.join(DEMO_SRC, "shim.js")))
    if unknown:
        print(f"build_demo: warning: {len(unknown)} API calls of the app have no stand-in in tools/demo/shim.js (a read answers "
              "with the \"not in the demo yet\" line, a write with the notice; add a route there):")
        for m, p, n in unknown:
            print(f"  unknown: {m} {p}  ({n})")
    n = sum(len(fs) for _, _, fs in os.walk(out))
    print(f"build_demo: {out} ({n} files, languages: en {' '.join(langs)})")


if __name__ == "__main__":
    main(sys.argv[1:])
