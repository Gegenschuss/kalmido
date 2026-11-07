# kalmido-suite: nodata
"""2.623.0 (#4950): a test file ending with a bare done(...) is rejected by tools/check_done_exit.py; run_all.sh counts a
"N failed" summary line with N > 0 as red even at exit code 0. Static, no server."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
from kt import check, done  # noqa: E402
import check_done_exit  # noqa: E402

with tempfile.TemporaryDirectory() as d:
    def put(name, src):
        with open(os.path.join(d, name), "w") as f:
            f.write(src)
    put("bad_a_test.py", "from kt import done\ndone('x')\n")
    put("bad_b_test.py", "import kt\nkt.done('x')\n")
    put("good_test.py", "import sys\nfrom kt import done\nsys.exit(done('x'))\n")
    put("empty_test.py", "")
    errs = check_done_exit.errors(d)
    check(len(errs) == 2, f"lint flags exactly the two bare done() files: {errs}")
    check(any("bad_a_test.py" in e for e in errs) and any("bad_b_test.py" in e for e in errs), "both forms are named")
    check(not any("good_test" in e or "empty_test" in e for e in errs), "sys.exit(done()) and an empty file pass")
    rc = subprocess.run([sys.executable, os.path.join(HERE, "..", "tools", "check_done_exit.py"), d], capture_output=True).returncode
    check(rc == 1, "the command line exits 1 on a bare done()")

check(check_done_exit.errors() == [], f"no file in tests/ ends with a bare done(): {check_done_exit.errors()}")

# run_all.sh: the summary-line rule is there
src = open(os.path.join(HERE, "run_all.sh")).read()
check('ok, [1-9][0-9]* failed' in src and "rc=1" in src, "run_all.sh turns a 'N failed' line into red")
import re  # noqa: E402
rx = re.compile(r"ok, [1-9][0-9]* failed")
check(rx.search("x: 5 ok, 2 failed") and not rx.search("x: 5 ok, 0 failed"), "the pattern separates 2 failed from 0 failed")

sys.exit(done("p2623_a_done_exit"))
