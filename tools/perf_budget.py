#!/usr/bin/env python3
"""2.65.0 (#1822): start-up performance budget, measured statically (standard library only).

Measures what the browser must fetch before the app shows anything, from static/index.html: every <script src> (size raw and
gzip level 6, count) and every <link rel="stylesheet"> (raw and gzip). For comparison it lists what is loaded on demand
(LAZY / LAZY_CSS in static/sw.js). The limits live in tools/perf_budget.json; going over one makes this tool exit 1.
The load time limit `start_ms` is not measured here; tests/perf_ui.js checks it in the browser.
2.191.0 B (#1824): measures the bytes as the server sends them (.js / .css without comments, kalmido/core/strip.py).

usage: python3 tools/perf_budget.py [--json] [--budget FILE] [--root DIR]
"""
import gzip
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location("pbg_strip", os.path.join(os.path.dirname(HERE), "kalmido", "core", "strip.py"))
pbg_strip = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pbg_strip)
KEYS = ("start_js_bytes", "start_js_gzip", "start_css_bytes", "start_css_gzip", "start_scripts")


def pbg_read(path):
    with open(path, "rb") as f:
        return f.read()


def pbg_local(root, url):
    """Map a /static/... url to a file below root; None for anything else (external, data:, missing)."""
    url = url.split("?")[0].split("#")[0]
    if not url.startswith("/static/"):
        return None
    p = os.path.join(root, url.lstrip("/"))
    return p if os.path.isfile(p) else None


def pbg_served(root, path):
    """2.191.0 B (#1824): the bytes of a static file as they go out."""
    data = pbg_read(path)
    rel = os.path.relpath(path, os.path.join(root, "static")).replace(os.sep, "/")
    out = pbg_strip.strip_asset(rel, data)
    return data if out is None else out


def pbg_sizes(root, urls):
    raw = gz = n = 0
    for u in urls:
        p = pbg_local(root, u)
        if not p:
            continue
        data = pbg_served(root, p)
        raw += len(data)
        gz += len(gzip.compress(data, 6))
        n += 1
    return raw, gz, n


def pbg_measure(root):
    html = pbg_read(os.path.join(root, "static", "index.html")).decode("utf-8")
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    js = re.findall(r'<script\b[^>]*\bsrc="([^"]+)"', html)
    css = [m.group(1) for m in (re.search(r'href="([^"]+)"', t) for t in re.findall(r"<link\b[^>]*>", html)
                                 if re.search(r'rel="stylesheet"', t)) if m]
    sw = pbg_read(os.path.join(root, "static", "sw.js")).decode("utf-8")

    def lst(name):
        m = re.search(name + r" = \[(.*?)\];", sw, re.S)
        return re.findall(r"'(/static/[^']+)'", m.group(1)) if m else []

    jr, jg, jn = pbg_sizes(root, js)
    cr, cg, _ = pbg_sizes(root, css)
    lr, lg, ln = pbg_sizes(root, lst("LAZY"))
    xr, xg, xn = pbg_sizes(root, lst("LAZY_CSS"))
    return {"start_js_bytes": jr, "start_js_gzip": jg, "start_css_bytes": cr, "start_css_gzip": cg, "start_scripts": jn,
            "lazy_js_bytes": lr, "lazy_js_gzip": lg, "lazy_scripts": ln,
            "lazy_css_bytes": xr, "lazy_css_gzip": xg, "lazy_css_files": xn}


def pbg_fmt(n):
    return f"{n:,}".replace(",", ".")


def main(argv):
    as_json = "--json" in argv
    budget = os.path.join(HERE, "perf_budget.json")
    root = os.path.dirname(HERE)
    for flag in ("--budget", "--root"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 >= len(argv):
                print(f"{flag} needs a value", file=sys.stderr)
                return 2
            if flag == "--budget":
                budget = argv[i + 1]
            else:
                root = argv[i + 1]
    got = pbg_measure(root)
    with open(budget, encoding="utf-8") as f:
        lim = json.load(f)
    over = [k for k in KEYS if k in lim and got[k] > lim[k]]
    if as_json:
        print(json.dumps({"measured": got, "limits": {k: lim.get(k) for k in KEYS + ("start_ms",)}, "over": over}, indent=2))
    else:
        print(f"{'value':<18}{'actual':>14}{'limit':>14}")
        for k in KEYS:
            print(f"{k:<18}{pbg_fmt(got[k]):>14}{pbg_fmt(lim[k]) if k in lim else '-':>14}")
        print(f"on demand (not in the start): {got['lazy_scripts']} scripts {pbg_fmt(got['lazy_js_bytes'])} bytes "
              f"({pbg_fmt(got['lazy_js_gzip'])} gzip), {got['lazy_css_files']} stylesheets {pbg_fmt(got['lazy_css_bytes'])} bytes")
    for k in over:
        print(f"Budget exceeded: {k} {pbg_fmt(got[k])} > {pbg_fmt(lim[k])} "
              f"(tools/perf_budget.json; raise it on purpose or make the start smaller)", file=sys.stderr)
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
