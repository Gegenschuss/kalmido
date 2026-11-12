#!/usr/bin/env python3
"""2.589.0 (#4359, audit #2480 finding 6): the checks after the real update of an installation (tools/install_upgrade_check.py run,
the nightly CI job "install-upgrade"): the release before the candidate was installed with its install.sh, filled by
tests/upgrade_seed.py (which wrote <version>.json: what that release showed) and updated to the candidate with the update.sh
the installer wrote. Not a suite of its own; tests/p2589_d_install_upgrade_test.py runs the same checks against the test server.

    python3 install_upgrade_verify.py <datadir> <version>.json <candidate VERSION> [<install folder> [<ref of the update>]]

<datadir> holds .kalmido-db ("<db container> <database>", tests/dbx.py); KALMIDO_TEST_PORT / KALMIDO_TEST_CONTAINER as in kt.py.
Checks: the server runs the candidate (/api/version, kalmido_meta.app_version), its log since the start has no traceback, the
old accounts sign in and see their data as before (upgrade_views.data_checks: lists, tasks, comments, office documents, clients,
time entries, the agent, the boundaries between organisation, private workspace and frida), a write works. With the install
folder also what update.sh promises: a database copy in data/backups/, .kalmido-version = the candidate's ref and
.kalmido-version.prev = the version of before (vX.Y.Z or latest-ok/X.Y.Z, #5713), update.sh is still there."""
import glob
import json
import os
import subprocess
import sys

import kt
from kt import B, check
from upgrade_views import data_checks


def bad_lines(text):
    """Tracebacks fail; ERROR lines are only shown: a real installation logs some of its own (the virus scanner still
    loading its signatures, the update check), the test container has those switched off."""
    for ln in text.splitlines():
        if " ERROR" in ln or ln.startswith("ERROR"):
            print("   info, log:", ln[:300])
    return [ln for ln in text.splitlines() if "Traceback" in ln]


def verify(E, version, install_dir=None, ref=None):
    """All checks (kt.check); E = the JSON of upgrade_seed.py, version = the candidate's VERSION."""
    tag = f"{E['version']} -> {version}"
    meta = dict(kt.dbx("SELECT key, value FROM kalmido_meta"))
    check(meta.get("app_version") == version, f"{tag}: kalmido_meta.app_version = {version} ({meta.get('app_version')})")
    r = subprocess.run(["docker", "logs", kt.CT], capture_output=True, text=True)
    bad = bad_lines(r.stdout + r.stderr)
    check(r.returncode == 0 and not bad, f"{tag}: server log without traceback: {bad[:5]}")
    users = data_checks(E, tag)
    A = users["alice"]
    v = A.get(B + "/api/version")
    check(v.ok and v.json().get("app") == version, f"{tag}: /api/version names {version}: {v.status_code} {v.text[:200]}")
    t = A.post(B + "/api/tasks", json={"list_id": E["ids"]["team"], "title": "Nach dem Update angelegt"})
    check(t.ok, f"{tag}: a new task in the old org project: {t.status_code} {t.text[:200]}")
    nt = t.json().get("id") if t.ok else None
    check(nt and any(x["id"] == nt for x in users["bob"].get(B + "/api/state").json()["tasks"]), f"{tag}: bob sees the new org task")
    if not install_dir:
        return
    dumps = [p for p in glob.glob(os.path.join(install_dir, "data", "backups", "kalmido-*.dump")) if os.path.getsize(p) > 0]
    check(dumps, f"{tag}: update.sh made a database copy in data/backups/ ({dumps})")

    def first_line(name):
        try:
            with open(os.path.join(install_dir, name), encoding="utf-8") as f:
                return f.readline().strip()
        except OSError:
            return ""
    if ref:
        check(first_line(".kalmido-version") == ref, f"{tag}: .kalmido-version = {ref} ({first_line('.kalmido-version')})")
    # 2.1011.0 (#5713): a live version without release page was installed from its tag latest-ok/X.Y.Z
    prev = ("v" + E["version"], "latest-ok/" + E["version"])
    check(first_line(".kalmido-version.prev") in prev, f"{tag}: .kalmido-version.prev in {prev} ({first_line('.kalmido-version.prev')})")
    check(os.access(os.path.join(install_dir, "update.sh"), os.X_OK), f"{tag}: update.sh is still there")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    with open(sys.argv[2], encoding="utf-8") as f:
        EXP = json.load(f)
    verify(EXP, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None, sys.argv[5] if len(sys.argv) > 5 else None)
    sys.exit(kt.done("install_upgrade_verify"))
