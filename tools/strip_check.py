#!/usr/bin/env python3
"""2.191.0 B (#1824): checks the comment remover of the static files (kalmido/core/strip.py) on every client file.

For each static/*.js, static/js/*.js, static/*.css and static/css/*.css: the remover must be sure (else the file would go
out with its comments), the line count stays the same, a second pass changes nothing, and every JavaScript result passes
`node --check`. When the tokenizer of the pinned ESLint is reachable (run under `npx -p eslint@<version> -c "..."`, as CI
does), the tokens of every JavaScript file before and after are compared one by one, with their line numbers: only
comments may differ.

usage: python3 tools/strip_check.py [-v] [--need-espree]     exit code 1 on any difference
"""
import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location("stc_strip", os.path.join(ROOT, "kalmido", "core", "strip.py"))
stc_strip = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(stc_strip)

_TOKENS_JS = r"""
const espree = require(process.argv[1]);
const fs = require('fs');
const o = { ecmaVersion: 'latest', sourceType: 'script', loc: true, tokens: true };
const tok = s => espree.tokenize(s, o).map(t => t.type + ' ' + t.value + ' ' + t.loc.start.line);
let bad = 0;
for (const [name, a, b] of JSON.parse(fs.readFileSync(0, 'utf8'))) {
  const x = tok(fs.readFileSync(a, 'utf8')), y = tok(fs.readFileSync(b, 'utf8'));
  const i = x.findIndex((t, k) => t !== y[k]);
  if (i >= 0 || x.length !== y.length) { bad++; console.log(name + ': tokens differ at ' + (x[i] || 'end') + ' / ' + (y[i] || 'end')); }
}
process.exit(bad ? 1 : 0);
"""


def stc_espree():
    """The espree package next to the eslint found in PATH (npx -p eslint ...), else None."""
    exe = shutil.which("eslint")
    if not exe:
        return None
    mods = os.path.dirname(os.path.dirname(os.path.realpath(exe)))  # .../node_modules/eslint/bin/eslint.js -> node_modules
    while mods and os.path.basename(mods) != "node_modules":
        parent = os.path.dirname(mods)
        if parent == mods:
            return None
        mods = parent
    p = os.path.join(mods, "espree")
    return p if os.path.isdir(p) else None


def main(argv):
    verbose = "-v" in argv
    files = sorted(glob.glob(os.path.join(ROOT, "static", "*.js")) + glob.glob(os.path.join(ROOT, "static", "js", "*.js"))
                   + glob.glob(os.path.join(ROOT, "static", "*.css")) + glob.glob(os.path.join(ROOT, "static", "css", "*.css")))
    errs, pairs, before, after = [], [], 0, 0
    tmp = tempfile.mkdtemp(prefix="strip_check_")
    try:
        for f in files:
            rel = os.path.relpath(f, os.path.join(ROOT, "static")).replace(os.sep, "/")
            with open(f, "rb") as fh:
                data = fh.read()
            out = stc_strip.strip_asset(rel, data)
            if out is None:
                errs.append(f"{rel}: the remover is unsure (the file would go out with its comments)")
                continue
            before, after = before + len(data), after + len(out)
            n_in, n_out = data.count(b"\n"), out.count(b"\n")
            if n_in != n_out:
                errs.append(f"{rel}: line count {n_in} -> {n_out}")
            if stc_strip.strip_asset(rel, out) != out:
                errs.append(f"{rel}: a second pass changes the result")
            if rel.endswith(".js"):
                p = os.path.join(tmp, rel.replace("/", "_"))
                with open(p, "wb") as fh:
                    fh.write(out)
                r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
                if r.returncode:
                    errs.append(f"{rel}: node --check fails after stripping: {r.stderr.strip()[:300]}")
                pairs.append([rel, f, p])
        espree = stc_espree()
        if espree:
            r = subprocess.run(["node", "-e", _TOKENS_JS, espree], input=json.dumps(pairs), capture_output=True, text=True)
            if r.returncode:
                errs.extend((r.stdout + r.stderr).strip().splitlines())
            elif verbose:
                print(f"strip_check: tokens of {len(pairs)} JavaScript files unchanged (espree)")
        elif "--need-espree" in argv:
            errs.append("espree not found (run under npx -p eslint@<version> -c ...)")
        else:
            print("strip_check: espree not found, token comparison skipped")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for e in errs:
        print("strip_check: " + e)
    print(f"strip_check: {len(files)} files, " + f"{before:_} -> {after:_}".replace("_", ".") + f" bytes, {len(errs)} error(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
