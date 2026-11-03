#!/usr/bin/env python3
"""Modules that a test loads as a single file still load as a single file (2.493.0, #4041).

Twice main went red because imports pulled up to the top of a module (#2517) broke a module that a test loads on its own
with importlib.util.spec_from_file_location - no package around it, so `from ..x import y` fails (office/einvoice_in.py in
job/2368, docs/ocr.py in job/2376). This check finds every such module in tests/*.py and

  1. statically: every module-level import from the own package (`from ..x import`, `from .x import`, `import kalmido.x`,
     `from kalmido.x import`) must sit in a try whose except catches ImportError (or Exception) - unless the test that loads
     the module puts that very module into sys.modules itself (a stand-in, e.g. p2146_a_api for einvoice_in);
  2. dynamically: loads the module the same way (same name, spec_from_file_location + exec_module, in a fresh Python
     without the repository on sys.path). A missing third-party package (bare Python of the CI lint job) skips this step
     for that module; the static step still covers it. Modules whose test puts stand-ins into sys.modules are only checked
     statically.

    python3 tools/check_singlefile.py [-v] [--tests DIR] [--root DIR]      exit 1 when a module breaks

Standard library only (the CI lint job runs plain Python).
"""
import argparse
import ast
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = "kalmido"
SPEC = re.compile(r"spec_from_file_location\(\s*([^,]+?)\s*,\s*os\.path\.join\(")
VAR_DEF = re.compile(r"^(\w+)\s*=\s*(?:os\.path\.abspath\()?(?:os\.environ\.get\([^)]*\)\s*or\s*)?os\.path\.join\(([^)]*)\)", re.M)
STR = re.compile(r"""^(['"])([^'"]*)\1$""")
STUB_LINE = re.compile(r"^.*(?:sys\.modules|ModuleType\().*$", re.M)
STUB = re.compile(r"""["'](\w+(?:\.\w+)*)["']""")
CHILD = r"""
import importlib.util, sys
name, path = sys.argv[1], sys.argv[2]
sys.path = [p for p in sys.path if p]
try:
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
except ModuleNotFoundError as e:
    top = (e.name or "").split(".")[0]
    if top and top != "kalmido" and not e.msg.startswith("No module named '.'"):
        print("SKIP third-party module " + top)
        sys.exit(3)
    raise
"""


def split_args(s):
    """The comma separated arguments of a call text up to its closing parenthesis -> (args, rest)."""
    out, depth, cur, quote = [], 0, "", None
    for i, ch in enumerate(s):
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            cur += ch
        elif ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            if depth == 0:
                out.append(cur.strip())
                return [a for a in out if a], s[i + 1:]
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [], ""


def resolve_var(var, defs, seen=()):
    """The path parts (relative to the repository root) a variable of a test stands for, None = unknown."""
    if var in ("N", "HERE", "TESTS"):
        return ["tests"]
    if var in defs and var not in seen:
        args, _ = split_args(defs[var] + ")")
        return parts_of(args, defs, seen + (var,))
    return None


def parts_of(args, defs, seen=()):
    if not args:
        return None
    base = resolve_var(args[0], defs, seen) if not STR.match(args[0]) else [STR.match(args[0]).group(2)]
    if base is None:
        return None
    out = list(base)
    for a in args[1:]:
        m = STR.match(a)
        if not m:
            return out + ["<dyn:" + a + ">"]
        out.append(m.group(2))
    norm = []
    for p in out:
        if p == "..":
            if norm:
                norm.pop()
        elif p and p != ".":
            norm.append(p)
    return norm


def loads_in(test_path, root):
    """-> [(module path relative to root, load name or None, test file)] for one test file."""
    src = open(test_path, encoding="utf-8").read()
    defs = {m.group(1): m.group(2) for m in VAR_DEF.finditer(src)}
    out = []
    for m in SPEC.finditer(src):
        args, _ = split_args(src[m.end():])
        parts = parts_of(args, defs)
        if not parts:
            continue
        name_m = STR.match(m.group(1))
        name = name_m.group(2) if name_m else None
        if parts[-1].startswith("<dyn:"):
            # load(name): os.path.join(SRC, "kalmido", "office", name + ".py") - the names come from the calls of the
            # enclosing function in the same file
            expr = parts[-1][5:-1]
            var = re.match(r"(\w+)\s*\+\s*['\"]\.py['\"]$", expr)
            head = src[:m.start()]
            fn = list(re.finditer(r"^def (\w+)\((\w+)", head, re.M))
            if not var or not fn or fn[-1].group(2) != var.group(1):
                continue
            prefix = re.match(r"""^(['"])(\w*)\1\s*\+\s*\w+$""", m.group(1).strip())
            for c in sorted(set(re.findall(r"\b%s\(\s*['\"](\w+)['\"]\s*\)" % re.escape(fn[-1].group(1)), src))):
                rel = os.path.join(*parts[:-1], c + ".py")
                if os.path.isfile(os.path.join(root, rel)):
                    out.append((rel, (prefix.group(2) + c) if prefix else c, test_path))
            continue
        rel = os.path.join(*parts)
        if rel.endswith(".py") and os.path.isfile(os.path.join(root, rel)):
            out.append((rel, name, test_path))
    return out


def catches_import_error(node):
    for h in node.handlers:
        t = h.type
        names = []
        if t is None:
            return True
        for e in (t.elts if isinstance(t, ast.Tuple) else [t]):
            names.append(e.id if isinstance(e, ast.Name) else getattr(e, "attr", ""))
        if {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"} & set(names):
            return True
    return False


def own_target(node, modname):
    """The absolute module an import from the own package refers to, None for anything else."""
    pkg = modname.split(".")[:-1]
    if isinstance(node, ast.ImportFrom):
        if node.level:
            base = pkg[:len(pkg) - (node.level - 1)] if node.level - 1 <= len(pkg) else []
            return ".".join(base + ([node.module] if node.module else [])) or "."
        if node.module and node.module.split(".")[0] == PKG:
            return node.module
    elif isinstance(node, ast.Import):
        for a in node.names:
            if a.name.split(".")[0] == PKG:
                return a.name
    return None


def static_problems(path, modname, stubbed):
    """Unguarded module-level imports from the own package -> ["line N: from ..x import y", ...]."""
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    bad = []

    def walk(body, guarded):
        for n in body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                tgt = own_target(n, modname)
                if tgt and not guarded and tgt not in stubbed:  # a stand-in package (__path__ = []) holds no submodules
                    bad.append(f"line {n.lineno}: {ast.unparse(n)}")
            elif isinstance(n, ast.Try):
                walk(n.body, guarded or catches_import_error(n))
                for h in n.handlers:
                    walk(h.body, guarded)
                walk(n.orelse, guarded)
                walk(n.finalbody, guarded)
            elif isinstance(n, ast.If):
                walk(n.body, guarded)
                walk(n.orelse, guarded)
    walk(tree.body, False)
    return bad


def module_name(rel, name):
    """The name the module gets: the test's own name, or the package path (kalmido/docs/ocr.py -> kalmido.docs.ocr)."""
    return name or rel[:-3].replace(os.sep, ".")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--tests", default=None)
    o = ap.parse_args(argv)
    root = os.path.abspath(o.root)
    tests = o.tests or os.path.join(root, "tests")
    seen, fails, n_dyn, n_skip = {}, [], 0, 0
    for t in sorted(glob.glob(os.path.join(tests, "*.py"))):
        try:
            src = open(t, encoding="utf-8").read()
        except OSError:
            continue
        if "spec_from_file_location" not in src:
            continue
        # stand-ins the test puts into sys.modules itself (sys.modules["x.y"] = ..., types.ModuleType("x.y"), loops over names)
        stubbed = set()
        for ln in STUB_LINE.findall(src):
            stubbed |= set(STUB.findall(ln))
        if stubbed:
            stubbed |= {x for ln in re.findall(r"^\s*for \w+ in \(([^)]*)\):", src, re.M) for x in STUB.findall(ln)}
        for rel, name, _ in loads_in(t, root):
            # the name only matters with a dot (relative imports against that package); plain names load alike
            name = name if name and "." in name else "sf_" + os.path.basename(rel)[:-3]
            key = (rel, name, frozenset(stubbed))
            if key in seen:
                continue
            seen[key] = os.path.basename(t)
    for (rel, name, stubbed), tname in sorted(seen.items(), key=lambda kv: (kv[0][0], kv[1])):
        path = os.path.join(root, rel)
        modname = module_name(rel, name)
        # relative imports resolve against the name the test gives (a dotted one) or the package the file sits in
        modname_pkg = modname if "." in modname else (rel[:-3].replace(os.sep, ".") if rel.startswith(PKG + os.sep) else modname)
        try:
            bad = static_problems(path, modname_pkg, stubbed)
        except SyntaxError as e:
            bad = [f"syntax error: {e}"]
        for b in bad:
            fails.append(f"{rel} (loaded alone by tests/{tname}): import from the own package outside a guard, {b} - "
                         "keep it inside the function or wrap it in try/except ImportError (pattern kalmido/docs/ocr.py)")
        if stubbed:
            if o.v:
                print(f"  static  {rel} ({tname} puts stand-ins into sys.modules)")
            continue
        r = subprocess.run([sys.executable, "-I", "-B", "-c", CHILD, modname, path], capture_output=True, text=True,
                           cwd=tests, timeout=120)
        if r.returncode == 3:
            n_skip += 1
            if o.v:
                print(f"  static  {rel} ({r.stdout.strip()})")
        elif r.returncode != 0:
            last = (r.stderr.strip().splitlines() or ["?"])[-1]
            fails.append(f"{rel} (loaded alone by tests/{tname}) does not load as a single file: {last}")
        else:
            n_dyn += 1
            if o.v:
                print(f"  loads   {rel} as {modname}")
    for f in fails:
        print("FAIL " + f)
    print(f"check_singlefile: {len(seen)} single-file loads, {n_dyn} loaded, {n_skip} static only (third-party package "
          f"missing), {len(fails)} problem(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
