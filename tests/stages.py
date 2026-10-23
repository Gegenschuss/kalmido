#!/usr/bin/env python3
"""Test stages: which suites a change needs (2.180.0 A, #2695).

Two stages: "full" runs every suite (nightly, before every live update = a push that changes VERSION, a change of the CI
basics, a commit with "[full]"); "push" runs (a) every security / rights / tenant / org / freelancer suite, (b) the core
flows, (c) the suites of the touched areas. A file that cannot be mapped safely (core server / client files, schema, test
helpers most suites use, anything unknown inside the image) makes the stage full. A chosen suite brings its whole group
(the `fresh` container and the suites after it in run_all.sh), as ONLY_GROUPS does. Static and fast: reads run_all.sh, the
test files and the changed files, nothing is started; Python standard library only.

  python3 tests/stages.py --changed BASE [HEAD]      stage + suites of a git range (HEAD default: the work tree)
  python3 tests/stages.py FILE ...                   the same for a list of changed files (paths relative to the repo)
    --why            one line per chosen suite: why it runs
    --suites         print only the suites of the chosen groups (space separated); exit 3 when the stage is full
    --groups-out F   write the first suite of every chosen group to F (tools/shards.py --only F)
    --security       list the always-run suites (security / rights / tenant / org / freelancer) and exit
    --touched        2.181.0 (#2696): only the suites of the changed files plus the suites before them in their group that
                     write a state file they read (*ids.json) and
                     the route guards for a new route (no always-run suites, never "full": unmappable files go to stderr);
                     prints the suites in run order, exit 3 when none; --why lists the reasons on stderr
  python3 tests/stages.py --ci                       CI mode (ci.yml job "plan"): the stage from the event (environment:
                     GITHUB_EVENT_NAME, CI_BEFORE, CI_INPUT_STAGE, CI_MESSAGE) and the changed files; prints "stage=" /
                     "reason=" lines, writes the groups of the push stage to --groups-out

On the Mac runner, only the suites a branch touches (exit 3 = the change needs the full run):
  s=$(python3 tests/stages.py --suites --changed origin/main) && kalmido-mactest.sh run $s
  kalmido-mactest.sh run --auto      (2.181.0, #2696: --touched against the merge base with main)
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from shards import FRESH_RE, RUN_RE  # noqa: E402  (the same group count as tools/shards.py and run_all.sh)

FILE_RE = re.compile(r"\s([A-Za-z0-9_./-]+\.(?:py|js))\b")
# the CI basics, the stage rules themselves and the release (VERSION): always the full run
FULL_EXACT = {
    "VERSION", "Dockerfile", ".dockerignore", "app.py", ".github/workflows/ci.yml",
    "tests/run_all.sh", "tests/start.sh", "tests/requirements.txt", "tests/package.json", "tests/package-lock.json",
    "tests/stages.py", "tools/shards.py",
    # test helpers (nearly) every suite uses
    "tests/boot.js", "tests/kt.py", "tests/ff.js", "tests/testclock.py", "tests/testclock.js", "tests/dbx.py",
    # server start, schema, request context
    "kalmido/__init__.py", "kalmido/startup.py",
    # client start files: every page needs them
    "static/index.html", "static/sw.js", "static/i18n.js", "static/app.css", "static/manifest.json",
}
FULL_PREFIX = ("kalmido/core/",)
FULL_CLIENT = {"core", "main", "lazyload", "render", "views", "reloadguard", "clienterr", "icons", "dialogs", "popovers",
               "sidebar", "workspace", "setcore", "vlist", "detail"}
# no suite depends on these (docs, the other CI jobs: lint, e-invoice, demo, MCP)
NONE_PREFIX = ("docs/", "changelog.d/", ".github/", "tools/", "mcp/", "tests/.data/", "tests/node_modules/")
NONE_SUFFIX = (".md", ".txt", "LICENSE")
# (a) always: security / rights / tenant / org / freelancer (by name, by the freelancer-matrix marker, by the head comment)
SEC_NAME_RE = re.compile(r"secur|rls|tenant|freelanc|auth|perm|isolat|org|oidc|twofa|signin|passkey|webauthn|csrf|privacy|"
                         r"rights|role|scope|guard|e2e|crypt|admin|access|share|public|token|login|session", re.I)
SEC_HEAD_RE = re.compile(r"secur|\brls\b|tenant|isolation\b|permission|rights|cross[- ]org|foreign org|other org|freelanc|"
                         r"mandant|row level", re.I)
# (b) the core flows: the first group (api, ui, settings_ui, news_ui, offline) and the first-run setup
CORE_SUITES = ("api", "setup_ui")
FULL_SHARE = 0.7  # a push stage that would run this share of the groups runs everything (and says so)


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def suites(run_all):
    """[(group index, suite, test file or None)] in the order of run_all.sh."""
    out, g = [], 0
    for line in read(run_all).splitlines():
        if FRESH_RE.match(line):
            g += 1
        m = RUN_RE.match(line)
        if m and g:
            f = FILE_RE.search(line[m.end() - 1:])
            out.append((g, m.group(3), f.group(1) if f else None))
    return out


class Repo:
    def __init__(self, root, run_all):
        self.root = root
        self.rows = suites(run_all)
        self.first = {}
        for g, s, _ in self.rows:
            self.first.setdefault(g, s)
        self.group_of = {s: g for g, s, _ in self.rows}
        self.by_file = {}
        for g, s, f in self.rows:
            if f:
                self.by_file.setdefault("tests/" + f, []).append(s)
        self._text = {}
        self.tests = sorted(os.path.join("tests", n) for n in os.listdir(os.path.join(root, "tests"))
                            if n.endswith((".py", ".js")))

    def text(self, rel):
        if rel not in self._text:
            self._text[rel] = read(os.path.join(self.root, rel))
        return self._text[rel]

    def security(self):
        """{suite: why} - the always-run suites."""
        out = {}
        for _, s, f in self.rows:
            if SEC_NAME_RE.search(s):
                out[s] = "security/rights by name"
                continue
            if not f:
                continue
            t = self.text("tests/" + f)
            if "freelancer-matrix:" in t:
                out[s] = "freelancer-matrix marker"
            elif SEC_HEAD_RE.search("\n".join(t.splitlines()[:25])):
                out[s] = "security/rights in the head comment"
        return out

    def mentioning(self, tokens):
        """Suites whose test file - or a helper it names, transitively - mentions one of the tokens: {suite: token}."""
        tokens = [t for t in tokens if t]
        hits, seen, queue = {}, set(), [(t, t) for t in tokens]
        while queue:
            tok, why = queue.pop(0)
            for rel in self.tests:
                if rel in seen or tok not in self.text(rel):
                    continue
                seen.add(rel)
                if rel in self.by_file:
                    for s in self.by_file[rel]:
                        hits.setdefault(s, why)
                else:  # a helper: the suites that use it too
                    stem = os.path.splitext(os.path.basename(rel))[0]
                    queue.append((stem, f"{why} via tests/{os.path.basename(rel)}"))
        return hits


def routes(text):
    """Route prefixes a server module defines ("/api/office/bank", "/api/v1/tasks/x" -> 4 parts for v1)."""
    out = set()
    for r in re.findall(r"\.(?:route|get|post|put|patch|delete)\(\s*[rf]?['\"](/[^'\"<]*)", text):
        parts = [p for p in r.split("/") if p]
        keep = 4 if parts[:2] == ["api", "v1"] else 3
        p = "/" + "/".join(parts[:keep])
        if len(p) > 4:
            out.add(p)
    return out


def py_module(rel):
    """kalmido/office/bank.py -> kalmido.office.bank"""
    return rel[:-3].replace("/", ".").removesuffix(".__init__")


def importers(repo, rel, depth=3):
    """Server modules that import rel (directly or up to depth steps), rel included."""
    pyfiles = []
    for d, _, fs in os.walk(os.path.join(repo.root, "kalmido")):
        pyfiles += [os.path.relpath(os.path.join(d, f), repo.root) for f in fs if f.endswith(".py")]
    found, frontier = {rel}, {rel}
    for _ in range(depth):
        nxt = set()
        for target in frontier:
            mod = py_module(target)
            name = mod.rsplit(".", 1)[-1]
            pkg = mod.rsplit(".", 1)[0]
            pat = re.compile(rf"(\b{re.escape(mod)}\b|from \.+ import [^\n]*\b{name}\b|from \.+{name}\b|"
                             rf"from {re.escape(pkg)} import [^\n]*\b{name}\b)")
            for p in pyfiles:
                if p not in found and pat.search(repo.text(p)):
                    nxt.add(p)
        found |= nxt
        frontier = nxt
        if not frontier:
            break
    return found


def js_tokens(text, stem):
    toks = {stem + ".js", f"'{stem}'", f'"{stem}"'}
    toks |= {n for n in re.findall(r"^(?:async )?function ([A-Za-z_$][\w$]{5,})\s*\(", text, re.M)}
    for r in re.findall(r"['\"`](/api/[A-Za-z0-9_/-]+)", text):  # the routes it calls (UI suites name them)
        parts = [x for x in r.split("/") if x]
        if len(parts) < 3:  # /api/lists, /api/settings: every UI suite sets up through them, not the module's area
            continue
        toks.add("/" + "/".join(parts[:4 if parts[:2] == ["api", "v1"] else 3]))
    toks |= {n for n in re.findall(r"^\s*window\.([A-Za-z_$][\w$]{5,})\s*=", text, re.M)}
    return toks


def diff_lines(base, head, rel, root):
    """(removed lines, added lines) of one file between base and head (or the work tree), None without a diff."""
    if not base:
        return None
    cmd = ["git", "-C", root, "diff", "-U0", base] + ([head] if head else []) + ["--", rel]
    try:
        d = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return ([ln[1:] for ln in d.splitlines() if ln.startswith("-") and not ln.startswith("---")],
            [ln[1:] for ln in d.splitlines() if ln.startswith("+") and not ln.startswith("+++")])


def i18n_only_added(base, head, rel, root):
    """True when the diff of a translation file only adds keys (a removed line comes back with a comma added)."""
    d = diff_lines(base, head, rel, root)
    if d is None:
        return False
    plus = {ln.strip().rstrip(",") for ln in d[1]}
    return all(ln.strip().rstrip(",") in plus for ln in d[0])


def run_all_added(base, head, root):
    """The suites of the run lines a diff of run_all.sh only adds (new suites / groups), None for any other change."""
    d = diff_lines(base, head, "tests/run_all.sh", root)
    if d is None or d[0]:
        return None
    new = []
    for ln in d[1]:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        m = RUN_RE.match(ln)
        if not m:
            return None
        new.append(m.group(3))
    return new


def classify(repo, path, base=None, head=None):
    """('full', why) | ('suites', {suite: why}) | ('none', why) for one changed file."""
    p = path.strip()
    p = p[2:] if p.startswith("./") else p
    name = os.path.basename(p)
    stem = os.path.splitext(name)[0]
    if p == "tests/run_all.sh":
        new = run_all_added(base, head, repo.root)
        if new is not None and all(n in repo.group_of for n in new):
            return "suites", {n: "new in run_all.sh" for n in new}
        return "full", "run_all.sh changed (not only suites added)"
    if p in FULL_EXACT or p.startswith(FULL_PREFIX):
        return "full", "core / CI basics"
    if p.startswith("static/i18n/") and p.endswith(".json"):
        if i18n_only_added(base, head, p, repo.root):
            return "none", "translations: keys added only"
        return "full", "translations changed (not only added)"
    if p.startswith("static/js/") and stem in FULL_CLIENT:
        return "full", "client start file"
    if p.startswith("tests/"):
        if p in repo.by_file:
            return "suites", {s: "its test file" for s in repo.by_file[p]}
        if p.startswith(NONE_PREFIX) or p.endswith(NONE_SUFFIX):
            return "none", "test data / docs"
        hits = repo.mentioning([name, stem])
        return ("suites", hits) if hits else ("none", "no suite uses it")
    if p.startswith(NONE_PREFIX) or p.endswith(NONE_SUFFIX) or "/" not in p and p.upper().startswith(("README", "CHANGELOG")):
        return "none", "docs / other CI jobs"
    if p.startswith("kalmido/") and p.endswith(".py"):
        if not os.path.exists(os.path.join(repo.root, p)):
            return "full", "server module removed"
        if name == "__init__.py":
            area = os.path.dirname(p)
            files = [os.path.join(area, f) for f in os.listdir(os.path.join(repo.root, area)) if f.endswith(".py")]
        else:
            files = sorted(importers(repo, p))
        toks = set()
        for f in files:
            toks |= routes(repo.text(f))
        hits = repo.mentioning(sorted(toks))
        if not hits:
            return "full", "server module without a route a suite names"
        return "suites", hits
    if p.startswith("static/js/") and p.endswith(".js"):
        hits = repo.mentioning(sorted(js_tokens(repo.text(p), stem)))
        return ("suites", hits) if hits else ("full", "client module no suite names")
    if p.startswith("static/css/") and p.endswith(".css"):
        hits = repo.mentioning([name])
        if os.path.exists(os.path.join(repo.root, "static/js", stem + ".js")):  # and the suites of its client module
            hits = {**repo.mentioning(sorted(js_tokens(repo.text("static/js/" + stem + ".js"), stem))), **hits}
        return ("suites", hits) if hits else ("full", "stylesheet no suite names")
    if p.startswith("static/") and not p.endswith((".js", ".css", ".html", ".json")):
        hits = repo.mentioning([name])
        return ("suites", hits) if hits else ("none", "static asset no suite names")
    if p.startswith("folderwatch/"):  # 2.207.0 B (#2763): the Go folder watcher (its Go tests run in the image build)
        hits = repo.mentioning(["folderwatch"])
        return ("suites", hits) if hits else ("full", "folder watcher no suite names")
    return "full", "not mapped (inside the image or unknown)"


def changed_files(base, head, root):
    cmd = ["git", "-C", root, "diff", "--name-only", "--no-renames", base] + ([head] if head else [])
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def select(repo, files, base=None, head=None):
    """(stage, reason, {group: [why...]}, {suite: why})"""
    why = {}
    for s, w in repo.security().items():
        why.setdefault(s, "always: " + w)
    for s in CORE_SUITES:
        if s in repo.group_of:
            why.setdefault(s, "always: core flow")
    full = []
    for f in files:
        kind, res = classify(repo, f, base, head)
        if kind == "full":
            full.append(f"{f} ({res})")
        elif kind == "suites":
            for s, w in res.items():
                why.setdefault(s, f"{f}: {w}")
    if full:
        return "full", "full run needed: " + "; ".join(full[:5]) + (f" (+{len(full) - 5})" if len(full) > 5 else ""), {}, why
    groups = {}
    for s, w in why.items():
        groups.setdefault(repo.group_of[s], []).append(f"{s}: {w}")
    total = len(repo.first)
    if total and len(groups) >= FULL_SHARE * total:
        return "full", f"the push stage would run {len(groups)} of {total} groups", groups, why
    return "push", f"{len(groups)} of {total} groups ({len(files)} changed files)", groups, why


# 2.181.0 (#2696): the route guards (static) - they run when a changed server file gains a route
COVERAGE_SUITES = ("tenant_coverage", "freelancer_coverage")
TOUCHED_BROAD = 60  # --touched: a file that maps to more suites than this is reported as not mapped instead
STATE_RE = re.compile(r"\b[a-z_]*ids\.json\b")  # the files suites of one group hand data over with
ROUTE_DEF_RE = re.compile(r"\.(?:route|get|post|put|patch|delete)\(\s*[rf]?['\"]/")


def touched(repo, files, base=None, head=None):
    """--touched (2.181.0, #2696, the Mac runner's small runs): only the suites of the changed files, each with the suites
    before it in its group that write a state file it reads (calendars_ui after calendars), plus the route guards when a
    server file gains a route; no always-run suites. A file that would need the full run is listed, not run (the CI does that).
    -> (suites in run order, {suite: why}, [unmapped files])"""
    why, unmapped = {}, []
    for f in files:
        kind, res = classify(repo, f, base, head)
        if kind == "suites" and f.startswith("kalmido/") and f.endswith(".py") and os.path.basename(f) != "__init__.py":
            # narrower than the push stage: the routes of the file itself (its importers only when it has none, one step)
            toks = routes(repo.text(f)) or set().union(*(routes(repo.text(x)) for x in importers(repo, f, depth=1)))
            # /api/lists, /api/settings: every UI suite sets up through them, not the module's area (as js_tokens)
            res = repo.mentioning(sorted(t for t in toks if t.count("/") >= 3)) or res
        if kind == "suites" and len(res) > TOUCHED_BROAD:  # a helper most areas use: that is the CI's full run
            kind, res = "full", f"too broad: {len(res)} suites"
        if kind == "full":
            unmapped.append(f"{f} ({res})")
        elif kind == "suites":
            for s, w in res.items():
                why.setdefault(s, f"{f}: {w}")
        if f.startswith("kalmido/") and f.endswith(".py"):
            d = diff_lines(base, head, f, repo.root)
            if d and any(ROUTE_DEF_RE.search(ln) for ln in d[1]):
                for s in COVERAGE_SUITES:
                    if s in repo.group_of:
                        why.setdefault(s, f"{f}: route added")
    # a chosen suite that reads a state file of its group (ids.json, cal_ids.json ...) needs the suites before it that
    # write it (calendars_ui after calendars, news_ui after news); the other suites set up their own data (ONLY runs them alone)
    for g, s, f in reversed(repo.rows):
        if s not in why or not f:
            continue
        for sf in set(STATE_RE.findall(repo.text("tests/" + f))):
            for g2, s2, f2 in repo.rows:
                if s2 == s:
                    break
                if g2 == g and f2 and s2 not in why and sf in repo.text("tests/" + f2):
                    why[s2] = f"writes {sf} for {s}"
    return [s for _, s, _ in repo.rows if s in why], why, unmapped


def git_ok(*args):
    try:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def ci_base():
    """(stage or None, reason, base) from the event (ci.yml job "plan", environment set there)."""
    ev = os.environ.get("GITHUB_EVENT_NAME", "")
    msg = os.environ.get("CI_MESSAGE", "")
    if ev == "schedule":
        return "full", "nightly run", None
    if ev == "workflow_dispatch":
        st = os.environ.get("CI_INPUT_STAGE", "") or "full"
        if st != "push":
            return "full", "started by hand (stage full)", None
        return None, "started by hand (stage push)", "HEAD^1"
    if "[full]" in msg:
        return "full", "commit message asks for [full]", None
    if ev == "pull_request":
        return None, "pull request", "HEAD^1"  # the merge commit: its first parent is the target branch
    if ev == "push":
        before = os.environ.get("CI_BEFORE", "")
        if not before or set(before) == {"0"}:
            return "full", "push without a previous commit", None
        if git_ok("cat-file", "-e", before + "^{commit}") is None:
            git_ok("fetch", "--no-tags", "--depth=1", "origin", before)
        return None, "push", before
    return "full", f"event {ev or 'unknown'}", None


def main(argv=None):
    ap = argparse.ArgumentParser(description="test stage (full / push) and the suites of a change", add_help=True)
    ap.add_argument("--changed", nargs="+", metavar=("BASE", "HEAD"))
    ap.add_argument("--why", action="store_true")
    ap.add_argument("--suites", action="store_true")
    ap.add_argument("--groups-out")
    ap.add_argument("--security", action="store_true")
    ap.add_argument("--touched", action="store_true")
    ap.add_argument("--ci", action="store_true")
    ap.add_argument("--run-all", default=os.path.join(HERE, "run_all.sh"))
    ap.add_argument("files", nargs="*")
    a = ap.parse_args(argv)
    repo = Repo(ROOT, a.run_all)
    if not repo.rows:
        print("stages.py: no suites in", a.run_all, file=sys.stderr)
        return 2
    if a.security:
        for s, w in repo.security().items():
            print(f"{s}  ({w})")
        return 0
    base = head = None
    pre = None
    if a.ci:
        pre, reason, base = ci_base()
        files = []
        if pre is None:
            if git_ok("rev-parse", "--verify", "-q", base + "^{commit}") is None:
                pre, reason = "full", f"{reason}: base {base} not available"
            else:
                files = changed_files(base, "HEAD", ROOT)
                head = "HEAD"
    elif a.changed:
        if len(a.changed) > 2:
            ap.error("--changed BASE [HEAD]")
        base, head = a.changed[0], (a.changed[1] if len(a.changed) > 1 else None)
        files = changed_files(base, head, ROOT) + a.files
    else:
        files = a.files
        if not files:
            ap.error("give --changed BASE [HEAD], --ci or changed files")
    if a.touched and not a.ci:  # 2.181.0 (#2696)
        order, why, unmapped = touched(repo, files, base, head)
        for u in unmapped:
            print(f"stages.py: not mapped to a suite: {u}", file=sys.stderr)
        if a.why:
            for s in order:
                print(f"  {s}: {why[s]}", file=sys.stderr)
        if not order:
            print("stages.py: no suite for the changed files", file=sys.stderr)
            return 3
        print(" ".join(order))
        return 0
    if pre:
        stage, groups, why = pre, {}, {}
    else:
        stage, r, groups, why = select(repo, files, base, head)
        reason = r if not a.ci else f"{reason}: {r}"
    if a.ci:  # ci.yml appends these lines to $GITHUB_OUTPUT
        print(f"stage={stage}\nreason={' '.join(reason.split())[:900]}")
    if a.groups_out:
        with open(a.groups_out, "w", encoding="utf-8") as f:
            for g in sorted(groups) if stage == "push" else []:
                f.write(repo.first[g] + "\n")
    if a.suites:
        if stage == "full":
            print(f"stages.py: {reason} - run everything", file=sys.stderr)
            return 3
        print(" ".join(s for g, s, _ in repo.rows if g in groups))
        return 0
    if not a.ci:
        print(f"stage: {stage} - {reason}")
        if stage == "push":
            n = sum(1 for g, _, _ in repo.rows if g in groups)
            print(f"groups: {len(groups)}, suites: {n} (of {len(repo.rows)})")
    if a.why and stage == "push":
        for g in sorted(groups):
            for line in groups[g]:
                print(f"  [{repo.first[g]}] {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
