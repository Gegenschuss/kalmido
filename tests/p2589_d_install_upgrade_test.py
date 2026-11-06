#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.589.0 D (#4359, audit #2480 finding 6): the nightly way install.sh (release before) -> update.sh (candidate) of the CI job
"install-upgrade", checked here as far as it runs without GitHub:
 - tools/install_upgrade_check.py: the release to start from (latest release when older than the candidate, else the newest
   tag below with a GitHub release; never the candidate itself, never a branch), the setup code from a log (newest line)
 - install.sh: the update.sh it writes takes KALMIDO_VERSION and KALMIDO_INSTALLER_URL (the nightly job updates through it)
 - ci.yml: the job runs only nightly / by hand, with actions and commit hashes the workflow already uses (#2912), calls the
   tool and keeps the old database as an artifact (install.ps1 goes through the PowerShell parser in p2450_b_lint)
 - against the test server, started like a real installation (one-time setup code in the log, onboarding, agent control,
   admin alerts at their defaults): tests/upgrade_seed.py needs the code (without it the setup is refused), fills the server,
   writes <version>.sql.gz + .json; tests/install_upgrade_verify.py then passes on it (version, sign-in, data, boundaries, a write)"""
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import kt
from kt import DATA, check

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import install_upgrade_check as iuc  # noqa: E402
import install_upgrade_verify as iuv  # noqa: E402

VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


# ---- the release to start from
TAGS = ["v2.586.0", "v2.587.0", "v2.587.1", "v2.588.0", "v2.589.0", "v2.590.0", "main", "v2.588.0-rc1"]
check(iuc.pick("2.589.0", TAGS, latest="v2.588.0") == "v2.588.0", "pick: the latest release when it is older than the candidate")
check(iuc.pick("2.589.0", TAGS, latest="v2.589.0") == "v2.588.0", "pick: latest = the candidate itself -> the newest tag below it")
check(iuc.pick("2.589.0", TAGS, latest=None, released=lambda t: t != "v2.588.0") == "v2.587.1",
      "pick: a tag without a GitHub release (red CI) is skipped, 2.587.1 above 2.587.0 (numbers, not text)")
check(iuc.pick("2.589.0", TAGS, latest="v2.590.0") == "v2.588.0", "pick: a latest release above the candidate is not taken")
check(iuc.pick("2.10.0", ["v2.9.0", "v2.10.0", "v2.100.0"]) == "v2.9.0", "pick: 2.9 is below 2.10")
check(iuc.pick("2.586.0", TAGS, released=lambda t: False) is None and iuc.pick("main", TAGS) is None, "pick: nothing older / no version -> None")

# ---- the setup code from a log
LOG = "x\n  Setup code: abcd-efgh-jkmn\n...restart...\n  Setup code: pqrs-tuvw-xyz2\n"
check(iuc.setup_code(LOG) == "pqrs-tuvw-xyz2" and iuc.setup_code("no code") == "", "setup code: the newest line counts, '' when none")

# ---- install.sh: the update.sh it writes (the way of step 3)
sh = read("install.sh")
upd = sh[sh.find("write_update_script()"):sh.find("UPD\n  chmod")]
check("KALMIDO_INSTALLER_URL" in upd and "releases/latest/download/install.sh" in upd and "KALMIDO_DIR" in upd,
      "install.sh: update.sh runs the installer of KALMIDO_INSTALLER_URL (default: the latest release) on its own folder")
check('  VERSION="${KALMIDO_VERSION:-}"' in sh and "*[!A-Za-z0-9._/-]*" in sh, "install.sh: KALMIDO_VERSION may name a commit")

# ---- ci.yml: the nightly job
ci = read(".github", "workflows", "ci.yml")
m = re.search(r"\n  install-upgrade:\n(.*?)(?=\n  [a-z][a-z0-9_-]*:\n|\Z)", ci, re.S)
check(m, "ci.yml: job install-upgrade")
job = m.group(1) if m else ""
check(re.search(r"\n    if: github\.event_name == 'schedule' \|\| github\.event_name == 'workflow_dispatch'\n", job),
      "install-upgrade runs only nightly / by hand, never on a push or pull request")
check("timeout-minutes:" in job and "fetch-depth: 0" in job, "install-upgrade: a time limit, the tags in the checkout")
check('python3 tools/install_upgrade_check.py run --ref "$GITHUB_SHA"' in job,
      "install-upgrade calls the tool for the commit of the run")
check("upload-artifact" in job and "upgrade-fixture" in job, "install-upgrade keeps the old database (the quarterly fixture) as an artifact")
used = {}
for name, ref in re.findall(r"uses: ([\w./-]+)@([0-9a-f]{40})", ci[:m.start()] if m else ci):
    used.setdefault(name, set()).add(ref)
mine = re.findall(r"uses: ([\w./-]+)@(\S+)", job)
check(mine and all(r in used.get(n, ()) for n, r in mine), f"#2912: install-upgrade uses only actions + hashes the workflow already has: {mine}")
try:
    import yaml
    y = yaml.safe_load(ci)
    check("install-upgrade" in y["jobs"] and not y["jobs"]["install-upgrade"].get("needs"), "ci.yml loads, install-upgrade has no needs")
except ImportError:
    print("info: no PyYAML, the YAML load is skipped")
# install.ps1 goes through the PowerShell parser in p2450_b_lint (since 2.501.0, #4296; on the CI runners pwsh is there)
check("Parser]::ParseFile" in read("tests", "p2450_b_lint_test.py"), "install.ps1: the parser check of p2450_b_lint is still there")

# ---- against the test server, set up like a real installation
os.environ.update(KALMIDO_SETUP_CODE="", KALMIDO_ONBOARDING="1", KALMIDO_AGENT_CONTROL_NEW="approve_all", KALMIDO_ADMIN_ALERTS="1")
kt.fresh()
code = kt.until(lambda: iuc.setup_code(iuc.container_log(kt.CT)), timeout=30)
check(re.fullmatch(r"[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}", code or ""), f"the server log shows a setup code ({code!r})")
out = tempfile.mkdtemp(prefix="p2589d-")
env = dict(os.environ, KALMIDO_TEST_PORT=kt.PORT, KALMIDO_TEST_CONTAINER=kt.CT, P2192C_DUMP_SHOTS=out, UPG_VERSION=VERSION)
env.pop("UPG_SETUP_CODE", None)
r = subprocess.run([sys.executable, "upgrade_seed.py", DATA], cwd=N, env=env, capture_output=True, text=True)
check(r.returncode != 0 and "setup" in (r.stdout + r.stderr) and not os.listdir(out),
      "upgrade_seed.py without the setup code: the setup is refused, nothing written")
r = subprocess.run([sys.executable, "upgrade_seed.py", DATA], cwd=N, env=dict(env, UPG_SETUP_CODE=code), capture_output=True, text=True)
check(r.returncode == 0, f"upgrade_seed.py with the code fills the server: {(r.stdout + r.stderr)[-1500:]}")
js, dump = os.path.join(out, VERSION + ".json"), os.path.join(out, VERSION + ".sql.gz")
check(os.path.isfile(js) and os.path.isfile(dump), f"upgrade_seed.py wrote {VERSION}.json + .sql.gz (UPG_VERSION)")
if os.path.isfile(js) and os.path.isfile(dump):
    with gzip.open(dump, "rb") as f:
        check(b"CREATE TABLE" in f.read(), "the dump holds the database")
    with open(js, encoding="utf-8") as f:
        E = json.load(f)
    check(E["version"] == VERSION and E["docs"]["alice"] and E["agents"] == ["nordbot"], "the JSON names the version, the documents, the agent")
    iuv.verify(E, VERSION)

shutil.rmtree(out, ignore_errors=True)
sys.exit(kt.done("p2589_d_install_upgrade"))
