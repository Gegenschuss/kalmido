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
_LIT = {"'": re.compile(r"'(?:[^'\\]|\\.)*'", re.S), '"': re.compile(r'"(?:[^"\\]|\\.)*"', re.S),
        "`": re.compile(r"`(?:[^`\\]|\\.)*`", re.S)}
_WS = re.compile(r"[ \t\r\n]*")


def key_sources(root):
    """The files with keys, relative to root: the web client (static/js/), app.py and the server package (kalmido/)."""
    return (sorted(os.path.relpath(p, root) for p in glob.glob(os.path.join(root, "static", "js", "*.js"))) + ["app.py"]
            + sorted(os.path.relpath(p, root) for p in glob.glob(os.path.join(root, "kalmido", "**", "*.py"), recursive=True)))


def skip_ws(src, i):
    return _WS.match(src, i).end()


class BadLiteral(ValueError):
    """A string literal this reader cannot read (2.191.0 F2, #2518): the checker reports it, the split treats the call as
    dynamic (its key stays in the core)."""


# 2.191.0 F2 (#2518): JavaScript escapes read here (not with json.loads: \x41, \0, \u{1F600}, \' and a raw tab are fine in JS)
_JS_ESC = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
_JS_ESC_RX = re.compile(r"\\(?:x([0-9a-fA-F]{2})|u\{([0-9a-fA-F]{1,6})\}|u([0-9a-fA-F]{4})|(0(?![0-9])|\r\n|[\s\S]))")


def js_string(lit):
    """The value of a JavaScript string literal with its quotes ('…', "…", `…` without ${}); BadLiteral when it is none."""
    q, body = lit[0], lit[1:-1]
    if q == "`":
        if "${" in body.replace("\\\\", "").replace("\\$", ""):
            raise BadLiteral("template with ${}")
        body = body.replace("\r\n", "\n").replace("\r", "\n")
    elif "\n" in body.replace("\\\n", "").replace("\\\r\n", "") or "\r" in body.replace("\\\r", ""):
        raise BadLiteral("a line break inside a quoted string")

    def esc(m):
        x, cp, u, c = m.groups()
        if x or u:
            return chr(int(x or u, 16))
        if cp:
            if int(cp, 16) > 0x10FFFF:
                raise BadLiteral("code point out of range")
            return chr(int(cp, 16))
        if c in ("\n", "\r", "\r\n", "\u2028", "\u2029"):  # a line continuation
            return ""
        if c in "123456789xu" or (c == "0" and body[m.end():m.end() + 1].isdigit()):  # octal (not in strict mode), a broken \x / \u
            raise BadLiteral("escape \\" + c)
        return _JS_ESC.get(c, c)
    v = _JS_ESC_RX.sub(esc, body) if "\\" in body else body
    try:  # \uD83D\uDE00: a surrogate pair is one character
        return v.encode("utf-16", "surrogatepass").decode("utf-16") if any("\ud800" <= ch <= "\udfff" for ch in v) else v
    except UnicodeError:
        raise BadLiteral("a lone surrogate") from None


def key_literal(src, i, py):
    """The quoted string literal at src[i] -> (value, end); (None, i) when there is none (tr(name), an f-string).
    2.191.0 F2 (#2518): a literal that is not valid (or this reader does not know) raises BadLiteral; JavaScript template
    literals without ${} count as literals."""
    c = src[i:i + 1]
    rx = _LIT.get(c)
    m = rx.match(src, i) if rx else None
    if not m:
        return None, i
    lit = m.group(0)
    if c == "`" and "${" in lit:
        return None, i  # a template with a value: dynamic
    if py:
        if c == "`":
            return None, i
        try:
            v = ast.literal_eval(lit)
        except (SyntaxError, ValueError, MemoryError, RecursionError) as e:
            raise BadLiteral(str(e)) from None
        if not isinstance(v, str):
            raise BadLiteral("no text")
        return v, m.end()
    return js_string(lit), m.end()


def comment_line(src, pos, py):
    line = src[src.rfind("\n", 0, pos) + 1:pos].lstrip()
    return line.startswith("#") if py else line.startswith(("//", "*", "/*"))


def key_calls(src, py, bad=None):
    """Every key call of a source text: (fn, key, other, pos). key None = no literal (tr(name)); other = the second literal
    of trn / Nn_ (None: missing). 2.191.0 F2 (#2518): a literal this reader cannot read gives key / other None and lands in
    bad (a list of (pos, message)) when one is given."""
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
        key = other = None
        try:
            key, i = key_literal(src, skip_ws(src, pos + len(fn) + 1), py)
            if key is not None and fn in ("trn", "Nn_"):
                i = skip_ws(src, i)
                if src[i:i + 1] == ",":
                    other, i = key_literal(src, skip_ws(src, i + 1), py)
        except BadLiteral as e:
            if bad is not None:
                bad.append((pos, str(e)))
        yield fn, key, other, pos


# 2.191.0 F2 (#2518): every string literal of a file (not only those after tr): a start file may pick a key as a value
# (tr(open ? 'Collapse' : 'Expand')), the server hands keys to the client. Comments are skipped; a template literal's
# ${...} is read as code (templates nest), the template itself counts when it has no ${}.
_JS_TOK = re.compile(r"""//[^\n]*|/\*.*?\*/|'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|[`{}/]""", re.S)
_JS_RX = re.compile(r"/(?![*/])(?:[^/\\\n\[]|\\.|\[(?:[^\]\\\n]|\\.)*\])+/")  # a regular expression literal
_JS_RX_BEFORE = re.compile(r"(?:^|[(,=:\[!&|?{};+\-*%<>~^]|\b(?:return|typeof|case|do|else|in|of|void|delete|throw|yield|await))\s*$")
_JS_TPL = re.compile(r"(?:[^`\\$]|\\.|\$(?!\{))*", re.S)
_PY_TOK = re.compile(r"#[^\n]*|'''(?:[^\\']|\\.|'(?!''))*'''|" + r'"""(?:[^\\"]|\\.|"(?!""))*"""|' + r"'(?:[^'\\\n]|\\.)*'|"
                     + r'"(?:[^"\\\n]|\\.)*"', re.S)


def core_sources(root):
    """2.191.0 F2 (#2518): files outside key_sources whose string literals hold keys in the core: the language loader and the
    service worker (they run before / outside every module)."""
    return [os.path.join("static", "i18n.js"), os.path.join("static", "sw.js")]


def _py_literals(src, out):
    for m in _PY_TOK.finditer(src):
        lit = m.group(0)
        if lit[0] == "#":
            continue
        j = m.start()
        while j and src[j - 1] in "rRbBuUfF":
            j -= 1
        pre = src[j:m.start()].lower()
        if len(pre) > 2 or (j and (src[j - 1].isalnum() or src[j - 1] == "_")) or "b" in pre:
            continue
        q = 3 if lit[:3] in ("\'\'\'", '\"\"\"') else 1
        body = lit[q:-q]
        if "f" in pre:  # the literals inside its {...}
            for x in re.finditer(r"\{([^{}]+)\}", body):
                _py_literals(x.group(1), out)
            continue
        if "\\" not in body:
            out.add(body)
        elif "r" not in pre:
            try:
                out.add(ast.literal_eval(lit))
            except (SyntaxError, ValueError, MemoryError, RecursionError):
                pass


def str_literals(src, py):
    """The values of every string literal of a source text outside comments (a set)."""
    out = set()
    if py:
        _py_literals(src, out)
        return out
    depth, i, n = [], 0, len(src)  # depth: the open braces of each ${ we are in

    def tpl(j, whole):  # inside a template from j: -> where code goes on
        m = _JS_TPL.match(src, j)
        e = m.end()
        if src[e:e + 1] == "`":
            if whole:
                try:
                    out.add(js_string(src[whole - 1:e + 1]))
                except BadLiteral:
                    pass
            return e + 1
        if src[e:e + 2] == "${":
            depth.append(0)
            return e + 2
        return n
    while i < n:
        m = _JS_TOK.search(src, i)
        if not m:
            break
        t, i = m.group(0), m.end()
        c = t[0]
        if c in "'\"":
            try:
                out.add(js_string(t))
            except BadLiteral:
                pass
        elif c == "/":
            if _JS_RX_BEFORE.search(src[max(0, m.start() - 12):m.start()]):
                r = _JS_RX.match(src, m.start())
                if r:
                    i = r.end()
        elif c == "`":
            i = tpl(i, i)
        elif c == "{":
            if depth:
                depth[-1] += 1
        elif c == "}" and depth:
            if depth[-1]:
                depth[-1] -= 1
            else:
                depth.pop()
                i = tpl(i, 0)
    return out


def lazy_modules(lazyload_js):
    """LD_MODS of static/js/lazyload.js -> {module: [its files without .js]}."""
    m = re.search(r"const LD_MODS = \{(.*?)\n\};", lazyload_js, re.S)
    body = re.sub(r"//[^\n]*", "", m.group(1)) if m else ""
    return {x.group(1): re.findall(r"'([\w-]+)'", x.group(2)) for x in re.finditer(r"(\w+): \[(.*?)\]", body, re.S)}


def module_keys(root, uses=None):
    """-> ({key: module} of the keys only one module uses, {module: [files]}). 2.191.0 F2 (#2518): ValueError when LD_MODS
    names no module; a string literal of a file outside the modules (key_sources, core_sources) that is a key keeps it in
    the core; uses (a dict) gets {module: every key its files use with tr / trn}."""
    with open(os.path.join(root, "static", "js", "lazyload.js"), encoding="utf-8") as f:
        mods = lazy_modules(f.read())
    if not mods:
        raise ValueError("static/js/lazyload.js: no modules in LD_MODS")
    f2m = {}
    for m, files in mods.items():
        for fn in files:
            f2m.setdefault(fn + ".js", set()).add(m)
    core, use, lits = set(), {}, set()
    for rel in key_sources(root) + core_sources(root):
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        py = rel.endswith(".py")
        mm = None if py or os.path.dirname(rel) != os.path.join("static", "js") else f2m.get(os.path.basename(rel))
        if not mm:
            lits |= str_literals(src, py)
        if rel in core_sources(root):
            continue
        for fn, key, _, _ in key_calls(src, py):
            if key is None:
                continue
            if mm and fn in ("tr", "trn"):
                use.setdefault(key, set()).update(mm)
            else:
                core.add(key)
    if uses is not None:
        for k, v in use.items():
            for m in v:
                uses.setdefault(m, set()).add(k)
    return {k: next(iter(v)) for k, v in use.items() if len(v) == 1 and k not in core and k not in lits}, mods


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
