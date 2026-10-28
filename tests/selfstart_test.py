#!/usr/bin/env python3
"""2.180.0 C (#2695): guard of tests/selfstart.txt - the suites that start their OWN fresh container first thing.
run_all.sh's `fresh` starts a container lazily: right before the first suite of the group that really runs. A suite named
in selfstart.txt calls start.sh itself before its first request, so run_all.sh only removes the old container for it
(no second start, ~1 container start saved per group). A suite qualifies when, statically:
 - its file has no KEEP (KEEP=1 = it relies on the container / data before it), and
 - its FIRST start.sh call is a top-level statement: JS `execFileSync('bash', [path.join(__dirname, 'start.sh') …` at
   column 0, optionally behind `if (!process.env.X_NOSTART …)` / `if (process.env.X_NOSTART !== '1')`; Python
   `subprocess.run(["bash", os.path.join(N, "start.sh") …` at column 0 or right under `if not os.environ.get("X_NOSTART"):`
   (X_NOSTART = any variable ending in NOSTART; run_all.sh and the CI set none), and
 - no top-level statement before it talks to the server (JS: nothing awaited / no async IIFE; Python: no requests / login).
2.381.0 (#2712): a suite whose first start.sh call is not such a statement still qualifies when follows() proves, statically,
that the first thing it does that can reach the server is start.sh: inside a local start function it calls first
(`def start():` / `function restart() {` / `const fresh = () => …`, also `await fresh()`), behind a NOSTART guard with
plain lines before it, or behind a NOSTART variable set once (`NOSTART = os.environ.get("X_NOSTART")`). selftest() pins
one snippet per pattern (and the ones that must stay out).
A suite that does not start its container anyway fails loudly (no container), never runs on the old one.
No container. usage: selfstart_test.py [--list]   (--list: print every qualifying suite of run_all.sh = the new file)"""
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
RUN = re.compile(r'^\s*(?:now [^;]*;\s*)?(?:fresh;\s*)?run (\S+) (?:node|"\$PY") (\S+)')
JS_START = re.compile(r"""^(?:if \((?:!process\.env\.\w*NOSTART(?: && !process\.env\.\w*NOSTART)*|process\.env\.\w*NOSTART !== '1')\) )?"""
                      r"""execFileSync\('bash', \[path\.join\(__dirname, 'start\.sh'\)""")
PY_START = re.compile(r"""^(?:\w+ = )?subprocess\.run\(\["bash", os\.path\.join\(N, "start\.sh"\)""")
PY_GUARD = re.compile(r"""^if not os\.environ\.get\(["']\w*NOSTART["']\):\s*$""")
JS_TALK = re.compile(r"^\(async|^(?:fetch|boot|login|call|api|v1)\s*\(")  # CommonJS: no top-level await
KEEP = re.compile(r"(?<!\w)KEEP(?!\w)")  # the env var KEEP, not names like LS_KEEP (p2240_ui, #3270)
PY_TALK = re.compile(r"requests\.|urlopen|\bsess\(|\blogin\(|\.(?:get|post|put|patch|delete)\(B")


# 2.381.0 (#2712): follow a start function. ~200 suites call start.sh inside `def start():` / `function restart() {` /
# `const fresh = () => …` (or behind a NOSTART guard with a few plain lines before it) and call that function first thing.
# walk() runs the statements of a scope in order, statically: it returns START when the first thing that can reach the server
# is start.sh (directly, behind a NOSTART guard, or as the first step of a local function it calls, up to 4 levels), TALK
# when something else comes first (a request, a docker exec, an await, a helper from another module, a branch, a loop, a
# return), NONE when the scope ends without either. Anything it does not understand counts as TALK (one group less, never a
# run on the old container).
PY_COND = (r"""(?:not os\.environ\.get\(["']\w*NOSTART["']\)|os\.environ\.get\(["']\w*NOSTART["']\) != ["']1["']"""
           r"""|not \(os\.environ\.get\(["']\w*NOSTART["']\) or os\.environ\.get\(["']\w*NOSTART["']\)\))""")
PY_GUARD2 = re.compile(r"^if " + PY_COND + r":\s*$")
JS_COND = r"(?:!process\.env\.\w*NOSTART|process\.env\.\w*NOSTART !== '1')(?: && !process\.env\.\w*NOSTART)*"
JS_GUARD = re.compile(r"^if \(" + JS_COND + r"\) \{\s*$")
JS_START2 = re.compile(r"^(?:if \(" + JS_COND + r"\) )?(?:await )?execFileSync\('bash', \[path\.join\(__dirname, 'start\.sh'\)")
JS_DEF = re.compile(r"^(?:async )?function (\w+)\s*\(|^const (\w+) = (?:async )?(?:\([^()]*\)|\w+) =>")
PY_NEG = re.compile(r"""^(\w+) = (?:bool\()?os\.environ\.get\(["']\w*NOSTART["']\)\)?(?: == ["']1["'])?"""
                    r"""(?: or os\.environ\.get\(["']\w*NOSTART["']\))?\s*$""")
PY_POS = re.compile(r"""^(\w+) = not os\.environ\.get\(["']\w*NOSTART["']\)\s*$""")
JS_NEG = re.compile(r"""^const (\w+) = (?:!!process\.env\.\w*NOSTART|process\.env\.\w*NOSTART === '1')"""
                    r"""(?: \|\| !!process\.env\.\w*NOSTART)*;$""")
PY_DEF = re.compile(r"^(?:async )?def (\w+)\s*\(")
JS_IIFE = re.compile(r"^\(async \(\) => \{\s*$")
JS_OPEN = re.compile(r"^(?:if|else|for|while|do|try|switch|return|throw|break|continue)\b|^\}.*\b(?:else|catch|finally)\b")
PY_OPEN = re.compile(r"^(?:if|elif|else|for|while|with|try|except|finally|def|class|async|match|return|raise|break|continue|"
                     r"assert|yield|global|nonlocal)\b|sys\.exit|^exit\(")
JS_TALK2 = re.compile(r"\bawait\b|\bfetch\(|fromURL|\.then\(|'docker', \['(?:exec|cp|logs)'|\bhttps?\.(?:get|request)\(")
PY_TALK2 = re.compile(PY_TALK.pattern + r"""|["']docker["'], ["'](?:exec|cp|logs)["']|\bsocket\.|\bawait\b""")
START, TALK, NONE = "start", "talk", "none"
PURE = {"testclock"}  # shared test modules that never reach the server (the test time)


def _indent(x):
    return len(x) - len(x.lstrip())


class Scan:
    def __init__(self, lines, js):
        self.js = js
        self.start = JS_START2 if js else PY_START
        self.cut = (lambda x: x.split("//")[0].rstrip()) if js else (lambda x: x.split("#")[0].rstrip())
        self.x = [self.cut(x) if not (x.strip().startswith(("//", "*", "/*")) and js) else "" for _, x in lines]
        self.defs, self.foreign, self.mods = {}, set(), set()
        for i, x in enumerate(self.x):
            m = (JS_DEF if js else PY_DEF).match(x)
            if m:
                self.defs.setdefault(m.group(1) or (m.group(2) if js else None), i)
            if js:
                r = re.match(r"^const \{([^}]*)\} = require\('\./", x)
                if r:  # helpers of the shared test modules (boot.js, ff.js …) may talk to the server; sleep does not
                    self.foreign |= {n.split(":")[-1].strip() for n in r.group(1).split(",")} - {"sleep", ""}
                r = re.match(r"^const (\w+) = require\('\./", x)
                if r:
                    self.mods.add(r.group(1))
            else:
                r = re.match(r"^from (\w+) import ([\w, ]+)$", x)
                if r and os.path.exists(os.path.join(N, r.group(1) + ".py")):  # helpers of the shared test modules
                    self.foreign |= {n.split(" as ")[-1].strip() for n in r.group(2).split(",")} - {""}
                r = re.match(r"^import ([\w, ]+)$", x)
                if r:
                    self.mods |= {n.strip() for n in r.group(1).split(",")
                                  if os.path.exists(os.path.join(N, n.strip() + ".py"))} - PURE
        self.defs.pop(None, None)
        self.guard = JS_GUARD if js else PY_GUARD2
        neg, pos = set(), set()  # NOSTART = os.environ.get("X_NOSTART") … (set once) -> `if not NOSTART:` is a guard too
        for x in self.x:
            m = (JS_NEG if js else PY_NEG).match(x)
            if m:
                neg.add(m.group(1))
            m = None if js else PY_POS.match(x)
            if m:
                pos.add(m.group(1))
        once = {v for v in neg | pos if sum(bool(re.match(r"^\s*(?:const |let |var )?" + v + r" =[^=]", y)) for y in self.x) == 1}
        neg, pos = neg & once, pos & once
        if neg or pos:
            if js:
                alt = r"|^if \(!(?:" + "|".join(neg) + r")\) \{\s*$"
            else:
                alt = "|".join(([r"^if not (?:" + "|".join(neg) + r"):\s*$"] if neg else [])
                               + ([r"^if (?:" + "|".join(pos) + r"):\s*$"] if pos else []))
                alt = "|" + alt
            self.guard = re.compile(self.guard.pattern + alt)
            if js:
                self.start = re.compile(JS_START2.pattern + r"|^if \(!(?:" + "|".join(neg) + r")\) "
                                        r"execFileSync\('bash', \[path\.join\(__dirname, 'start\.sh'\)")
        if not js:  # a class: making an object runs its __init__ (a session that logs in …)
            self.foreign |= {m.group(1) for m in (re.match(r"^class (\w+)", x) for x in self.x) if m}
        names = "|".join(sorted(map(re.escape, list(self.defs) + list(self.foreign)), key=len, reverse=True))
        self.call = re.compile(r"(?<![\w.$])(" + names + r")\s*\(" if names else r"(?!x)x")
        mods = "|".join(map(re.escape, self.mods))
        self.foreign_ref = re.compile(r"(?<![\w.$])(?:" + mods + r")\.\w+\s*\(" if mods else r"(?!x)x")  # pg.query(…)

    def block_end(self, i, ind):
        """The first line after the block whose header is line i (indent ind)."""
        j = i + 1
        while j < len(self.x):
            y = self.x[j]
            if y.strip():
                if self.js and _indent(y) == ind and y.lstrip().startswith("}"):
                    return j + 1
                if not self.js and _indent(y) <= ind:
                    return j
            j += 1
        return j

    def def_body(self, name):
        i = self.defs[name]
        h = self.x[i]
        if self.js:
            if not h.rstrip().endswith("{"):  # an arrow with one expression: `const fresh = () => execFileSync(…start.sh…)`
                return ("expr", h.split("=>", 1)[1].strip() if "=>" in h else "")
            return ("lines", i + 1, self.block_end(i, 0) - 1, 2)
        j = i
        while j < len(self.x) and not self.x[j].endswith(":"):  # a signature over several lines
            j += 1
        return ("lines", j + 1, self.block_end(j, 0), 4)

    def stmt(self, y, depth):
        """One plain statement (or a continuation line): START / TALK / NONE."""
        s = y.strip()
        m = re.match(r"^await (\w+)\(", s) if self.js else None
        if m and m.group(1) in self.defs and m.group(1) not in self.foreign:  # `await fresh();`: its sync first step runs at once
            s = s[6:]
        if self.start.match(s):
            return START
        if (JS_TALK2 if self.js else PY_TALK2).search(s) or (self.js and JS_TALK.match(s)) or "start.sh" in s:
            return TALK
        m = self.call.search(s)
        if m:
            name = m.group(1)
            if name in self.foreign or depth >= 4:
                return TALK
            r = self.walk_def(name, depth + 1)
            if r != NONE:
                return r
            rest = s[m.end():]
            return TALK if self.call.search(rest) or self.foreign_ref.search(rest) else NONE
        if self.foreign_ref.search(s):
            return TALK
        return NONE

    def walk_def(self, name, depth):
        b = self.def_body(name)
        if b[0] == "expr":
            return self.stmt(b[1], depth) if b[1] else TALK
        return self.walk(b[1], b[2], b[3], depth)

    def walk(self, a, b, ind, depth, top=False):
        i = a
        while i < b:
            y = self.x[i]
            s = y.strip()
            if not s:
                i += 1
                continue
            k = _indent(y)
            if k < ind:
                return TALK  # out of the expected layout
            if k == ind:
                if top and (JS_DEF if self.js else PY_DEF).match(s):  # a definition: skip its body
                    i = (self.def_body_end(i))
                    continue
                if top and not self.js and s.startswith("class "):  # its methods run later; its body may not talk
                    e = self.def_body_end(i)
                    if any(self.stmt(y, depth) != NONE for y in self.x[i + 1:e]
                           if y.strip() and _indent(y) == 4 and not y.strip().startswith(("def ", "@"))):
                        return TALK
                    i = e
                    continue
                if top and not self.js and s.startswith("@"):
                    return TALK
                if top and self.js and JS_IIFE.match(s):  # the suite's main body
                    return self.walk(i + 1, self.block_end(i, ind) - 1, ind + 2, depth)
                g = self.guard.match(s)
                if g:
                    e = self.block_end(i, ind)
                    r = self.walk(i + 1, e - 1 if self.js else e, ind + (2 if self.js else 4), depth)
                    if r != NONE:
                        return r
                    i = e
                    continue
                if self.start.match(s):
                    return START
                if (JS_OPEN if self.js else PY_OPEN).match(s):
                    return TALK
            r = self.stmt(y, depth)
            if r != NONE:
                return r
            i += 1
        return NONE

    def def_body_end(self, i):
        if self.js:
            return i + 1 if not self.x[i].rstrip().endswith("{") else self.block_end(i, 0)
        j = i
        while j < len(self.x) and not self.x[j].endswith(":"):
            j += 1
        return self.block_end(j, 0)


FOLLOW = ("first start.sh call is not a top-level statement", "start.sh call is inside a function or condition",
          "first start.sh call is not subprocess.run(start.sh)")


def follows(lines, js):
    """2.381.0 (#2712): True when the suite's first step that can reach the server is start.sh (see Scan)."""
    sc = Scan(lines, js)
    return sc.walk(0, len(sc.x), 0, 0, top=True) == START


def suites():
    sys.path.insert(0, N)
    import suites as _suites  # 2.321 (#1368): the suite list (suites.txt + marker files)
    for _, name, fname in _suites.rows(N):
        if fname:
            yield name, fname


def code_lines(path):
    """The lines of the file without the module docstring / leading comment block (they name start.sh in prose)."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    if path.endswith(".py"):
        src = "\n".join(lines)
        m = re.match(r'(#![^\n]*\n)?\s*("""|\'\'\')', src)
        if m:
            end = src.find(m.group(2), m.end())
            skip = src[:end].count("\n") + 1
            return [(i, "" if i < skip else x) for i, x in enumerate(lines)]
    return list(enumerate(lines))


def qualifies(fname):
    """None = qualifies, else the reason it does not."""
    why = _qualifies(fname)
    if why in FOLLOW and follows(code_lines(os.path.join(N, fname)), fname.endswith(".js")):
        return None  # 2.381.0 (#2712)
    return why


def _qualifies(fname):
    path = os.path.join(N, fname)
    if not os.path.exists(path):
        return "no file"
    lines = code_lines(path)
    js = fname.endswith(".js")
    strip = (lambda x: x.split("//")[0]) if js else (lambda x: x.split("#")[0])
    if any(KEEP.search(strip(x)) for _, x in lines):
        return "uses KEEP"
    first = next((i for i, x in lines if "start.sh" in strip(x)), None)
    if first is None:
        return "no start.sh call"
    x = lines[first][1]
    if js:
        if not JS_START.match(x):
            return "first start.sh call is not a top-level statement"
        before = [y for _, y in lines[:first] if y and not y[0].isspace() and not y.startswith(("//", "}", ")"))]
        if any(JS_TALK.match(y) for y in before):
            return "talks to the server before start.sh"
    else:
        if not PY_START.match(x.strip()):
            return "first start.sh call is not subprocess.run(start.sh)"
        if x[0].isspace():
            prev = next((y for _, y in reversed(lines[:first]) if y.strip()), "")
            if not PY_GUARD.match(prev) or len(x) - len(x.lstrip()) != 4:
                return "start.sh call is inside a function or condition"
        before = [y for _, y in lines[:first] if y and not y[0].isspace() and not y.startswith(("#", "def ", "class ", "@"))]
        if any(PY_TALK.search(y) for y in before):
            return "talks to the server before start.sh"
    return None


# 2.381.0 (#2712): one snippet per pattern follows() knows - True = qualifies, False = must stay out
SELFTEST = [
    ("py: def start() called first", False, True, """
import testclock


def start(with_key=True):
    env = dict(os.environ, EXTRA="-e X=1")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0


class S(requests.Session):
    pass


TODAY = testclock.today()
A = start()
s0 = S()"""),
    ("py: guard with a plain line before start.sh", False, True, """
if os.environ.get("X_NOSTART") != "1":
    env = dict(os.environ, EXTRA="-e X=1")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, env=env)
s0 = requests.Session()"""),
    ("py: guard with a comment", False, True, """
if not (os.environ.get("X_NOSTART") or os.environ.get("KMT_NOSTART")):  # a quick local run
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True)"""),
    ("py: NOSTART variable", False, True, """
NOSTART = os.environ.get("X_NOSTART") == "1"
if not NOSTART:
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True)"""),
    ("py: STARTED variable", False, True, """
STARTED = not os.environ.get("X_NOSTART")
if STARTED:
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True)"""),
    ("js: const fresh = () => {...}, first in the main body", True, True, """
const {boot, sleep, B, login} = require('./boot');
const fresh = async (env = {}) => {
  execFileSync('bash', [path.join(__dirname, 'start.sh')], {stdio: 'ignore', env: {...process.env, ...env}});
  for (let i = 0; i < 60; i++) { try { if ((await fetch(B + 'api/health')).ok) break; } catch { /* not up yet */ } await sleep(500); }
};
(async () => {
  // the setup
  await fresh();
  const w = await boot();
})();"""),
    ("js: arrow with one expression", True, True, """
const fresh = code => execFileSync('bash', [path.join(__dirname, 'start.sh')], {stdio: 'ignore', env: {...process.env, X: code}});
(async () => {
  fresh('');
})();"""),
    ("js: function restart() at the top level", True, True, """
function restart(env) {
  const e = {...process.env, ...env};
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: e});
}
restart({});"""),
    ("js: guard block", True, True, """
if (!process.env.X_NOSTART && !process.env.KMT_NOSTART) {
  const env = {...process.env};
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env});
}"""),
    ("js: NOSTART variable", True, True, """
const NOSTART = !!process.env.X_NOSTART;
if (!NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});"""),
    # must stay out
    ("py: a request before start()", False, False, """
def start():
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True)


requests.get(B + "/api/health")
start()"""),
    ("py: start() whose first step talks", False, False, """
def start():
    s0.post(B + "/api/x")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True)


start()"""),
    ("py: an object (its __init__) before start()", False, False, """
class Api:
    def __init__(self):
        self.s = requests.Session()


def start():
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True)


A = Api()
start()"""),
    ("py: start.sh behind another condition", False, False, """
if not os.environ.get("BASE"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True)"""),
    ("py: a loop before start.sh", False, False, """
for i in range(3):
    pass
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True)"""),
    ("py: a docker exec into the old container first", False, False, """
subprocess.run(["docker", "exec", CT, "true"])
if not os.environ.get("X_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True)"""),
    ("py: a NOSTART variable set twice", False, False, """
NOSTART = os.environ.get("X_NOSTART") == "1"
NOSTART = True
if not NOSTART:
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True)"""),
    ("js: a helper of boot.js before fresh()", True, False, """
const {boot, sleep, B, login} = require('./boot');
const fresh = () => execFileSync('bash', [path.join(__dirname, 'start.sh')], {stdio: 'ignore'});
(async () => {
  const ck = await login('alice');
  fresh();
})();"""),
    ("js: another awaited step first", True, False, """
const fresh = () => execFileSync('bash', [path.join(__dirname, 'start.sh')], {stdio: 'ignore'});
(async () => {
  await swCheck();
  fresh();
})();"""),
    ("js: start.sh behind BASE", True, False, """
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});"""),
    ("js: a loop over parts", True, False, """
const start = () => { execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'}); };
(async () => {
  for (const n of Object.keys(PARTS)) await PARTS[n]();
})();"""),
]


def selftest():
    fails = []
    for what, js, want, src in SELFTEST:
        if follows(list(enumerate(src.split("\n"))), js) != want:
            fails.append(what)
            print("FAIL: selftest", what, "->", "qualifies" if not want else "stays out", "expected")
    return fails


def main():
    all_suites = list(suites())
    if "--list" in sys.argv:
        print("# 2.180.0 C (#2695): suites that start their own fresh container first thing (tests/selfstart_test.py --list)")
        print("# run_all.sh skips the start of `fresh` for them; tests/selfstart_test.py guards every line")
        for name, fname in all_suites:
            if qualifies(fname) is None:
                print(name)
        return 0
    files = dict(all_suites)
    with open(os.path.join(N, "selfstart.txt"), encoding="utf-8") as f:
        listed = [x.strip() for x in f if x.strip() and not x.startswith("#")]
    fails, ok = selftest(), 0
    for name in listed:
        why = "not in run_all.sh" if name not in files else qualifies(files[name])
        if why:
            fails.append(f"{name}: {why}")
            print("FAIL:", name, why)
        else:
            ok += 1
    if len(set(listed)) != len(listed):
        fails.append("names twice")
        print("FAIL: a name is listed twice")
    print(f"selfstart: {ok} ok, {len(fails)} failed ({len(listed)} suites start their own container, {len(SELFTEST)} patterns)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
