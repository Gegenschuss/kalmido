# 2.757.0 (#5295): static test, no server.
# kalmido-suite: nodata
"""2.757.0 (#5295): tools/check_glossar.py sees the real glossary green and a missing / stale entry red (in a tmp tree)."""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "check_glossar.py")


def run(root):
    return subprocess.run([sys.executable, TOOL, "--root", root], capture_output=True, text=True)


def main():
    r = run(ROOT)
    assert r.returncode == 0, "real tree not green:\n" + r.stdout
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "kalmido", "core", "migrations.d"))
        os.makedirs(os.path.join(tmp, "static", "js"))
        os.makedirs(os.path.join(tmp, "docs"))
        for f in ("kalmido/__init__.py", "kalmido/core/__init__.py", "kalmido/core/a.py",
                  "kalmido/core/migrations.d/1_x.py", "static/js/b.js"):
            open(os.path.join(tmp, f), "w").write("")
        gl = os.path.join(tmp, "docs", "GLOSSAR.md")
        open(gl, "w").write("- `kalmido/core/a.py` - a\n- `static/js/b.js` - b\n")
        r = run(tmp)
        assert r.returncode == 0, "tmp tree should be green:\n" + r.stdout
        open(gl, "w").write("- `kalmido/core/a.py` - a\n")
        r = run(tmp)
        assert r.returncode == 1 and "static/js/b.js" in r.stdout, "missing entry not found:\n" + r.stdout
        assert "migrations.d" not in r.stdout and "__init__" not in r.stdout
        open(gl, "w").write("- `kalmido/core/a.py` - a\n- `static/js/b.js` - b\n- `static/js/gone.js` - x\n")
        r = run(tmp)
        assert r.returncode == 1 and "gone.js" in r.stdout, "stale entry not found:\n" + r.stdout
    finally:
        shutil.rmtree(tmp)
    print("ok")


if __name__ == "__main__":
    main()
