#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.493.0 (#4041) tools/check_singlefile.py: a module a test loads as a single file still loads that way; no container.
Twice main went red because imports pulled up to the module top broke such a module (office/einvoice_in.py, docs/ocr.py,
#2517). The check runs in the CI lint job, so a package's einreihen check finds it before main does:
 1. the sources as they are: no finding, and the known single-file modules (ocr.py, einvoice_in.py) are among the checked
 2. a copy where a module a test loads alone gets an unguarded `from ..x import y` at the top: red, named
 3. the same import inside try/except ImportError: green
 4. a dotted load name with a stand-in the test puts into sys.modules (the zipread pattern): green; a second, not stood-in
    import: red
 5. the load names of a helper load("name") are followed (office tests)
usage: python3 tests/singlefile_import_lint_test.py"""
import os
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
sys.path.insert(0, N)
from kt import check, done  # noqa: E402
TOOL = os.path.join(ROOT, "tools", "check_singlefile.py")


def run(root):
    r = subprocess.run([sys.executable, TOOL, "-v", "--root", root], capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout + r.stderr


# 1. the repository
rc, out = run(ROOT)
check(rc == 0, "the sources: no module that a test loads alone breaks: " + out[-600:])
check("kalmido/docs/ocr.py" in out and "kalmido/office/einvoice_in.py" in out, "ocr.py and einvoice_in.py are checked")


def tree(d, module, test):
    for p in ("tests", "kalmido/a", "kalmido/b"):
        os.makedirs(os.path.join(d, p), exist_ok=True)
    for p in ("kalmido/__init__.py", "kalmido/a/__init__.py", "kalmido/b/__init__.py"):
        open(os.path.join(d, p), "w").close()
    with open(os.path.join(d, "kalmido", "b", "c.py"), "w") as f:
        f.write("X = 1\n")
    with open(os.path.join(d, "kalmido", "a", "m.py"), "w") as f:
        f.write(module)
    with open(os.path.join(d, "tests", "x_test.py"), "w") as f:
        f.write("import importlib.util\nimport os\nimport sys\nN = os.path.dirname(os.path.abspath(__file__))\n" + test)


LOAD = 'spec = importlib.util.spec_from_file_location("m_x", os.path.join(N, "..", "kalmido", "a", "m.py"))\n'
with tempfile.TemporaryDirectory() as d:
    # 2. pulled up, unguarded
    tree(d, "import os\nfrom ..b.c import X\n\n\ndef f():\n    return X\n", LOAD)
    rc, out = run(d)
    check(rc == 1 and "kalmido/a/m.py" in out and "from ..b.c import X" in out and "tests/x_test.py" in out,
          "an unguarded pulled-up import in a module a test loads alone: red, with file, import and test: " + out[-400:])
    check("does not load as a single file" in out, "the load itself is tried and fails too")
with tempfile.TemporaryDirectory() as d:
    # 3. guarded
    tree(d, "try:\n    from ..b.c import X\nexcept ImportError:\n    X = None\n", LOAD)
    rc, out = run(d)
    check(rc == 0 and "loads   kalmido/a/m.py" in out, "the same import in try/except ImportError: green, loaded: " + out[-300:])
with tempfile.TemporaryDirectory() as d:
    # 4. dotted name + stand-in in sys.modules
    stub = ('import types\npkg = types.ModuleType("zz")\npkg.__path__ = []\nsys.modules["zz"] = pkg\n'
            'c = types.ModuleType("zz.c")\nc.X = 1\nsys.modules["zz.c"] = c\n'
            'spec = importlib.util.spec_from_file_location("zz.m", os.path.join(N, "..", "kalmido", "a", "m.py"))\n')
    tree(d, "from .c import X\n", stub)
    rc, out = run(d)
    check(rc == 0 and "stand-ins" in out, "an import the test stands in for (sys.modules): green, static only: " + out[-300:])
    tree(d, "from .c import X\nfrom .other import Y\n", stub)
    rc, out = run(d)
    check(rc == 1 and "from .other import Y" in out and "from .c import X" not in out,
          "a second import without a stand-in: red, only that one: " + out[-300:])
with tempfile.TemporaryDirectory() as d:
    # 5. a helper load("name")
    tree(d, "from ..b.c import X\n",
         'def load(name):\n    spec = importlib.util.spec_from_file_location(name, os.path.join(N, "..", "kalmido", "a", name + ".py"))\n'
         '    return spec\n\n\nm = load("m")\n')
    rc, out = run(d)
    check(rc == 1 and "kalmido/a/m.py" in out, "a load(\"m\") helper is followed: " + out[-300:])
done("singlefile_import_lint")
