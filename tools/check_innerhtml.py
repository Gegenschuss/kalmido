#!/usr/bin/env python3
"""2.754.0 (#5297): every ${} in an HTML template of the web client is escaped, a safe helper, or marked.

A template literal with markup (a `...` holding <tag) ends up in innerHTML / insertAdjacentHTML / outerHTML. A ${value} in it
that is not escaped becomes markup when the value comes from a person (a name, a title, a host). Reads every template literal
of static/js/**/*.js that holds markup (the template reader of tools/check_trh.py) and checks each ${expr}:

  safe   esc(...) / i18nEsc(...) / escA(...) as a whole, trh / trnh (escape their values), tr('constant') (the author's text),
         a number literal, x.length / x.size, Math.* / Number() / parseInt() / (x|0), a constant string, a template literal
         with markup (own ${} are checked on their own), a call of a helper that builds escaped markup (SAFE_HELPERS),
         a ternary / || / && whose every branch is one of these, .map(... => `...`).join(...) (its template is checked)
  marked ${/*html-ok*/ expr} = HTML on purpose (built elsewhere from esc()); say in a comment why
  else   reported as a finding. Old findings are the baseline (tools/innerhtml_baseline.json, "file|expression" -> count,
         no line numbers); a NEW one is red. The baseline only ever shrinks: --update rewrites it (never adds).

usage: python3 tools/check_innerhtml.py [-v] [--update] [--selftest]      exit 1 on a new finding (a fixed one only shows as a note)
Standard library only.
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_trh as T  # noqa: E402  (template reader, call_args)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "tools", "innerhtml_baseline.json")
MARK = "/*html-ok*/"
# helpers whose result is markup built from escaped parts (checked at their definition) or plain safe text
SAFE_HELPERS = ("esc", "i18nEsc", "escA", "tr", "trn", "trh", "trnh", "icon", "ic", "svg", "sw")
NUM = re.compile(r"-?\d+(\.\d+)?$")
LEN = re.compile(r"[\w$.\[\]()?]+\.(length|size)$")
MATH = re.compile(r"(Math\.\w+|Number|parseInt|parseFloat)\(.*\)$", re.S)
MAPJ = re.compile(r"\.map\(.*=>\s*\(?\s*(`|esc\()", re.S)


def split_top(a, ops):
    """Split a on the top-level operators in ops (strings, brackets, templates skipped); ternary '?' ':' are kept apart."""
    parts, depth, j, start, n = [], 0, 0, 0, len(a)
    while j < n:
        c = a[j]
        if c in "'\"":
            m = re.compile(c + r"(?:[^" + c + r"\\\n]|\\.)*" + c).match(a, j)
            j = m.end() if m else j + 1
            continue
        if c == "`":
            _x, j = T.call_args(a, j - 1, tpl_only=True)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0:
            for op in ops:
                if a.startswith(op, j) and not (op == "?" and a[j + 1:j + 2] in ".?") and not (op == ":" and False):
                    parts.append(a[start:j])
                    start = j + len(op)
                    j = start - 1
                    break
        j += 1
    parts.append(a[start:])
    return [p.strip() for p in parts]


def safe(a):
    a = a.strip()
    if not a or MARK in a:
        return True
    if a[0] in "'\"":
        return len(split_top(a, ["+"])) == 1 or all(safe(p) for p in split_top(a, ["+"]))
    if a[0] == "`":
        return True  # a nested template inherits "markup" from its parent: its own ${} are checked on their own
    if a[0] == "(" and a[-1] == ")" and T.call_args(a, 0)[1] == len(a):
        return safe(a[1:-1])
    q = split_top(a, ["?"])
    if len(q) > 1:  # ternary: cond ? x : y  (the condition is no output)
        br = split_top(a[len(q[0]) + 1:], [":"])
        return all(safe(x) for x in ([br[0], ":".join(br[1:])] if len(br) > 1 else br))
    for op in ("||", "??", "&&"):
        p = split_top(a, [op])
        if len(p) > 1:  # for && the left side is only a condition
            return all(safe(x) for x in (p[1:] if op == "&&" else p))
    if NUM.match(a) or LEN.match(a) or MATH.match(a) or re.match(r"\(.*\|\s*0\)$", a):
        return True
    m = re.match(r"([\w$.]+)\(", a)
    if m and m.group(1) in SAFE_HELPERS and T.call_args(a, m.end() - 1)[1] == len(a):
        return True
    if MAPJ.search(a) and re.search(r"\.join\(", a):
        return True
    return False


def scan(src):
    """-> [(line, expression)] of the unsafe ${} in every markup template."""
    tpls = T.templates(src)
    for k, (_s, _parts, exprs, _p) in enumerate(tpls):
        if not T.html(tpls, k):
            continue
        for e in exprs:
            end = _expr_end(src, e)
            a = src[e:end]
            if not safe(a):
                yield src.count("\n", 0, e) + 1, re.sub(r"\s+", " ", a).strip()


def _expr_end(src, e):
    depth, j, n = 0, e, len(src)
    while j < n:
        c = src[j]
        if c in "'\"":
            m = re.compile(c + r"(?:[^" + c + r"\\\n]|\\.)*" + c).match(src, j)
            j = m.end() if m else j + 1
            continue
        if c == "`":
            _x, j = T.call_args(src, j - 1, tpl_only=True)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if c == "}" and depth == 0:
                return j
            depth -= 1
        j += 1
    return n


def collect():
    found = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "static", "js", "**", "*.js"), recursive=True)):
        rel = os.path.relpath(p, ROOT)
        for line, ex in scan(open(p, encoding="utf-8").read()):
            found.setdefault(f"{rel}|{ex}", []).append(line)
    return found


def selftest():
    bad = ["`<b>${name}</b>`", "`<i>${a.title + 'x'}</i>`", "`<p>${x ? name : ''}</p>`", "`<p>${list.join('')}</p>`"]
    good = ["`<b>${esc(name)}</b>`", "`<b>${n}</b>`".replace("n", "3"), "`<p>${x ? esc(a) : ''}</p>`",
            "`<p>${a.length}</p>`", "`<p>${trh('{0}', n)}</p>`", "`<p>${/*html-ok*/ h}</p>`",
            "`<p>${rows.map(r => `<i>${esc(r)}</i>`).join('')}</p>`", "`<p>${esc(a) || ''}</p>`", "`no markup ${x}`", "`<p>${v ? ` s=\"${esc(v)}\"` : ''}</p>`",
            "`<p>${tr('Hello')}</p>`", "`<p class=\"${on ? 'a' : 'b'}\">${esc(x)}</p>`"]
    f = 0
    for s in bad:
        if not list(scan(s)):
            print("selftest: not reported:", s)
            f += 1
    for s in good:
        r = list(scan(s))
        if r:
            print("selftest: wrongly reported:", s, r)
            f += 1
    print("check_innerhtml selftest:", "FAILED %d" % f if f else "ok")
    return 1 if f else 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    found = collect()
    base = json.load(open(BASE, encoding="utf-8")) if os.path.exists(BASE) else {}
    cnt = {k: len(v) for k, v in found.items()}
    if "--update" in argv:
        new = {k: min(v, base.get(k, v)) for k, v in cnt.items() if (k in base or not base)}
        json.dump(dict(sorted(new.items())), open(BASE, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
        print("check_innerhtml: baseline written,", len(new), "entries,", sum(new.values()), "findings")
        return 0
    out = []
    for k, n in sorted(cnt.items()):
        if n > base.get(k, 0):
            f, ex = k.split("|", 1)
            out.append(f"{f}:{found[k][-1]}: ${{{ex}}} in an HTML template is not escaped - esc() / tr() / trh(), "
                       f"HTML on purpose: ${{{MARK} …}}")
    stale = sorted(k for k, n in base.items() if cnt.get(k, 0) < n)
    for x in out:
        print(x)
    for k in stale:
        print(f"tools/innerhtml_baseline.json: fewer than recorded (good), `--update` shrinks the baseline: {k}")
    print(f"check_innerhtml: {len(out)} new finding(s), {sum(cnt.values())} in the baseline, {len(stale)} fixed since")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
