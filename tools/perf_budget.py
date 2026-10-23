#!/usr/bin/env python3
"""2.65.0 (#1822): start-up performance budget, measured statically (standard library only).

Measures what the browser must fetch before the app shows anything, from static/index.html: every <script src> (size raw and
gzip level 6, count) and every <link rel="stylesheet"> (raw and gzip). For comparison it lists what is loaded on demand
(LAZY / LAZY_CSS in static/sw.js). The limits live in tools/perf_budget.json; going over one makes this tool exit 1.
The load time limit `start_ms` is not measured here; tests/perf_ui.js checks it in the browser.

usage: python3 tools/perf_budget.py [--json] [--budget FILE] [--root DIR]
"""
import gzip
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
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


def pbg_sizes(root, urls):
    raw = gz = n = 0
    for u in urls:
        p = pbg_local(root, u)
        if not p:
            continue
        data = pbg_read(p)
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


def pbg_i18n(root, code="de"):
    """2.191.0 A (#2518): the language texts of the start = the core of <code>.json (kalmido/core/i18nkeys.py, as the server
    splits it); the texts of the modules come with them. Measured only (no limit in perf_budget.json yet)."""
    import importlib.util
    path, kp = os.path.join(root, "static", "i18n", code + ".json"), os.path.join(root, "kalmido", "core", "i18nkeys.py")
    if not os.path.isfile(path) or not os.path.isfile(kp):
        return {}
    spec = importlib.util.spec_from_file_location("i18nkeys", kp)
    keys = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(keys)
    core, parts = keys.split_lang(json.loads(pbg_read(path)), keys.module_keys(root)[0])
    enc = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()  # noqa: E731 (as the server sends it)
    c, p = enc(core), [enc(x) for x in parts.values()]
    return {"start_i18n_bytes": len(c), "start_i18n_gzip": len(gzip.compress(c, 6)), "lazy_i18n_bytes": sum(map(len, p)),
            "lazy_i18n_parts": len(p), "i18n_file_bytes": os.path.getsize(path)}


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
    got.update(pbg_i18n(root))  # 2.191.0 A (#2518)
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
        if "start_i18n_bytes" in got:  # 2.191.0 A (#2518)
            print(f"language texts (de): core at start {pbg_fmt(got['start_i18n_bytes'])} bytes ({pbg_fmt(got['start_i18n_gzip'])} gzip) "
                  f"of the file's {pbg_fmt(got['i18n_file_bytes'])}, {got['lazy_i18n_parts']} module parts {pbg_fmt(got['lazy_i18n_bytes'])} bytes")
    for k in over:
        print(f"Budget exceeded: {k} {pbg_fmt(got[k])} > {pbg_fmt(lim[k])} "
              f"(tools/perf_budget.json; raise it on purpose or make the start smaller)", file=sys.stderr)
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
