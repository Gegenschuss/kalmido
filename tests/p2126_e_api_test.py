"""2.126.0 tests, part E (#1993 ESLint in CI): the generated list of the client's global names.

- tools/eslint_globals.json is current (the same check CI runs before ESLint)
- the scanner finds the top-level names of a script (several declarators, destructuring, classes, window.X =) and skips
  the inner ones and what stands in strings, template literals, comments and regular expressions
No server needed; the data dir argument of run_all.sh is ignored.
usage: p2126_e_api_test.py [<datadir>]"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import eslint_globals  # noqa: E402

FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what)


r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "eslint_globals.py"), "--check"], capture_output=True, text=True)
check(r.returncode == 0, f"tools/eslint_globals.json is current: {r.stdout.strip()} {r.stderr.strip()[-300:]}")

SRC = r"""
// function inComment() {}
/* const inBlock = 1; */
const A1 = 1, a2 = {x: [1, 2], y: f(3, 4)}, a3 = `t ${ {k: 1}.k } } {`;
let {b1, b2: renamed, b3 = 5, ...b4} = obj, [c1, , c2 = 1] = arr;
var d1 = /\/function notMe\(/g.test(s) ? 1 : 2;
async function e1(p1, p2) { const inner = 1; function nested() {} return `${inner}`; }
function* e2() {}
class E3 extends Error { m() { const notTop = 1; } }
const e4 = () => { let alsoInner = 2; }
const e5 = 'function nope() {}'
window.w1 = () => 1; globalThis.w2 = 2; if (x) { window.w3 = 3; }
if (window.notAssigned === 1) {}
obj.function = 1;
"""
got = eslint_globals.names(SRC)
want = {"A1", "a2", "a3", "b1", "renamed", "b3", "b4", "c1", "c2", "d1", "e1", "e2", "E3", "e4", "e5", "w1", "w2", "w3"}
check(want <= got, f"top-level names found, missing: {sorted(want - got)}")
nope = {"inComment", "inBlock", "notMe", "p1", "p2", "inner", "nested", "notTop", "alsoInner", "nope", "notAssigned", "b2", "x", "y", "k"}
check(not (nope & got), f"inner names / text not taken: {sorted(nope & got)}")

real = set(eslint_globals.collect())
check({"api", "tr", "render", "S"} <= real, "the client's core names are in the list")

print(f"p2126_e_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
