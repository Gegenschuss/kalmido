#!/usr/bin/env python3
"""2.742.0 (#5217): the web manifest of a source tree - the full SHA-256 of every file the browser gets from that version, as
it goes out (kalmido/core/codemanifest.py; the server answers /api/code-manifest with the same bytes).

Runs without the app and without a package (only the standard library): it loads kalmido/core/codemanifest.py, strip.py and
i18nkeys.py of the tree it describes (--root), so an old tag is described with its own recipe.

usage: web_manifest.py [--root DIR] [-o FILE]   the manifest of DIR (default: this repository) to FILE (default: stdout)
       web_manifest.py --twice [--root DIR] [-o FILE]   build it in two fresh processes from two copies of the tree (other path, other
                                                times of the files); exit 1 on any difference (the CI's proof that it is
                                                reproducible)"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def build(root):
    """-> the manifest of root as bytes (core/codemanifest.py cm_json)."""
    sys.path[:0] = [os.path.join(root, "kalmido", "core")]
    try:
        import codemanifest  # noqa: E402 (the recipe of the tree it describes)
        version, files = codemanifest.cm_build(root)
        return codemanifest.cm_json(version, files)
    finally:
        del sys.path[0]


def _copy(root, dst):
    """The files the manifest reads (app.py, VERSION, kalmido/, static/) into dst, with new times."""
    for name in ("app.py", "VERSION"):
        if os.path.exists(os.path.join(root, name)):
            shutil.copyfile(os.path.join(root, name), os.path.join(dst, name))
    for d in ("kalmido", "static"):
        shutil.copytree(os.path.join(root, d), os.path.join(dst, d),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), copy_function=shutil.copyfile)


def twice(root):
    """Builds the manifest twice, each in its own process (-I: nothing of this environment) from its own copy; -> (same, a, b)."""
    outs = []
    for i in range(2):
        with tempfile.TemporaryDirectory(prefix=f"webman{i}-") as tmp:
            _copy(root, tmp)
            out = os.path.join(tmp, "manifest.json")
            subprocess.run([sys.executable, "-I", "-B", os.path.abspath(__file__), "--root", tmp, "-o", out], check=True)
            with open(out, "rb") as f:
                outs.append(f.read())
    return outs[0] == outs[1], outs[0], outs[1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=os.path.dirname(HERE), help="the source tree (the folder of app.py)")
    ap.add_argument("-o", "--out", help="write the manifest here (default: stdout)")
    ap.add_argument("--twice", action="store_true", help="build twice independently and compare")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    if a.twice:
        same, one, two = twice(root)
        if not same:
            import difflib
            sys.stdout.writelines(difflib.unified_diff(one.decode().splitlines(True), two.decode().splitlines(True), "first", "second"))
            print("web manifest: the two builds differ - not reproducible", file=sys.stderr)
            return 1
        body = one
        n = body.count(b'\n"/')
        print(f"web manifest: built twice, the same ({n} files)", file=sys.stderr)
    else:
        body = build(root)
    if a.out:
        with open(a.out, "wb") as f:
            f.write(body)
    else:
        sys.stdout.buffer.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
