#!/usr/bin/env python3
"""2.638.0 (#4294): every public_links_on(c, KIND) in kalmido/ names a member of PUB_KINDS (kalmido/core/instance.py) as a
string literal. A misspelt kind is never switched off ("kind not in pub_kinds_off"), so its links would stay on silently
when the admin turns that kind off; a kind computed at run time cannot be checked here and is refused as well.
public_links_on(c) without a kind (the instance switch alone) is fine. Statically, without a server; runs inside
tools/check_layout.py (CI lint) and on its own:

usage: python3 tools/check_pubkinds.py [ROOT]    exit code 1 on a finding   (ROOT: default the repository)
"""
import ast
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pub_kinds(root=None):
    """The keys of PUB_KIND_LABEL in kalmido/core/instance.py (PUB_KINDS = tuple(PUB_KIND_LABEL)), read without importing."""
    with open(os.path.join(root or ROOT, "kalmido", "core", "instance.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PUB_KIND_LABEL" for t in node.targets) \
                and isinstance(node.value, ast.Dict):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return set()


def errors(root=None):
    """List of error strings, one per public_links_on(...) call whose kind is not a literal member of PUB_KINDS."""
    root = root or ROOT
    kinds = pub_kinds(root)
    if not kinds:
        return ["kalmido/core/instance.py: PUB_KIND_LABEL (the kinds of public links) not found"]
    out = []
    for p in sorted(glob.glob(os.path.join(root, "kalmido", "**", "*.py"), recursive=True)):
        try:
            with open(p, encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = os.path.relpath(p, root)
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if name != "public_links_on":
                continue
            arg = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "kind"), None)
            if arg is None:
                continue  # the instance switch alone
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                out.append(f"{rel}:{n.lineno}: public_links_on() with a kind that is not a string literal; name one of "
                           f"{', '.join(sorted(kinds))}")
            elif arg.value not in kinds:
                out.append(f"{rel}:{n.lineno}: public_links_on(c, {arg.value!r}): not a kind of PUB_KINDS "
                           f"({', '.join(sorted(kinds))}); the switch of this kind would never apply")
    return out


if __name__ == "__main__":
    errs = errors(sys.argv[1] if len(sys.argv) > 1 else None)
    for e in errs:
        print("ERROR:", e)
    print(f"check_pubkinds: {len(errs)} error(s)")
    sys.exit(1 if errs else 0)
