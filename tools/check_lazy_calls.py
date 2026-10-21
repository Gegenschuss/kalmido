#!/usr/bin/env python3
"""2.149.0 F (#2519): a start file must not call a function that only a module loaded on demand defines, unguarded.

On a fresh device (empty cache) the module is not there yet: such a call throws a ReferenceError. The lists come from where
they are kept (see tools/check_layout.py): the start files = the <script> tags of static/index.html, the files loaded on
demand = LD_MODS in static/js/lazyload.js. A call of a name that only a lazy file declares is fine when

  * lazyload.js gives it a stand-in (LD_CALL, LD_NOP, LD_VIEW) or a start file assigns window.<name> = …
  * it is guarded: `typeof name`, `window.name`, `name?.(`, `loadModule(` / `LD_DONE` on the line or up to four lines
    before it (a typeof of another name of the same lazy file counts too)
  * it is marked as wanted: a comment `// lazy-ok: <reason>` on the line (or alone on the line before), e.g. when the
    caller only runs while the module is loaded (a click on what the module drew); inside a template literal as
    `${''/* lazy-ok: <reason> */}`; for a run of lines: `// lazy-ok-begin: <reason>` … `// lazy-ok-end`; for a whole start file that only works
    inside one module (its helpers run from that module's views): `// lazy-ok-module <module>: <reason>` once in the file

Also (#2519): every var(--x) without a fallback in static/ (CSS, JS, HTML) names a custom property that is defined
somewhere (a `--x:` in CSS, a style="--x:…" / setProperty('--x') / {'--x': …} in JS or HTML).

usage: python3 tools/check_lazy_calls.py [-v] [--root DIR]      exit code 1 on a finding
"""
import glob
import os
import re
import sys

DEF_RE = re.compile(r"(?:^|[^\w$.])(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\("
                    r"|(?:^|[^\w$.])(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\(|[A-Za-z_$][\w$]*\s*=>|function)")
TOP_RE = re.compile(r"^(?:async\s+)?(?:function\s*\*?\s*|class\s+|(?:const|let|var)\s+)([A-Za-z_$][\w$]*)", re.M)
WIN_RE = re.compile(r"window\.([A-Za-z_$][\w$]*)\s*=(?!=)")
OK_RE = re.compile(r"\blazy-ok:\s*\S")
BEGIN_RE, END_RE = re.compile(r"//\s*lazy-ok-begin:\s*\S"), re.compile(r"//\s*lazy-ok-end\b")
OKMOD_RE = re.compile(r"//\s*lazy-ok-module\s+([\w-]+):\s*\S")


def read(root, *p):
    with open(os.path.join(root, *p), encoding="utf-8") as f:
        return f.read()


def lists(root):
    idx = re.sub(r"<!--.*?-->", "", read(root, "static", "index.html"), flags=re.S)
    start = re.findall(r'<script\b[^>]*\bsrc="/static/(js/[\w-]+\.js)', idx)
    lz = read(root, "static", "js", "lazyload.js")
    m = re.search(r"const LD_MODS = \{(.*?)\n\};", lz, re.S)
    mods = {k: [f"js/{f}.js" for f in re.findall(r"'([\w-]+)'", v)]
            for k, v in re.findall(r"([\w$]+):\s*\[([^\]]*)\]", re.sub(r"//[^\n]*", "", m.group(1)))} if m else {}
    lazy = [f for fs in mods.values() for f in fs]
    prot = set()
    for key in ("LD_CALL", "LD_NOP"):
        m = re.search(r"const " + key + r" = \{(.*?)\};", lz, re.S)
        if m:
            prot |= set(re.findall(r"'([A-Za-z_$][\w$]*)'", re.sub(r"//[^\n]*", "", m.group(1))))
    m = re.search(r"const LD_VIEW = \{(.*?)\};", lz, re.S)
    if m:
        prot |= set(re.findall(r"([A-Za-z_$][\w$]*):\s*\[", re.sub(r"//[^\n]*", "", m.group(1))))
    return start, lazy, prot, mods


def blank(src):
    """The source with comments and the text of string literals replaced by spaces (newlines and the code inside a
    template's ${…} stay), so a word in a text or a comment never counts as a call. Regular expression literals are told
    from a division by the character before them (good enough for this check)."""
    out, i, n = list(src), 0, len(src)
    stack = []  # open template literals: the brace depth inside their ${…}
    depth = 0
    prev = ""  # last significant code character

    def wipe(a, b):
        for j in range(a, b):
            if out[j] != "\n":
                out[j] = " "
    while i < n:
        c = src[i]
        if c == "/" and src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            wipe(i, j); i = j; continue
        if c == "/" and src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            wipe(i, j); i = j; continue
        if c in "'\"" or (c == "/" and (not prev or prev in "(,=:[!&|?{};+-*%<>~^" or re.search(r"\b(?:return|typeof|case|in|of)\s*$", src[max(0, i - 8):i]))):
            j = i + 1
            cls = False
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 2; continue
                if c == "/" and src[j] == "[":
                    cls = True
                elif c == "/" and src[j] == "]":
                    cls = False
                elif src[j] == c and not cls:
                    break
                j += 1
            wipe(i + 1, j); i = j + 1; prev = "a"; continue
        if c == "`" or (c == "}" and stack and stack[-1] == depth):
            if c == "}":
                stack.pop()
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2; continue
                if src[j] == "`":
                    break
                if src.startswith("${", j):
                    break
                j += 1
            wipe(i + 1, j)
            if j < n and src[j] == "$":
                stack.append(depth); i = j + 2; prev = "{"; continue
            i = j + 1; prev = "a"; continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if not c.isspace():
            prev = c
        i += 1
    return "".join(out)


def shadowed(text, n):
    """Is n also a local name of this file (a variable, a parameter)? Then a call of it is most likely the local one."""
    e = re.escape(n)
    return bool(re.search(r"(?:const|let|var)\s+(?:[\w$]+\s*=[^;]*?,\s*)*[{\[]?[^;=]*?(?<![\w$])" + e + r"\b"
                          r"|(?<![\w$.])" + e + r"\s*=>|[(,]\s*(?:\.\.\.)?" + e + r"\s*[,)=]|\bcatch\s*\(\s*" + e + r"\b", text))


def lazy_calls(root):
    start, lazy, prot, mods = lists(root)
    start_defs, start_win = set(), set()
    texts = {}
    for f in start:
        t = texts[f] = read(root, "static", f)
        start_defs |= {a or b for a, b in DEF_RE.findall(t)} | set(TOP_RE.findall(t))
        start_win |= set(WIN_RE.findall(t))
    owner, tops = {}, {}
    for f in lazy:
        p = os.path.join(root, "static", f)
        if not os.path.isfile(p):
            continue
        t = read(root, "static", f)
        tops[f] = set(TOP_RE.findall(t))
        for n in {a or b for a, b in DEF_RE.findall(t)} | set(WIN_RE.findall(t)):
            owner.setdefault(n, set()).add(f)
    only = {n: fs for n, fs in owner.items() if n not in start_defs and n not in start_win and n not in prot}
    if not only:
        return [], len(start), len(lazy)
    call = re.compile(r"(?<![\w$.'\"`])(" + "|".join(sorted(map(re.escape, only), key=len, reverse=True)) + r")\s*\(")
    hits = []
    for f in start:
        lines = texts[f].split("\n")
        btext = blank(texts[f])  # without comments and string texts (a name in a text is no declaration)
        code = btext.split("\n")
        for mod in OKMOD_RE.findall(texts[f]):
            if mod not in mods:
                hits.append((f, 0, mod, "-", "lazy-ok-module names a module that LD_MODS does not know"))
        okf = {x for mod in OKMOD_RE.findall(texts[f]) for x in mods.get(mod, [])}  # files of the modules the file names
        block = False
        for k, line in enumerate(lines):
            s = line.strip()
            if BEGIN_RE.search(line):
                block = True
            elif END_RE.search(line):
                block = False
            if block or OK_RE.search(line) or (k and re.match(r"\s*//\s*lazy-ok:\s*\S", lines[k - 1])):
                continue
            for m in call.finditer(code[k]):
                n = m.group(1)
                if only[n] <= okf:
                    continue
                if re.search(r"function\s*\*?\s*" + re.escape(n) + r"\s*\(", line) or shadowed(btext, n):
                    continue
                ctx = "\n".join(lines[max(0, k - 4):k + 1])
                sib = set().union(*(tops.get(x, set()) for x in only[n])) | {n}
                alt = "|".join(sorted(map(re.escape, sib)))
                if re.search(r"typeof\s+(?:window\.)?(?:" + alt + r")\b|window\.(?:" + alt + r")\b|" + re.escape(n)
                             + r"\?\.\(|loadModule\(|LD_DONE\b", ctx):
                    continue
                hits.append((f, k + 1, n, ",".join(sorted(os.path.basename(x) for x in only[n])), s[:140]))
    return hits, len(start), len(lazy)


def css_vars(root):
    """var(--x) without a fallback whose --x is defined nowhere in static/."""
    used, defined = [], set()
    for p in sorted(glob.glob(os.path.join(root, "static", "**", "*.*"), recursive=True)):
        if not p.endswith((".css", ".js", ".html")):
            continue
        with open(p, encoding="utf-8") as fh:
            t = fh.read()
        rel = os.path.relpath(p, os.path.join(root, "static"))
        defined |= set(re.findall(r"(--[\w-]+)\s*:", t))
        defined |= set(re.findall(r"""['"`](--[\w-]+)['"`]""", t))  # setProperty('--x', …), {'--x': …}
        for k, line in enumerate(t.split("\n")):
            for m in re.finditer(r"var\(\s*(--[\w-]+)\s*\)", line):
                used.append((rel, k + 1, m.group(1)))
    return [(f, k, v) for f, k, v in used if v not in defined]


def main(argv):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]
    hits, ns, nl = lazy_calls(root)
    undef = css_vars(root)
    for f, k, n, d, s in hits:
        if d == "-":
            print(f"static/{f}: {s}: {n}", file=sys.stderr)
            continue
        print(f"static/{f}:{k}: {n}() is only defined in {d} (loaded on demand): guard it (typeof / a stand-in in "
              f"lazyload.js LD_CALL) or mark it `// lazy-ok: <reason>`  | {s}", file=sys.stderr)
    for f, k, v in undef:
        print(f"static/{f}:{k}: var({v}) has no fallback and {v} is defined nowhere", file=sys.stderr)
    if "-v" in argv or not (hits or undef):
        print(f"lazy calls: {ns} start files, {nl} files on demand, {len(hits)} unguarded; css variables: {len(undef)} undefined")
    return 1 if hits or undef else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
