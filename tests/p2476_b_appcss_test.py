#!/usr/bin/env python3
# kalmido-suite: after=perf_budget nodata
"""2.476.0 part B (#3487): fewer merge conflicts in app.css and index.html. Static, no container:
 - tools/check_appcss.py: the tree is clean; app.css one line longer = exit 1 with a message that names start-<topic>.css;
   a start style file with an open block / an open comment / a wrong name = exit 1; changing a line of app.css stays fine
 - kalmido/core/strip.py with_start_css: app.css + the start files in name order, each after a comment naming it
 - tools/perf_budget.py counts the start style files into the start CSS (one big start file = Budget exceeded)
 - tools/check_layout.py: the start scripts below the mark in index.html are sorted; a new one above the mark = error
usage: python3 tests/p2476_b_appcss_test.py"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402

TOOLS = os.path.join(ROOT, "tools")
_SPEC = importlib.util.spec_from_file_location("p2476b_strip", os.path.join(ROOT, "kalmido", "core", "strip.py"))
st = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(st)


def run(tool, *a):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, tool), *a], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def put(p, text, mode="w"):
    with open(p, mode, encoding="utf-8") as f:
        f.write(text)


rc, out = run("check_appcss.py", "-v")
check(rc == 0, "the tree passes check_appcss: " + out)

with tempfile.TemporaryDirectory() as tmp:
    root = os.path.join(tmp, "tree")
    shutil.copytree(os.path.join(ROOT, "static"), os.path.join(root, "static"),
                    ignore=shutil.ignore_patterns("fonts", "*.png", "*.svg", "*.woff2", "i18n", "vendor"))
    app = os.path.join(root, "static", "app.css")
    orig = open(app, encoding="utf-8").read()
    put(app, orig.replace("{", "{ ", 1))  # a changed line: same count
    rc, out = run("check_appcss.py", "--root", root)
    check(rc == 0, "a changed line of app.css stays allowed: " + out)
    # 2.476.0 (#3487): the limit has a small margin over the count when the rule landed: grow app.css one line past it
    import re as _re
    cap = int(_re.search(r"^APPCSS_MAX_LINES = (\d+)", open(os.path.join(ROOT, "tools", "check_appcss.py"), encoding="utf-8").read(), _re.M).group(1))
    have = orig.count("\n") + (0 if orig.endswith("\n") else 1)
    put(app, orig + "".join(f".p2476-new{i} {{ color: red; }}\n" for i in range(max(1, cap - have + 1))))
    rc, out = run("check_appcss.py", "--root", root)
    check(rc == 1 and "grew" in out and "start-<topic>.css" in out and "static/css/<module>.css" in out,
          "app.css one line longer: exit 1, the message says where new rules go: " + out)
    put(app, orig)
    css = os.path.join(root, "static", "css")
    put(os.path.join(css, "start-p2476-open.css"), ".a { color: red;\n")
    rc, out = run("check_appcss.py", "--root", root)
    check(rc == 1 and "start-p2476-open.css: 1 block(s) not closed" in out, "a start file with an open block: " + out)
    put(os.path.join(css, "start-p2476-open.css"), "/* open\n.a { color: red; }\n")
    rc, out = run("check_appcss.py", "--root", root)
    check(rc == 1 and "start-p2476-open.css: a comment is not closed" in out, "a start file with an open comment: " + out)
    os.remove(os.path.join(css, "start-p2476-open.css"))
    put(os.path.join(css, "start-Big Name.css"), ".a { color: red; }\n")
    rc, out = run("check_appcss.py", "--root", root)
    check(rc == 1 and "start-<topic>.css" in out, "a start file with a wrong name: " + out)
    os.remove(os.path.join(css, "start-Big Name.css"))

    # with_start_css: name order, each part on its own lines after a comment naming it
    put(os.path.join(css, "start-zz-p2476.css"), ".zz { color: red; }\n")
    put(os.path.join(css, "start-aa-p2476.css"), ".aa { color: blue; }\n")
    files = [os.path.basename(p) for p in st.start_css_files(os.path.join(root, "static"))]
    check(files == sorted(files) and files.index("start-aa-p2476.css") < files.index("start-zz-p2476.css"),
          f"start_css_files in name order: {files}")
    check(not any(f in files for f in os.listdir(css) if not f.startswith("start-")), "only start-*.css, no module stylesheet")
    both = st.with_start_css(os.path.join(root, "static"), b"x{}\n").decode()
    check(both.startswith("x{}\n") and both.index(".aa {") < both.index(".zz {") and "/* css/start-zz-p2476.css */\n.zz" in both,
          "with_start_css: app.css first, then the files in name order")
    check(st.strip_asset("app.css", both.encode()).count(b"\n") == both.count("\n"), "the joined text strips with its line count")

    # perf_budget: the start style files count into the start CSS
    rc, out = run("perf_budget.py", "--root", root, "--json")
    first = lambda o: json.JSONDecoder().raw_decode(o.strip())[0]  # noqa: E731  (over the budget: the messages follow)
    before = first(out)["measured"]["start_css_bytes"]
    # 2.521.0 (#4391): the check is the gzip ceiling now, so the extra style file must not compress away
    put(os.path.join(css, "start-zz-p2476.css"), "".join(f".zz{os.urandom(8).hex()} {{ color: red; }}\n" for _ in range(40000)))
    rc, out = run("perf_budget.py", "--root", root, "--json")
    after = first(out)["measured"]["start_css_bytes"]
    check(after - before > 700000, f"perf_budget counts the start style files ({before} -> {after})")
    rc, out = run("perf_budget.py", "--root", root)
    check(rc == 1 and "Budget exceeded: decke_css_gzip" in out, "a big start style file goes over the start CSS ceiling: " + out)  # 2.521.0 (#4391)

rc, out = run("perf_budget.py")
check(rc == 0, "the tree stays within the budget (the start style files counted): " + out)

# check_layout.py on a copy of the tree: the sorted part of index.html
with tempfile.TemporaryDirectory() as tmp:
    root = os.path.join(tmp, "tree")
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "node_modules", "fonts", "*.png", "*.woff2", "i18n",
                                                              "vendor", "docs", "__pycache__", ".data*"))
    idx = os.path.join(root, "static", "index.html")
    h = open(idx, encoding="utf-8").read()
    main = '<script src="/static/js/main.js" defer></script>\n'
    tag = lambda n: f'<script src="/static/js/{n}.js" defer></script>\n'  # noqa: E731

    def lay():
        r = subprocess.run([sys.executable, os.path.join(root, "tools", "check_layout.py")], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    put(idx, h.replace(main, tag("zz-p2476") + tag("aa-p2476") + main))
    rc, out = lay()
    check(rc == 1 and "sorted by name" in out, "two new start scripts below the mark, not sorted: error " + out[-400:])
    # 2.635.0 (#5006): the part below the mark holds real start scripts now (2.591.0 #4889: dropany.js): "aa-" goes right
    # under the mark, "zz-" right before main.js, so the two sort around whatever stands there
    mark = re.search(r"<!-- [^\n]*new start scripts go below this line[^\n]*-->\n", h).group(0)
    put(idx, h.replace(mark, mark + tag("aa-p2476")).replace(main, tag("zz-p2476") + main))
    rc, out = lay()
    check("sorted by name" not in out and "above the mark" not in out, "sorted below the mark: no order error " + out[-400:])
    first = '<script src="/static/js/reloadguard.js" defer></script>\n'
    # 2.476.0 (#3487): as many new scripts above the mark as it takes to pass the limit (it has a small margin)
    top_max = int(re.search(r"^LAYOUT_TOP_MAX = (\d+)", open(os.path.join(ROOT, "tools", "check_layout.py"), encoding="utf-8").read(), re.M).group(1))
    top_now = len(re.findall(r"<script src=\"/static/js/[\w-]+\.js\"", h.split("new start scripts go below this line")[0]))
    put(idx, h.replace(first, first + "".join(tag(f"aa-p2476-{i}") for i in range(max(1, top_max - top_now + 1)))))
    rc, out = lay()
    check(rc == 1 and "above the mark (limit" in out, "a new start script above the mark: error " + out[-400:])
    put(idx, h.replace("new start scripts go below this line", "x"))
    rc, out = lay()
    check(rc == 1 and "mark of the sorted start scripts" in out, "the mark is gone: error " + out[-400:])

print(f"{OKS[0]} ok, {'FAILED ' + str(len(FAILS)) if FAILS else 'all ok'}")
sys.exit(1 if FAILS else 0)
