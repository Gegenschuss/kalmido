#!/usr/bin/env python3
# kalmido-suite: after=p2501_a_nosham nodata
"""2.1056.0 (#5863): tools/check_call_arity.py, calls of module-level functions get all required parameters. Static, no container.
 - the case of 2.1024: lists/otrundo.py calling otr_back without uid (the #5491 signature) is red, the repository as it is: quiet
 - samples in a package of their own: a missing parameter through `from x import f`, a relative import, a module alias, a
   re-export; too many positional arguments, an unknown keyword, a missing keyword-only parameter: red
 - a call with **k, a name shadowed by an argument, an unknown decorator, `# arity-ok: <reason>`: quiet
usage: check_call_arity_test.py"""
import os
import sys
import tempfile

from kt import FAILS, OKS, check

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from check_call_arity import Index  # noqa: E402

SAMPLES = {
    "__init__.py": "",
    "a.py": (
        "import functools\n\n\n"
        "def back(c, r, uid, checked=False):\n    return c\n\n\n"
        "def kw(c, *, who, note=''):\n    return c\n\n\n"
        "def any_(*a, **k):\n    return a\n\n\n"
        "def deco(fn):\n    return fn\n\n\n"
        "@deco\n"
        "def wrapped(c, r):\n    return c\n\n\n"
        "@functools.lru_cache\n"
        "def cached(c, r):\n    return c\n"
    ),
    "re.py": "from .a import back  # noqa: F401 - a re-export\n",
    "b.py": (
        "from .a import back, kw, any_, wrapped, cached\n"
        "from . import a\n"
        "from . import re as rx\n"
        "import kalmido.zz5863.a as al\n\n\n"
        "def run(c, r, uid, k):\n"
        "    back(c, r, checked=True)\n"                    # 8: missing uid (the 2.1024 case)
        "    a.back(c, r)\n"                                # 9: missing uid through the module
        "    al.back(c)\n"                                  # 10: missing r, uid through an alias
        "    rx.back(c, r)\n"                               # 11: missing uid through a re-export
        "    back(c, r, uid, True, 5)\n"                    # 12: too many positional
        "    back(c, r, uid, chekced=True)\n"               # 13: unknown keyword
        "    kw(c)\n"                                       # 14: missing keyword-only who
        "    back(c, r, uid, checked=True)\n"               # 15: fine
        "    back(c, r, uid=uid)\n"                         # 16: fine, by keyword
        "    back(c, **k)\n"                                # 17: **k may bring them
        "    kw(c, who=uid)\n"                              # 18: fine
        "    any_()\n"                                      # 19: fine
        "    wrapped(c)\n"                                  # 20: unknown decorator, not followed
        "    cached(c)\n"                                   # 21: lru_cache keeps the signature: red
        "    back(c, r)  # arity-ok: a test double takes two\n"  # 22: marked
        "    back(\n        c,\n        r,  # arity-ok: wrapped call, marked on a later line\n    )\n"  # 23
        "\n\n"
        "def shadow(back, c):\n"
        "    return back(c)\n"                              # 30: back is an argument here, not the module's
    ),
}

with tempfile.TemporaryDirectory() as tmp:
    pkg = os.path.join(tmp, "zz5863")
    os.makedirs(pkg)
    extra = []
    for name, src in SAMPLES.items():
        p = os.path.join(pkg, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(src)
        mod = "kalmido.zz5863" + ("" if name == "__init__.py" else "." + name[:-3])
        extra.append((mod, p))
    # the real case: otrundo.py as it was in job/4232 (018984dba4), otr_back without the person
    with open(os.path.join(ROOT, "kalmido", "lists", "otrundo.py"), encoding="utf-8") as f:
        und = f.read()
    check("otr_back(c, r, uid, checked=True)" in und, "otrundo.py still has the call of the 2.1024 case")
    old = os.path.join(tmp, "otrundo.py")
    with open(old, "w", encoding="utf-8") as f:
        f.write(und.replace("otr_back(c, r, uid, checked=True)", "otr_back(c, r, checked=True)"))
    extra.append(("kalmido.lists.otrundo_old", old))

    idx = Index(extra=extra)
    out = idx.findings(only={"kalmido.zz5863.b"})
    lines = sorted(int(x.split(":")[1]) for x in out)
    check(lines == [8, 9, 10, 11, 12, 13, 14, 21], f"the wrong calls of the samples are red, the others quiet: {out}")
    by = {int(x.split(":")[1]): x for x in out}
    check("missing uid" in by.get(8, ""), f"the missing parameter is named: {by.get(8)}")
    check("missing r, uid" in by.get(10, ""), f"through an alias: {by.get(10)}")
    check("3 positional" not in by.get(12, "") and "5 positional argument(s), takes at most 4" in by.get(12, ""), f"too many: {by.get(12)}")
    check("unknown keyword chekced" in by.get(13, ""), f"an unknown keyword: {by.get(13)}")
    check("missing keyword-only who" in by.get(14, ""), f"keyword-only: {by.get(14)}")
    out = idx.findings(only={"kalmido.lists.otrundo_old"})
    check(len(out) == 1 and "otr_back() of kalmido.lists.listtrash" in out[0] and "missing uid" in out[0],
          f"the 2.1024 case (otr_back without uid) is red: {out}")
    out = idx.findings(only={m for m in idx.mods if not m.startswith("kalmido.zz5863") and m != "kalmido.lists.otrundo_old"})
    check(not out, f"the repository: {out}")

print(f"check_call_arity: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
