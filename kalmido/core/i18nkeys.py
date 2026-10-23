"""2.191.0 A (#1410 #2518): the translation keys of the code and their split per module loaded on demand.

One reader of the keys for the checker (tools/i18n_check.py loads this file by its path) and the server (core/i18nparts.py):
every call of tr, trn (one, other, n), N_ and Nn_ (one, other) outside a comment line. English is the
source language, the literal English text is the key (see TRANSLATING.md).

The split (module_keys): a key belongs to a module loaded on demand (LD_MODS in static/js/lazyload.js) only when tr / trn
use it in the files of that one module and in no other file -- not in a start script, another module, a file outside the
modules or the server (the client translates texts of the server). A key a module only marks with N_ / Nn_ (a table whose
text code elsewhere may translate) and every key no file names (dynamic keys, _meta, _weekdays ...) stays in the core.
Only the standard library: the checker runs without the app."""
import ast
import glob
import json
import os
import re

KEY_FNS = ("trn", "tr", "Nn_", "N_")
_LIT = {"'": re.compile(r"'(?:[^'\\]|\\.)*'", re.S), '"': re.compile(r'"(?:[^"\\]|\\.)*"', re.S)}
_WS = re.compile(r"[ \t\r\n]*")


def key_sources(root):
    """The files with keys, relative to root: the web client (static/js/), app.py and the server package (kalmido/)."""
    return (sorted(os.path.relpath(p, root) for p in glob.glob(os.path.join(root, "static", "js", "*.js"))) + ["app.py"]
            + sorted(os.path.relpath(p, root) for p in glob.glob(os.path.join(root, "kalmido", "**", "*.py"), recursive=True)))


def skip_ws(src, i):
    return _WS.match(src, i).end()


def key_literal(src, i, py):
    """The quoted string literal at src[i] -> (value, end); (None, i) when there is none (tr(name), an f-string)."""
    rx = _LIT.get(src[i:i + 1])
    m = rx.match(src, i) if rx else None
    if not m:
        return None, i
    lit = m.group(0)
    if py:
        return ast.literal_eval(lit), m.end()
    body = lit[1:-1]
    if lit[0] == "'":
        body = body.replace("\\'", "'").replace('"', '\\"')
    return json.loads('"' + body + '"'), m.end()


def comment_line(src, pos, py):
    line = src[src.rfind("\n", 0, pos) + 1:pos].lstrip()
    return line.startswith("#") if py else line.startswith(("//", "*", "/*"))


def key_calls(src, py):
    """Every key call of a source text: (fn, key, other, pos). key None = no literal (tr(name)); other = the second literal
    of trn / Nn_ (None: missing)."""
    calls = []
    for fn in KEY_FNS:  # str.find: many times quicker than a regex over megabytes of code (the server splits at run time)
        i = src.find(fn + "(")
        while i >= 0:
            c = src[i - 1:i]
            if not c or not (c.isalnum() or c in "_.$"):
                calls.append((i, fn))
            i = src.find(fn + "(", i + 1)
    for pos, fn in sorted(calls):
        if src[max(0, pos - 9):pos].endswith(("function ", "def ")) or comment_line(src, pos, py):
            continue
        key, i = key_literal(src, skip_ws(src, pos + len(fn) + 1), py)
        other = None
        if key is not None and fn in ("trn", "Nn_"):
            i = skip_ws(src, i)
            if src[i:i + 1] == ",":
                other, i = key_literal(src, skip_ws(src, i + 1), py)
        yield fn, key, other, pos


def lazy_modules(lazyload_js):
    """LD_MODS of static/js/lazyload.js -> {module: [its files without .js]}."""
    m = re.search(r"const LD_MODS = \{(.*?)\n\};", lazyload_js, re.S)
    body = re.sub(r"//[^\n]*", "", m.group(1)) if m else ""
    return {x.group(1): re.findall(r"'([\w-]+)'", x.group(2)) for x in re.finditer(r"(\w+): \[(.*?)\]", body, re.S)}


def module_keys(root):
    """-> ({key: module} of the keys only one module uses, {module: [files]})."""
    with open(os.path.join(root, "static", "js", "lazyload.js"), encoding="utf-8") as f:
        mods = lazy_modules(f.read())
    f2m = {}
    for m, files in mods.items():
        for fn in files:
            f2m.setdefault(fn + ".js", set()).add(m)
    core, use = set(), {}
    for rel in key_sources(root):
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        py = rel.endswith(".py")
        mm = None if py or os.path.dirname(rel) != os.path.join("static", "js") else f2m.get(os.path.basename(rel))
        for fn, key, _, _ in key_calls(src, py):
            if key is None:
                continue
            if mm and fn in ("tr", "trn"):
                use.setdefault(key, set()).update(mm)
            else:
                core.add(key)
    return {k: next(iter(v)) for k, v in use.items() if len(v) == 1 and k not in core}, mods


def split_lang(d, mod_of):
    """A language file -> (core, {module: part}); the core names the modules with a part ("_mods")."""
    core, parts = {}, {}
    for k, v in d.items():
        m = mod_of.get(k)
        if m is None:
            core[k] = v
        else:
            parts.setdefault(m, {})[k] = v
    core["_mods"] = sorted(parts)
    return core, parts
