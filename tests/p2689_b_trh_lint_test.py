#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.689.0 (#5125, rest of #4074 point 8) tools/check_trh.py: no unescaped value through tr() / trn() into HTML; no container.
 1. the web client as it is: no finding, no stale line in tools/trh_ok.txt (red before the callers moved to trh / trnh)
 2. the rule on small sources: a name through ${tr( in a template with markup is a finding, through trn( too (not its n);
    trh / trnh, esc(), a number, x.length, a constant, a translation of its own, markup built on purpose are not
 2b. trh / trnh with an esc() value is escaped twice: a finding (review: projtime.js); esc(a) + b.name is no esc() call
 3. what the check leaves to the code: a template without markup (text), a tr() inside another call (esc(tr(…)),
    a helper taking a label) or inside an array literal, a tr() of a nested template is checked on its own
 4. a ternary and a string join land directly in the template: checked
 5. the allow list: a line names file|key|value; a line that matches nothing any more is red (stale)
usage: python3 tests/p2689_b_trh_lint_test.py"""
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from kt import check, done  # noqa: E402
import check_trh  # noqa: E402

# 1. the repository
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_trh.py")], capture_output=True, text=True, timeout=300)
check(r.returncode == 0, "the web client: no unescaped value through tr() into HTML: " + (r.stdout + r.stderr)[-800:])


def found(src):
    return [(fn, bad) for _l, fn, _k, bad, _p in check_trh.findings("x.js", src)]


# 2. the rule
check(found("h = `<p>${tr('{0} invites you', name)}</p>`;") == [("tr", ["name"])], "a name through ${tr( into markup")
check(found("h = `<p>${trn('{0} task of {1}', '{0} tasks of {1}', n, p.title)}</p>`;") == [("trn", ["p.title"])],
      "trn: the value after n, not n itself")
for ok, what in (("${trh('{0} invites you', name)}", "trh"), ("${trnh('{0} of {1}', '{0} of {1}', n, who)}", "trnh"),
                 ("${tr('{0} invites you', esc(name))}", "esc()"), ("${tr('Line {0}', 12)}", "a number"),
                 ("${tr('{0} rows', rows.length)}", "x.length"), ("${tr('Format {0}', '14:30')}", "a constant"),
                 ("${tr('In {0}', tr('Documents|folder'))}", "a translation"), ("${tr('By {0}', `<b>${esc(n)}</b>`)}", "markup on purpose"),
                 ("${tr('Round {0}', Math.round(x))}", "Math")):
    check(found(f"h = `<div>{ok}</div>`;") == [], f"not a finding: {what}")

check(found("h = `<p>${tr('{0} of {1}', esc(a) + b.name)}</p>`;") == [("tr", ["esc(a) + b.name"])],
      "esc(a) + b.name is not one esc() call: a finding")
check([x[2] for x in check_trh.double_escaped("h = `<p>${trh('{0} in {1}', n, esc(name))}</p>`;")] == ["esc(name)"],
      "trh with an esc() value: escaped twice (review 2.689: projtime.js showed &amp; in a project name)")
check(list(check_trh.double_escaped("// trh('{0}', esc(x)) in a comment\nh = trh('{0}', name);")) == [], "... not in a comment, not a plain value")

# 3. left to the code
check(found("t.textContent = `${tr('{0} invites you', name)} - ok`;") == [], "a template without markup is text")
check(found("h = `<p>${esc(tr('Only: {0}', name))}</p>`;") == [], "inside esc(…): escaped as a whole")
check(found("h = `<p>${sw(k, on, tr('Show {0}', name))}</p>`;") == [], "inside a helper's arguments: the helper decides")
check(found("h = `<select>${[['', tr('as the project ({0})', name)]].map(([v, n]) => `<option>${esc(n)}</option>`).join('')}</select>`;") == [],
      "inside an array literal mapped through esc() later")
check(found("h = `<ul>${xs.map(x => `<li>${tr('Line {0}', x.name)}</li>`).join('')}</ul>`;") == [("tr", ["x.name"])],
      "a nested template with markup is checked on its own")
check(found("const re = /`/; h = `<p>${tr('{0}', name)}</p>`;") == [("tr", ["name"])], "a regular expression with a backtick does not derail it")

# 4. directly in the template
check(found("h = `<p>${on ? tr('By {0}', who) : ''}</p>`;") == [("tr", ["who"])], "a ternary")
check(found("h = `<span>${u.x ? ' · ' + tr('SSO: {0}', u.login) : ''}</span>`;") == [("tr", ["u.login"])], "a string join")

# 5. the allow list
ok_before = check_trh.OK_FILE
try:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ok.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("# comment\nnowhere.js|'{0}'|gone  # a line that matches nothing\n")
        check_trh.OK_FILE = p
        out = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {os.path.join(ROOT, 'tools')!r}); import check_trh; "
                              f"check_trh.OK_FILE = {p!r}; sys.exit(check_trh.main(['--strict']))"], capture_output=True, text=True, timeout=300)
        check(out.returncode == 1 and "no longer found, remove: nowhere.js|'{0}'|gone" in out.stdout,
              "a stale line of the allow list is red with --strict (#4314: a note without): " + out.stdout[-300:])
        check("tr(} inserts 'when'" in out.stdout and "acctset.js" in out.stdout,
              "without the allow list the HTML on purpose (acctset.js: when) is a finding")
finally:
    check_trh.OK_FILE = ok_before

sys.exit(done("p2689_b_trh_lint"))
