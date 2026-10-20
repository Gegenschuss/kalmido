#!/usr/bin/env python3
"""The global names of the web client for ESLint's no-undef (2.126.0, #1993; see eslint.config.js in the repository root).

The classic scripts static/i18n.js + static/js/*.js share ONE global scope in the browser, so a name one file declares at
its top level is defined for all others. This script collects those top-level declarations (function, async function,
class, var / let / const incl. several declarators and destructuring, and every `window.X =` / `globalThis.X =`) and
writes them to tools/eslint_globals.json, which eslint.config.js reads. It needs no package: a small scanner skips
strings, template literals, comments and regular expressions and tracks the bracket depth.
static/sw.js is a service worker with its own scope and is not part of the list.

usage: python3 tools/eslint_globals.py           write tools/eslint_globals.json
       python3 tools/eslint_globals.py --check   exit code 1 if the file is not current (CI)
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tools", "eslint_globals.json")
FILES = ["static/i18n.js"] + sorted(os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "static", "js", "*.js")))

IDENT = re.compile(r"[A-Za-z_$][\w$]*")
# after these words a / starts a regular expression, not a division
RX_WORDS = {"return", "typeof", "case", "in", "of", "new", "delete", "void", "throw", "instanceof", "do", "else", "yield", "await"}
GLOBAL_OBJ = {"window", "globalThis", "self"}


def tokens(src):
    """Yield (kind, text, depth) for the code tokens of one file; kind: id, punct. Strings etc. are skipped."""
    i, n, depth = 0, len(src), 0
    prev = ""  # previous significant token (for the regex / division decision)
    tpl = []  # bracket depth at which each open template literal's ${ started
    while i < n:
        ch = src[i]
        if ch in " \t\r\n":
            i += 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif ch in "'\"":
            i = _skip_str(src, i, ch)
            prev = "str"
        elif ch == "`" or (ch == "}" and tpl and tpl[-1] == depth):
            if ch == "}":
                tpl.pop()
            i, opened = _skip_tpl(src, i + 1)
            if opened:
                tpl.append(depth)
            prev = "str"
        elif ch == "/" and (prev in ("", "punct") or prev in RX_WORDS):
            i = _skip_rx(src, i)
            prev = "str"
        elif ch.isalpha() or ch in "_$" or ord(ch) > 127:
            m = IDENT.match(src, i)
            if not m:
                i += 1
                continue
            word = m.group(0)
            yield "id", word, depth
            prev = word if word in RX_WORDS else "id"
            i = m.end()
        elif ch.isdigit():
            m = re.compile(r"[\w.]+").match(src, i)
            i = m.end()
            prev = "id"
        else:
            if ch in "([{":
                yield "punct", ch, depth
                depth += 1
            elif ch in ")]}":
                depth -= 1
                yield "punct", ch, depth
            else:
                yield "punct", ch, depth
            prev = "id" if ch in ")]" else "punct"
            i += 1


def _skip_str(src, i, q):
    i += 1
    while i < len(src) and src[i] != q:
        i += 2 if src[i] == "\\" else 1
    return i + 1


def _skip_tpl(src, i):
    """Skip a template literal part from i; return (index after it, True if it stopped at a ${)."""
    while i < len(src):
        if src[i] == "\\":
            i += 2
        elif src[i] == "`":
            return i + 1, False
        elif src.startswith("${", i):
            return i + 2, True
        else:
            i += 1
    return i, False


def _skip_rx(src, i):
    i += 1
    cls = False
    while i < len(src) and src[i] != "\n":
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            cls = True
        elif c == "]":
            cls = False
        elif c == "/" and not cls:
            i += 1
            break
        i += 1
    while i < len(src) and (src[i].isalnum()):
        i += 1  # flags
    return i


def names(src):
    """The top-level declared names of one script plus the names assigned to window.X / globalThis.X anywhere."""
    out = set()
    toks = list(tokens(src))
    n = len(toks)
    for k in range(n - 3):  # window.X = ... anywhere (also inside functions)
        if toks[k][0] == "id" and toks[k][1] in GLOBAL_OBJ and toks[k + 1][1] == "." and toks[k + 2][0] == "id" \
                and toks[k + 3][1] == "=" and not (k + 4 < n and toks[k + 4][1] in ("=", ">")) and (k == 0 or toks[k - 1][1] != "."):
            out.add(toks[k + 2][1])
    k = 0
    while k < n:
        kind, text, depth = toks[k]
        if depth == 0 and kind == "id" and (k == 0 or toks[k - 1][1] != "."):
            if text in ("function", "class") and k + 1 < n:
                j = k + 1
                if j < n and toks[j][1] == "*":
                    j += 1
                if j < n and toks[j][0] == "id" and not (text == "class" and toks[j][1] == "extends"):
                    out.add(toks[j][1])
            elif text in ("var", "let", "const"):
                k = _declarators(toks, k + 1, out)
                continue
        k += 1
    return out


def _declarators(toks, k, out):
    """Read the declarators of a top-level var / let / const from k; return the index after the statement."""
    n = len(toks)
    while k < n:
        kind, text, depth = toks[k]
        if kind == "id":
            out.add(text)
            k += 1
        elif text in "[{":  # destructuring: every identifier not followed by ':' and not a default value
            k = _pattern(toks, k, out)
        else:
            return k
        # skip the initialiser up to the next ',' or ';' at depth 0
        while k < n and not (toks[k][2] == 0 and toks[k][1] in ",;"):
            if toks[k][2] == 0 and toks[k][0] == "id" and toks[k][1] in ("function", "const", "let", "var", "class") \
                    and (toks[k - 1][1] in (")", "}", "]") or toks[k - 1][0] == "id" and toks[k - 1][1] not in ("async", "new")):
                return k  # no semicolon (ASI): the next statement starts
            k += 1
        if k >= n or toks[k][1] == ";":
            return k + 1
        k += 1  # the ','
    return k


def _pattern(toks, k, out):
    open_depth = toks[k][2]
    k += 1
    skip = 0  # inside a default value
    while k < len(toks):
        kind, text, depth = toks[k]
        if kind == "punct" and text in ")]}" and depth == open_depth:
            return k + 1
        if depth == open_depth + 1:
            if text == "=":
                skip = 1
            elif text == ",":
                skip = 0
        if kind == "id" and not skip and depth >= open_depth + 1:
            nxt = toks[k + 1][1] if k + 1 < len(toks) else ""
            if nxt != ":":
                out.add(text)
        k += 1
    return k


def collect():
    seen = set()
    for rel in FILES:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            seen |= names(f.read())
    return sorted(seen)


def render(lst):
    return json.dumps({"//": "generated by tools/eslint_globals.py (2.126.0, #1993) - do not edit, run the script",
                       "globals": lst}, indent=0, ensure_ascii=False) + "\n"


def main():
    text = render(collect())
    if "--check" in sys.argv[1:]:
        try:
            with open(OUT, encoding="utf-8") as f:
                cur = f.read()
        except FileNotFoundError:
            cur = ""
        if cur != text:
            print("tools/eslint_globals.json is not current: run python3 tools/eslint_globals.py and commit the file")
            return 1
        print("eslint_globals: ok (%d names)" % (len(json.loads(text)["globals"])))
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print("eslint_globals: wrote %d names" % (len(json.loads(text)["globals"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
