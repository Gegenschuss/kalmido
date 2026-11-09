#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.754.0 (#5298, #5300): the reporting-only CI parts (Profi-Bewertung F14, F18) - no container, no network.
 #5300 CodeQL (own workflow) and Trivy (job of ci.yml) report HIGH / CRITICAL in the job summary and never turn a run red:
  1. codeql.yml: Python + JavaScript, no upload (no write right), continue-on-error, summary via tools/scan_summary.py
  2. ci.yml job trivy: continue-on-error, Trivy as an image pinned by tag + digest (no third-party action), exit code 0
  3. tools/scan_summary.py --selftest (SARIF and Trivy JSON readers, severity cut, table)
 #5298 coverage of the server in the nightly full run, no gate:
  4. ci.yml: the coverage steps only for stage full on schedule / workflow_dispatch (never the release push), the data
     artifact includes the hidden .coverage.* files, the job "coverage" is continue-on-error
  5. tests/start.sh with a stand-in docker: KALMIDO_TEST_COVERAGE set = docker stop before the removal, the coverage
     mounts and `python /cov/lib/cov_boot.py` as the command; unset = the same docker run as before (no /cov, no command)
  6. tools/coverage_summary.py --selftest; tools/cov_boot.py runs a stand-in app and writes its data file, also when it
     ends on SIGTERM like `docker stop` (only where the coverage package is installed, else noted)
usage: python3 tests/p2754_l_ci_test.py"""
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from kt import check, done  # noqa: E402


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def job(text, name):
    """The block of one job (two-space key) of a workflow file."""
    m = re.search(r"^  " + re.escape(name) + r":\n((?:    .*\n|\n)+)", text, re.M)
    return m.group(1) if m else ""


# 1. CodeQL
cq = read(".github", "workflows", "codeql.yml")
head = cq.split("\njobs:\n", 1)[0]
check("python" in cq and "javascript-typescript" in cq, "#5300: CodeQL analyses Python and JavaScript")
check("upload: never" in cq and "security-events: write" not in cq and not re.search(r"^\s+\S+: write", cq, re.M),
      "#5300: CodeQL uploads nothing and asks for no write right")
check("continue-on-error: true" in cq, "#5300: a failed CodeQL analysis never turns the run red")
check("tools/scan_summary.py sarif" in cq and "GITHUB_STEP_SUMMARY" in cq, "#5300: CodeQL findings go into the job summary")
check("branches: [main]" in head and "schedule:" in head, "#5300: CodeQL runs on pushes to main and weekly")

# 2. Trivy
ci = read(".github", "workflows", "ci.yml")
tv = job(ci, "trivy")
check(tv and "continue-on-error: true" in tv.split("steps:", 1)[0], "#5300: the job trivy cannot turn the CI run red")
check(re.search(r"aquasec/trivy:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", tv), "#5300: Trivy runs as an image pinned by tag and digest")
check("--exit-code 0" in tv and "HIGH,CRITICAL" in tv and "tools/scan_summary.py trivy" in tv,
      "#5300: Trivy reports HIGH / CRITICAL into the summary, exit code 0")
check("uses: aquasecurity" not in ci, "#5300: no third-party Trivy action")

# 3. + 6. selftests of the summary tools
for tool in ("scan_summary.py", "coverage_summary.py"):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", tool), "--selftest"], capture_output=True, text=True)
    check(r.returncode == 0 and "selftest: ok" in r.stdout, f"tools/{tool} --selftest ({r.stdout.strip()} {r.stderr.strip()[-300:]})")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "scan_summary.py"), "trivy", "/nonexistent.json"],
                   capture_output=True, text=True)
check(r.returncode == 0 and "not readable" in r.stdout, "#5300: a missing report is a line in the summary, exit 0")

# 4. coverage in ci.yml
tests_job = job(ci, "tests")
cov_job = job(ci, "coverage")
nightly = "needs.plan.outputs.stage == 'full' && (github.event_name == 'schedule' || github.event_name == 'workflow_dispatch')"
check(nightly in tests_job and "KALMIDO_TEST_COVERAGE=" in tests_job, "#5298: the shards measure only in the nightly / by-hand full run")
check("include-hidden-files: true" in tests_job and "coverage-shard-" in tests_job, "#5298: the shard artifact keeps the .coverage.* files")
check(cov_job and nightly in cov_job and "continue-on-error: true" in cov_job.split("steps:", 1)[0],
      "#5298: the job coverage runs only then and never turns the run red")
check("tools/coverage_summary.py" in cov_job and "zero-coverage.txt" in cov_job and "GITHUB_STEP_SUMMARY" in cov_job,
      "#5298: figure + modules without coverage in the summary, zero list in the artifact")
check(re.search(r"coverage==\d+\.\d+\.\d+", tests_job) and re.search(r"coverage==\d+\.\d+\.\d+", cov_job), "#5298: coverage pinned")

# 5. tests/start.sh with a stand-in docker / curl
tmp = tempfile.mkdtemp(prefix="p2754l-")
bindir = os.path.join(tmp, "bin")
os.makedirs(bindir)
log = os.path.join(tmp, "docker.log")
stub = {"docker": f"""#!/bin/sh
echo "$*" >> "{log}"
case "$1 $2" in
  "network inspect") echo 192.0.2.1 ;;
  "ps -q") echo abc ;;
esac
exit 0
""", "curl": "#!/bin/sh\nexit 0\n", "sleep": "#!/bin/sh\nexit 0\n"}
for n, body in stub.items():
    p = os.path.join(bindir, n)
    with open(p, "w") as f:
        f.write(body)
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)


def start(cov):
    open(log, "w").close()
    env = dict(os.environ, PATH=bindir + os.pathsep + os.environ.get("PATH", ""), KALMIDO_TEST_CONTAINER="p2754l", KALMIDO_TEST_IMAGE="kalmido:p2754l",
               KALMIDO_TEST_DATA=os.path.join(tmp, "data"))
    env.pop("KALMIDO_TEST_COVERAGE", None)
    if cov:
        env["KALMIDO_TEST_COVERAGE"] = os.path.join(tmp, "cov")
    r = subprocess.run(["bash", os.path.join(HERE, "start.sh")], env=env, capture_output=True, text=True, timeout=60)
    with open(log) as f:
        return r, f.read().splitlines()


r, lines = start(False)
runs = [x for x in lines if x.startswith("run -d --name p2754l ")]
check(r.returncode == 0 and len(runs) == 1, f"start.sh with the stand-in docker starts one app container ({r.stderr[-300:]})")
check(runs and "/cov" not in runs[0] and runs[0].rstrip().endswith("kalmido:p2754l"),
      "#5298: without KALMIDO_TEST_COVERAGE the docker run is as before (image last, no command, no /cov)")
check(not any(x.startswith("stop ") for x in lines), "#5298: without coverage no docker stop before the removal")
r, lines = start(True)
runs = [x for x in lines if x.startswith("run -d --name p2754l ")]
check(r.returncode == 0 and runs and runs[0].rstrip().endswith("kalmido:p2754l python /cov/lib/cov_boot.py"),
      "#5298: with KALMIDO_TEST_COVERAGE the server runs under tools/cov_boot.py")
check(runs and f"{tmp}/cov/lib:/cov/lib:ro" in runs[0] and f"{tmp}/cov/data:/cov/data" in runs[0] and "PYTHONPATH=/cov/lib" in runs[0],
      "#5298: the coverage folders are mounted (lib read-only, data writable)")
stop_i = next((i for i, x in enumerate(lines) if x.startswith("stop -t 5 p2754l")), -1)
rm_i = next((i for i, x in enumerate(lines) if x.startswith("rm -f p2754l")), -1)
check(0 <= stop_i < rm_i, "#5298: under coverage the old container is stopped (SIGTERM, data written) before the removal")
check(os.path.isdir(os.path.join(tmp, "cov", "data")), "#5298: start.sh creates the data folder")

# 6. cov_boot with a stand-in app (needs the coverage package)
try:
    import coverage  # noqa: F401
    have_cov = True
except ImportError:
    have_cov = False
    print("note: coverage not installed here (tests/requirements.txt names it) - the cov_boot part is skipped")
if have_cov:
    app = os.path.join(tmp, "app")
    os.makedirs(os.path.join(app, "kalmido"))
    with open(os.path.join(app, "kalmido", "__init__.py"), "w") as f:
        f.write("def hello():\n    return 'hi'\n")
    with open(os.path.join(app, "app.py"), "w") as f:
        f.write("import sys, time\nimport kalmido\nprint(kalmido.hello(), flush=True)\n"
                "if sys.argv[1:] == ['wait']:\n    time.sleep(60)\n")
    for mode in ("exit", "term"):
        data = os.path.join(tmp, "covdata-" + mode)
        os.makedirs(data)
        env = dict(os.environ, KALMIDO_COV_APP=os.path.join(app, "app.py"), KALMIDO_COV_DATA=data, KALMIDO_COV_FLUSH_S="30")
        cmd = [sys.executable, os.path.join(ROOT, "tools", "cov_boot.py")] + (["wait"] if mode == "term" else [])
        p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if mode == "term":
            p.stdout.readline()  # the app printed its line: it is up (a real state, no fixed wait)
            p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=60)
        files = [f for f in os.listdir(data) if f.startswith(".coverage.")]
        check(len(files) == 1, f"#5298: cov_boot ({mode}) writes one data file ({files}, {err[-300:]})")
        if files:
            cd = coverage.CoverageData(os.path.join(data, files[0]))
            cd.read()
            measured = sorted(os.path.basename(x) for x in cd.measured_files())
            check(measured == ["__init__.py", "app.py"], f"#5298: cov_boot ({mode}) measured app.py and kalmido/ ({measured})")
        if mode == "term":
            check(p.returncode in (143, -15), f"#5298: on SIGTERM cov_boot ends the process (exit {p.returncode})")

sys.exit(done("p2754_l_ci"))
