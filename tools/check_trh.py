#!/usr/bin/env python3
"""2.689.0 (#5125, rest of #4074 point 8): no unescaped value through tr() / trn() into HTML.

tr('{0} invites you', name) puts name into the translation as it is. Inside an HTML template literal (a `...` with markup that
ends up in innerHTML) a name, a title or a host typed by someone would become markup. trh() / trnh() (static/i18n.js) escape
every inserted value and keep the translation's own <b> / <code>. This check reads every template literal of the web client
(static/js/*.js) that holds markup and reports each ${tr( / ${trn( in it whose inserted values are not safe:

  safe   a number literal, x.length / x.size, Math.* / Number() / parseInt(), an esc(...) call (escaped already), a
         constant string, a template literal with markup (HTML built on purpose, its own ${} are the author's business),
         a translation of its own (tr('…'), trn('…', '…', n))
  not checked: a tr() inside another call's arguments (esc(tr(…)), a helper that takes a label) or inside an array / object
  literal (mapped through esc() later) - the code there decides
  else   reported: use trh / trnh (or esc() the value); a value that is HTML on purpose (a <b>…</b> built elsewhere)
         goes into tools/trh_ok.txt as "file|key|value" with a reason after #

usage: python3 tools/check_trh.py [--list]      exit 1 on findings (--list: print them all, also the allowed ones)
Standard library only.
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK_FILE = os.path.join(ROOT, "tools", "trh_ok.txt")
FNS = ("trn", "tr")  # trh / trnh escape themselves
TAG = re.compile(r"<[a-zA-Z/!]")
SAFE = (re.compile(r"-?\d+(\.\d+)?$"), re.compile(r"[\w$.\[\]()?]+\.(length|size)$"),
        re.compile(r"(Math\.\w+|Number|parseInt|parseFloat|Math\.round)\(.*\)$", re.S),
        re.compile(r"(esc|i18nEsc)\((.*)\)$", re.S))
_TOK = re.compile(r"""//[^\n]*|/\*.*?\*/|'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|[`{}/]""", re.S)
_RX = re.compile(r"/(?![*/])(?:[^/\\\n\[]|\\.|\[(?:[^\]\\\n]|\\.)*\])+/")
_RX_BEFORE = re.compile(r"(?:^|[(,=:\[!&|?{};+\-*%<>~^]|\b(?:return|typeof|case|do|else|in|of|void|delete|throw|yield|await))\s*$")
_TPL = re.compile(r"(?:[^`\\$]|\\.|\$(?!\{))*", re.S)


def templates(src):
    """Every template literal: (start, text of its literal parts, [positions of its ${ expressions], parent index)."""
    out, stack, depth, i, n = [], [], [], 0, len(src)  # stack: open templates (index into out); depth: braces per ${

    def tpl(j):  # inside the template on top of the stack from j: -> where code goes on
        m = _TPL.match(src, j)
        e = m.end()
        out[stack[-1]][1].append(src[j:e])
        if src[e:e + 1] == "`":
            stack.pop()
            return e + 1
        if src[e:e + 2] == "${":
            out[stack[-1]][2].append(e + 2)
            depth.append(0)
            return e + 2
        stack.pop()
        return n
    while i < n:
        m = _TOK.search(src, i)
        if not m:
            break
        t, i = m.group(0), m.end()
        c = t[0]
        if c == "/" and len(t) == 1:
            if _RX_BEFORE.search(src[max(0, m.start() - 12):m.start()]):
                r = _RX.match(src, m.start())
                if r:
                    i = r.end()
        elif c == "`":
            out.append([m.start(), [], [], stack[-1] if stack else None])
            stack.append(len(out) - 1)
            i = tpl(i)
        elif c == "{" and len(t) == 1:
            if depth:
                depth[-1] += 1
        elif c == "}" and len(t) == 1 and depth:
            if depth[-1]:
                depth[-1] -= 1
            else:
                depth.pop()
                i = tpl(i)
    return out


def call_args(src, i, tpl_only=False):
    """The top-level argument texts of the call whose '(' is at i, and the end (tpl_only: skip the template literal
    starting at i + 1 -> ([], its end)."""
    args, depth, j, start, n = [], 0, i + 1, i + 1, len(src)
    while j < n:
        c = src[j]
        if c in "'\"":
            m = re.compile(c + r"(?:[^" + c + r"\\\n]|\\.)*" + c).match(src, j)
            j = m.end() if m else j + 1
            continue
        if c == "`":  # a nested template: skip it as a whole, with its ${ }
            k, lvl = j + 1, 0
            while k < n:
                if src[k] == "\\":
                    k += 2
                    continue
                if src[k] == "`" and lvl == 0:
                    break
                if src[k:k + 2] == "${":
                    lvl += 1
                    k += 2
                    continue
                if src[k] == "}" and lvl:
                    lvl -= 1
                k += 1
            j = k + 1
            if tpl_only:
                return [], j
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                args.append(src[start:j].strip())
                return [a for a in args if a], j + 1
            depth -= 1
        elif c == "," and depth == 0:
            args.append(src[start:j].strip())
            start = j + 1
        j += 1
    return args, n


def safe(a):
    if a[:1] in "'\"":
        return True  # a constant: the author's text (with or without markup)
    if a[:1] == "`":
        return bool(TAG.search(a)) or "${" not in a  # markup built on purpose; ${…} text without markup = a finding
    if re.match(r"trn?\((['\"])(?:[^\\]|\\.)*?\1\s*(,\s*(['\"])(?:[^\\]|\\.)*?\3\s*,\s*[\w$.]+\s*)?\)$", a):
        return True  # a translation of its own (tr('Documents|folder'), trn('{0} file', '{0} files', n))
    return any(r.match(a) for r in SAFE)


def html(tpls, k):
    while k is not None:
        if TAG.search("".join(tpls[k][1])):
            return True
        k = tpls[k][3]
    return False


def expr_calls(src, e):
    """The tr / trn calls whose text lands directly in the template from the ${ expression starting at e: (position of
    the name, name). Not inside a nested template (checked on its own) and not inside another call's arguments (esc(…),
    a helper that escapes its label itself - the callee decides - nor in an array / object, which is mapped later)."""
    stack, j, n = [], e, len(src)  # stack: the name before every open ( [ {
    while j < n:
        c = src[j]
        if c in "'\"":
            m = re.compile(c + r"(?:[^" + c + r"\\\n]|\\.)*" + c).match(src, j)
            j = m.end() if m else j + 1
            continue
        if c == "`":
            _a, j = call_args(src, j - 1, tpl_only=True)
            continue
        if c in "([{":
            m = re.search(r"([\w$.]*)\s*$", src[max(0, j - 40):j])
            stack.append(m.group(1) if c == "(" else c)  # "" = a grouping ( ); [ / { = an array / object (mapped later)
        elif c in ")]}":
            if not stack:
                return
            stack.pop()
        elif c == "t" and not (src[j - 1:j].isalnum() or src[j - 1:j] in "_$."):
            m = re.compile(r"(trn|tr)\(").match(src, j)
            if m and not any(stack):  # inside a call's arguments (esc(…), sw(…, label)) or an array the code decides
                yield j, m.group(1)
        j += 1


def findings(path, src):
    tpls = templates(src)
    for k, (_s, _parts, exprs, _p) in enumerate(tpls):
        if not html(tpls, k):
            continue
        for e in exprs:
            for pos, fn in expr_calls(src, e):
                args, _end = call_args(src, pos + len(fn))
                vals = args[3:] if fn == "trn" else args[1:]
                bad = [a for a in vals if not safe(a)]
                if bad:
                    yield src.count("\n", 0, pos) + 1, fn, args[0] if args else "", bad, pos


def allowed():
    ok = set()
    if os.path.exists(OK_FILE):
        for ln in open(OK_FILE, encoding="utf-8"):
            ln = ln.split(" #", 1)[0].strip()
            if ln and not ln.startswith("#"):
                ok.add(ln)
    return ok


def main(argv):
    ok, seen, out, n_ok = allowed(), set(), [], 0
    for p in sorted(glob.glob(os.path.join(ROOT, "static", "js", "*.js"))):
        rel = os.path.relpath(p, ROOT)
        src = open(p, encoding="utf-8").read()
        for line, fn, key, bad, _pos in findings(rel, src):
            for a in bad:
                ident = f"{os.path.basename(rel)}|{key}|{a}"
                seen.add(ident)
                if ident in ok:
                    n_ok += 1
                    if "--list" in argv:
                        print(f"allowed {rel}:{line}: {fn}({key}, … {a})")
                    continue
                out.append(f"{rel}:{line}: ${{{fn}(}} inserts {a!r} into HTML unescaped - trh / trnh (or esc()), "
                           f"HTML on purpose: tools/trh_ok.txt")
    stale = sorted(ok - seen)
    for x in out:
        print(x)
    for x in stale:
        print(f"tools/trh_ok.txt: no longer found, remove: {x}")
    print(f"check_trh: {len(out)} finding(s), {n_ok} allowed, {len(stale)} stale")
    return 1 if out or stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
