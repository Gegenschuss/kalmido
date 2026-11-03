#!/usr/bin/env python3
"""2.65.0 (#1822): start-up performance budget, measured statically (standard library only).

Measures what the browser must fetch before the app shows anything, from static/index.html: every <script src> (size raw and
gzip level 6, count) and every <link rel="stylesheet"> (raw and gzip). For comparison it lists what is loaded on demand
(LAZY / LAZY_CSS in static/sw.js). The limits live in tools/perf_budget.json; going over one makes this tool exit 1.
The load time limit `start_ms` is not measured here; tests/perf_ui.js checks it in the browser.
2.191.0 B (#1824): measures the bytes as the server sends them (.js / .css without comments, kalmido/core/strip.py).
2.476.0 (#3487): app.css counts with the start style files static/css/start-*.css the server sends behind it.

2.501.0 (#4198): --ratchet: the limits only go up when the same change lowers another one by as much (see pbg_ratchet).

usage: python3 tools/perf_budget.py [--json] [--budget FILE] [--root DIR] [--ratchet [BASE]]
"""
import gzip
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location("pbg_strip", os.path.join(os.path.dirname(HERE), "kalmido", "core", "strip.py"))
pbg_strip = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pbg_strip)
KEYS = ("start_js_bytes", "start_js_gzip", "start_css_bytes", "start_css_gzip", "start_i18n_bytes", "start_i18n_gzip", "start_scripts")
# 2.501.0 (#4198): the sums that must not grow against the base; a key the base does not have yet (a new limit) does not count
RATCHET = (("gzip", ("start_js_gzip", "start_css_gzip", "start_i18n_gzip")),
           ("bytes", ("start_js_bytes", "start_css_bytes", "start_i18n_bytes")),
           ("scripts", ("start_scripts",)))
SHRINK_HINT = ("make the start smaller: move a rarely used module behind a stand-in (static/js/lazyload.js LD_MODS / LD_CALL / LD_VIEW)")


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
    if rel == "app.css":  # 2.476.0 (#3487): the start style files go out behind app.css (one file for the browser)
        data = pbg_strip.with_start_css(os.path.join(root, "static"), data)
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


def pbg_git(root, *args):
    """stdout of a git command in root, None when it fails (no repo, unknown revision)."""
    try:
        p = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def pbg_ratchet_base(root):
    """2.501.0 (#4198): -> (base, why, red): what the limits are compared with, from the CI event (the same bases as
    tests/stages.py ci_base; that one answers None for its "full" stage and tools/ cannot import from tests/). base None:
    no comparison - red says whether that fails the check. Outside the CI (the train's lint replay on main + package) the
    base is the merge base with main; the CI proves the rule again, so a tree without git / main only says so."""
    ev = os.environ.get("GITHUB_EVENT_NAME", "")
    if ev in ("schedule", "workflow_dispatch"):
        return None, f"event {ev}: no change to compare", False
    if ev == "pull_request":
        return "HEAD^1", "pull request", True
    if ev == "push":
        if re.match(r"refs/heads/(job|hotfix)/", os.environ.get("GITHUB_REF", "")):
            if pbg_git(root, "rev-parse", "--verify", "-q", "origin/main^{commit}") is None:
                pbg_git(root, "fetch", "--no-tags", "origin", "main:refs/remotes/origin/main")
            return pbg_git(root, "merge-base", "origin/main", "HEAD"), "package branch against main", True
        before = os.environ.get("CI_BEFORE", "")
        if not before or set(before) == {"0"}:
            return None, "push without a previous commit", True
        if pbg_git(root, "cat-file", "-e", before + "^{commit}") is None:
            pbg_git(root, "fetch", "--no-tags", "--depth=1", "origin", before)
        return before, "push", True
    if ev:
        return None, f"unknown event {ev}", True
    for ref in ("main", "origin/main"):
        base = pbg_git(root, "merge-base", ref, "HEAD")
        if base:
            return base, f"merge base with {ref}", False
    return None, "no git history here", False


def pbg_ratchet_compare(old, new):
    """2.501.0 (#4198): the broken rules of limits NEW against OLD (net over the whole change, per sum), empty = fine."""
    bad = []
    for name, keys in RATCHET:
        common = [k for k in keys if k in old]
        gone = [k for k in common if k not in new]
        if gone:
            bad.append(f"{name}: limit removed: {', '.join(gone)}")
            continue
        a, b = sum(old[k] for k in common), sum(new[k] for k in common)
        if b > a:
            bad.append(f"{name}: sum of {' + '.join(common)} rose from {pbg_fmt(a)} to {pbg_fmt(b)} (+{pbg_fmt(b - a)})")
    return bad


def pbg_ratchet(root, lim, base=None):
    """2.501.0 (#4198): a limit may only rise when the same change lowers another by as much. The lowered limit has to hold the
    normal budget check as well, so the saving is real. -> exit code. An explicit BASE that cannot be read is always red;
    otherwise pbg_ratchet_base decides."""
    red = True
    why = "given on the command line"
    if base is None:
        base, why, red = pbg_ratchet_base(root)
    if not base:
        print(f"Budget ratchet: NOT COMPARED ({why})", file=sys.stderr if red else sys.stdout)
        return 1 if red else 0
    text = pbg_git(root, "show", f"{base}:tools/perf_budget.json")
    if text is None:
        print(f"Budget ratchet: NOT COMPARED, tools/perf_budget.json of {base} cannot be read ({why})", file=sys.stderr)
        return 1
    bad = pbg_ratchet_compare(json.loads(text), lim)
    for b in bad:
        print(f"Budget ratchet: {b}, against {base[:12]} ({why}). A limit only rises when the same change lowers another "
              f"one by as much; {SHRINK_HINT}", file=sys.stderr)
    if not bad:
        print(f"Budget ratchet: ok against {base[:12]} ({why})")
    return 1 if bad else 0


def main(argv):
    as_json = "--json" in argv
    ratchet, ratchet_base = "--ratchet" in argv, None
    if ratchet:
        i = argv.index("--ratchet")
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            ratchet_base = argv[i + 1]
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
    over = [k for k in KEYS if k in lim and k in got and got[k] > lim[k]]  # 2.501.0 (#4198): a tree without language files has no start_i18n_*
    if as_json:
        print(json.dumps({"measured": got, "limits": {k: lim.get(k) for k in KEYS + ("start_ms",)}, "over": over}, indent=2))
    else:
        print(f"{'value':<18}{'actual':>14}{'limit':>14}")
        for k in KEYS:
            if k in got:
                print(f"{k:<18}{pbg_fmt(got[k]):>14}{pbg_fmt(lim[k]) if k in lim else '-':>14}")
        print(f"on demand (not in the start): {got['lazy_scripts']} scripts {pbg_fmt(got['lazy_js_bytes'])} bytes "
              f"({pbg_fmt(got['lazy_js_gzip'])} gzip), {got['lazy_css_files']} stylesheets {pbg_fmt(got['lazy_css_bytes'])} bytes")
        if "start_i18n_bytes" in got:  # 2.191.0 A (#2518)
            print(f"language texts (de): core at start {pbg_fmt(got['start_i18n_bytes'])} bytes ({pbg_fmt(got['start_i18n_gzip'])} gzip) "
                  f"of the file's {pbg_fmt(got['i18n_file_bytes'])}, {got['lazy_i18n_parts']} module parts {pbg_fmt(got['lazy_i18n_bytes'])} bytes")
    for k in over:
        print(f"Budget exceeded: {k} {pbg_fmt(got[k])} > {pbg_fmt(lim[k])} "
              f"(tools/perf_budget.json; {SHRINK_HINT}; raising a limit needs an equal cut of another one in the same change)", file=sys.stderr)
    rc = 1 if over else 0
    if ratchet and pbg_ratchet(root, lim, ratchet_base):
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
