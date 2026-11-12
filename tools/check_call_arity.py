#!/usr/bin/env python3
"""2.1056.0 (#5863): every call of a module-level function of kalmido/ gets all its required parameters.

Two packages were merged side by side: #5491 gave otr_back (lists/listtrash.py) a new required parameter uid, the new caller
lists/otrundo.py (2.997) still called it with two arguments. Neither ruff nor the lint steps nor the einreihen check saw it; only
the full CI of 2.1024.0 did (two suites red, every undo of a delete a TypeError). This lint reads the signatures and the calls
with ast, no import, no database, in seconds - so it runs in the CI job Lint and in the einreihen check that replays it.

Signatures: every def / async def in the body of a module of kalmido/ (and app.py). Left out: a name defined twice or also
assigned at module level, a def under if / try, and a def with a decorator that may change its signature (only the ones in
KEEPS are known to keep it: the routes, functools.wraps wrappers, lru_cache ...).
Calls (in kalmido/ and app.py):
  - f(...) of a function of the same module or imported with `from <module> import f [as g]` (absolute or relative, at
    module level or inside a function; a re-export of another module is followed)
  - m.f(...) / kalmido.x.y.f(...) where m is a module (`import kalmido.x.y as m`, `from kalmido.x import y`, `from . import y`)
  - a name that is also bound otherwise in the file (an argument, an assignment, a loop variable, a nested def, two different
    imports) is not followed: then it may be something else
A finding: a required positional or keyword-only parameter without a value, more positional arguments than the function takes
(no *args), or a keyword it does not know (no **kwargs). A call with *a / **k is checked only for what it surely misses
(nothing with **k; with *a only the keyword-only parameters).
Exception: `# arity-ok: <reason>` on a line of the call (a call through a monkeypatched name, a test double ...).

usage: python3 tools/check_call_arity.py [-v]      exit 1 on a finding
Standard library only.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = "kalmido"
# decorators that return the function itself or a wrapper with the same parameters (functools.wraps around *a, **k)
KEEPS = {"app.get", "app.post", "app.put", "app.patch", "app.delete", "app.route", "app.errorhandler", "app.after_request",
         "app.before_request", "app.teardown_request", "app.teardown_appcontext", "v1_view", "bgj_fn", "fs_protect_hook",
         "contextlib.contextmanager", "contextmanager", "functools.lru_cache", "lru_cache", "functools.cache", "cache"}
MARK = re.compile(r"#\s*arity-ok:\s*\S")


def files(root=ROOT):
    """(module name, path) of every Python file of the package and app.py."""
    out = []
    app = os.path.join(root, "app.py")
    if os.path.exists(app):
        out.append(("app", app))
    for d, dirs, fs in os.walk(os.path.join(root, PKG)):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for f in sorted(fs):
            if f.endswith(".py"):
                rel = os.path.relpath(os.path.join(d, f), root)[:-3].split(os.sep)
                if rel[-1] == "__init__":
                    rel = rel[:-1]
                out.append((".".join(rel), os.path.join(d, f)))
    return out


def _deco(d):
    d = d.func if isinstance(d, ast.Call) else d
    try:
        return ast.unparse(d)
    except Exception:  # noqa: BLE001 - an odd node is simply not on the list
        return ""


class Sig:
    """The parameters of one def."""

    def __init__(self, fn, mod):
        a = fn.args
        pos = a.posonlyargs + a.args
        self.name, self.mod, self.line = fn.name, mod, fn.lineno
        self.pos = [p.arg for p in pos]
        self.posonly = {p.arg for p in a.posonlyargs}
        self.req = self.pos[:len(pos) - len(a.defaults)]
        self.kwonly = [p.arg for p in a.kwonlyargs]
        self.kwreq = [p.arg for p, dflt in zip(a.kwonlyargs, a.kw_defaults) if dflt is None]
        self.star, self.dstar = a.vararg is not None, a.kwarg is not None

    def problems(self, call):
        """What is wrong with the call (empty: nothing seen)."""
        stars = any(isinstance(x, ast.Starred) for x in call.args)
        dstar = any(k.arg is None for k in call.keywords)
        if dstar:
            return []  # **k may bring any of them
        n = sum(1 for x in call.args if not isinstance(x, ast.Starred))
        kws = [k.arg for k in call.keywords]
        out = []
        if not stars:
            if n > len(self.pos) and not self.star:
                out.append(f"{n} positional argument(s), takes at most {len(self.pos)}")
            miss = [p for p in self.req[n:] if p not in kws]
            if miss:
                out.append("missing " + ", ".join(miss))
        known = set(self.pos) - self.posonly | set(self.kwonly)
        if not self.dstar:
            bad = [k for k in kws if k not in known]
            if bad:
                out.append("unknown keyword " + ", ".join(bad))
        miss = [p for p in self.kwreq if p not in kws]
        if miss:
            out.append("missing keyword-only " + ", ".join(miss))
        return out


def _resolve(mod, level, name, is_pkg):
    """The absolute module of `from <level dots><name> import ...` in module mod."""
    if not level:
        return name or ""
    parts = mod.split(".")
    base = parts if is_pkg else parts[:-1]
    base = base[:len(base) - (level - 1)] if level > 1 else base
    return ".".join(base + ([name] if name else []))


class Module:
    """One file: its signatures, what its names are bound to, its calls."""

    def __init__(self, mod, path):
        self.mod, self.path = mod, path
        with open(path, encoding="utf-8") as f:
            self.src = f.read()
        self.lines = self.src.split("\n")
        self.tree = ast.parse(self.src, path)
        self.is_pkg = os.path.basename(path) == "__init__.py"
        self.sigs = {}
        self.binds = {}  # the module scope: name -> set of ("def", mod, name) / ("mod", module) / ("from", module, name) / ("other",)
        top = {}
        for n in self.tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                top.setdefault(n.name, []).append(n)
        for name, defs in top.items():
            fn = defs[0]
            if len(defs) == 1 and all(_deco(d) in KEEPS for d in fn.decorator_list):
                self.sigs[name] = Sig(fn, mod)
            self.binds.setdefault(name, set()).add(("def", mod, name))
        self._calls = []  # (call, scope chain: the module's binds first, then each enclosing function's)
        self._scan(self.tree, (self.binds,), set(), top=True)

    def _scan(self, node, chain, glob, top=False):
        """Bindings and calls below node; chain: the visible scopes (innermost last), glob: names declared global there."""
        here = chain[-1]

        def bind(name, what):
            (self.binds if name in glob else here).setdefault(name, set()).add(what)

        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, ast.Import):
                for a in ch.names:
                    if a.asname:
                        bind(a.asname, ("mod", a.name))
                    else:
                        bind(a.name.split(".")[0], ("mod", a.name.split(".")[0]))
            elif isinstance(ch, ast.ImportFrom):
                src = _resolve(self.mod, ch.level, ch.module, self.is_pkg)
                for a in ch.names:
                    if a.name != "*":
                        bind(a.asname or a.name, ("from", src, a.name))
            elif isinstance(ch, ast.Global):
                glob.update(ch.names)
            elif isinstance(ch, ast.Name) and isinstance(ch.ctx, (ast.Store, ast.Del)):
                bind(ch.id, ("other",))
            elif isinstance(ch, ast.ExceptHandler) and ch.name:
                bind(ch.name, ("other",))
            elif isinstance(ch, ast.Call):
                self._calls.append((ch, chain))
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                if not isinstance(ch, ast.Lambda) and not (top and not isinstance(ch, ast.ClassDef)):
                    # a nested def / a class binds its name where it stands (a module-level def is in self.binds already)
                    if not isinstance(node, ast.ClassDef):
                        bind(ch.name, ("other",))
                for d in getattr(ch, "decorator_list", []) + getattr(ch, "bases", []):
                    self._scan_expr(d, chain, glob)
                if isinstance(ch, ast.ClassDef):
                    # the class body is a scope of its own, its names are not seen by its methods
                    inner = {}
                    for x in ch.body:
                        self._scan(ast.Module(body=[x], type_ignores=[]), chain + (inner,), set())
                    continue
                inner = {}
                args = ch.args
                for x in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
                    if x is not None:
                        inner.setdefault(x.arg, set()).add(("other",))
                for dflt in args.defaults + [x for x in args.kw_defaults if x is not None]:
                    self._scan_expr(dflt, chain, glob)
                body = ch.body if isinstance(ch.body, list) else [ast.Expr(ch.body)]
                self._scan(ast.Module(body=body, type_ignores=[]), chain + (inner,), set())
            elif isinstance(ch, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                self._scan(ch, chain + ({},), glob)
            else:
                self._scan(ch, chain, glob)

    def _scan_expr(self, node, chain, glob):
        self._scan(ast.Expr(node), chain, glob)

    def lookup(self, chain, name):
        """The bindings of name seen from the innermost scope of chain (a function's own binding hides the module's)."""
        for sc in reversed(chain):
            if name in sc:
                return sc[name]
        return set()

    def calls(self):
        return self._calls

    def marked(self, call):
        end = getattr(call, "end_lineno", call.lineno) or call.lineno
        return any(MARK.search(self.lines[i - 1]) for i in range(call.lineno, end + 1) if 0 < i <= len(self.lines))


class Index:
    """All modules; resolves a call to the Sig it reaches."""

    def __init__(self, root=ROOT, extra=None):
        self.mods = {}
        for mod, path in files(root):
            self.mods[mod] = Module(mod, path)
        for mod, path in (extra or []):
            self.mods[mod] = Module(mod, path)

    def func(self, mod, name, seen=None):
        """The Sig of name in module mod, following re-exports (`from x import f` in mod)."""
        seen = seen or set()
        if (mod, name) in seen or mod not in self.mods:
            return None
        seen.add((mod, name))
        m = self.mods[mod]
        b = m.binds.get(name, set())
        if name in m.sigs and b == {("def", mod, name)}:
            return m.sigs[name]
        if len(b) == 1:
            (w,) = b
            if w[0] == "from":
                return self.func(w[1], w[2], seen)
        return None

    def _module_of(self, m, chain, node):
        """The module a Name / Attribute chain stands for in module m, or None."""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        b = m.lookup(chain, node.id)
        if len(b) != 1:
            return None
        (w,) = b
        if w[0] == "mod":
            base = w[1]
        elif w[0] == "from" and f"{w[1]}.{w[2]}" in self.mods:
            base = f"{w[1]}.{w[2]}"
        else:
            return None
        for part in reversed(parts):
            base = f"{base}.{part}"
        return base if base in self.mods else None

    def target(self, m, call, chain):
        f = call.func
        if isinstance(f, ast.Name):
            b = m.lookup(chain, f.id)
            if len(b) != 1:
                return None
            (w,) = b
            if w[0] == "def":
                return self.func(m.mod, f.id)
            if w[0] == "from":
                return self.func(w[1], w[2])
            return None
        if isinstance(f, ast.Attribute):
            mod = self._module_of(m, chain, f.value)
            if mod:
                return self.func(mod, f.attr)
        return None

    def findings(self, only=None):
        out = []
        for m in self.mods.values():
            if only is not None and m.mod not in only:
                continue
            rel = os.path.relpath(m.path, ROOT) if m.path.startswith(ROOT) else m.path
            for call, chain in m.calls():
                sig = self.target(m, call, chain)
                if sig is None:
                    continue
                bad = sig.problems(call)
                if bad and not m.marked(call):
                    out.append(f"{rel}:{call.lineno}: {sig.name}() of {sig.mod} (line {sig.line}): {'; '.join(bad)}"
                               f" - pass it, or '# arity-ok: <reason>' on the call (#5863)")
        return sorted(out)


def findings(root=ROOT, extra=None, only=None):
    """The findings as lines (empty: all fine). extra: (module, path) of more files (the test's samples), only: their names."""
    return Index(root, extra).findings(only)


if __name__ == "__main__":
    idx = Index()
    out = idx.findings()
    for x in out:
        print(x)
    if "-v" in sys.argv or out:
        n = sum(len(m.sigs) for m in idx.mods.values())
        print(f"check_call_arity: {len(idx.mods)} module(s), {n} signature(s), {len(out)} finding(s)")
    sys.exit(1 if out else 0)
