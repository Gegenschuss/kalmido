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
    mods = re.findall(r'<script src="/static/js/([\w-]+\.js)"></script>', src_html)
    if not mods:
        fail("index.html loads no static/js/ modules")
    app = "\n".join(read(os.path.join(STATIC, "js", m)) for m in mods)
    app = replace(app, "navigator.serviceWorker.register('/sw.js').catch(() => {});",
                  "Promise.resolve().catch(() => {});  /* demo build: no service worker */", "app.js")
    app = replace(app, "/static/", "static/", "app.js", count=5, at_least=True)
    if re.search(r"""['"`]/sw\.js""", app):
        fail("app.js still references /sw.js")
    write(os.path.join(st, "app.js"), app)
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
    html = src_html
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
    n = sum(len(fs) for _, _, fs in os.walk(out))
    print(f"build_demo: {out} ({n} files, languages: en {' '.join(langs)})")


if __name__ == "__main__":
    main(sys.argv[1:])
