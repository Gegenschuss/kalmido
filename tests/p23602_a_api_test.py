#!/usr/bin/env python3
"""2.360.2 (#2561, #2912, #2913): what needs no suite of its own.
freelancer-matrix: public
 - #2561: Server-Timing only for instance admins as in production (own container, KALMIDO_TEST_TIMING_ALL=0): the statement
   count told a known address from an unknown one
 - #2912: every uses: of a workflow on a full commit hash with the version behind it, Dependabot on, the release splits its rights
 - #2913: every pin of the Dockerfile is named in THIRD_PARTY_NOTICES.md, no Lucide section, no stale version
usage: p23602_a_api_test.py <datadir>   (KMT_NOSTART=1: only the file checks)"""
import glob
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check  # noqa: E402
import kt  # noqa: E402  2.1021.0 (#5775): kt.proved

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------ #2912 workflows
wf = sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))
check(len(wf) >= 2, "the workflows are there")
for p in wf:
    for i, line in enumerate(open(p, encoding="utf-8"), 1):
        m = re.match(r"\s*(?:- )?uses:\s*(\S+)(.*)$", line)
        if m and not m.group(1).startswith("./"):
            check(re.search(r"@[0-9a-f]{40}$", m.group(1)) and re.search(r"# v\d+\.\d+", m.group(2)),
                  f"#2912: {os.path.basename(p)}:{i} pinned to a commit hash with its version: {m.group(1)}")
dep = read(".github", "dependabot.yml")
check("package-ecosystem: github-actions" in dep and "interval: weekly" in dep, "#2912: Dependabot keeps the hashes current")
rel = read(".github", "workflows", "release.yml")
head, jobs = rel.split("\njobs:\n", 1)
check(not re.search(r"^\s+\S+: write", head, re.M), "#2912: no write right for the whole workflow")
job = {m.group(1): m.group(2) for m in re.finditer(r"^  ([a-z-]+):\n((?:    .*\n|\n)+)", jobs, re.M)}
check("packages: write" in job["release"] and "contents: write" not in job["release"], "#2912: the image job cannot write contents")
# 2.641.0 (#5011): release.yml has no job publish any more; the weekly release splits its rights the same way
check("publish" not in job and "gh release" not in job["release"], "#5011: release.yml makes no release page")
wk = read(".github", "workflows", "weekly-release.yml")
wjob = {m.group(1): m.group(2) for m in re.finditer(r"^  ([a-z-]+):\n((?:    .*\n|\n)+)", wk.split("\njobs:\n", 1)[1], re.M)}
check("write" not in wjob["pick"], "#5011: the weekly job with checkout cannot write")
check(len(re.findall(r"uses:", wjob["publish"])) == 1 and "download-artifact@" in wjob["publish"] and "contents: write" in wjob["publish"],
      "#5011: the weekly job that writes runs only download-artifact")
# 2.761.0 (#5218): code integrity stage 1b - the image (release.yml) and web-manifest-X.Y.Z.json (weekly-release.yml) get a
# GitHub build attestation (Sigstore, keyless); the signing job of the weekly release runs no code of the repository
ATT = "actions/attest-build-provenance@"
check(ATT in job["release"] and "id-token: write" in job["release"] and "attestations: write" in job["release"]
      and "subject-digest: ${{ steps.build.outputs.digest }}" in job["release"] and "subject-name: ${{ steps.v.outputs.image }}" in job["release"],
      "#5218: release.yml attests the pushed image digest")
check(job["release"].index(ATT) > job["release"].index("id: build"), "#5218: the attestation comes after the build")
check("id-token" not in head and all("id-token" not in j for n, j in job.items() if n != "release"), "#5218: only the image job of release.yml gets the OIDC token")
check("attest" in wjob and ATT in wjob["attest"] and "subject-path: dist/web-manifest-${{ needs.pick.outputs.version }}.json" in wjob["attest"],
      "#5218: the weekly release attests web-manifest-X.Y.Z.json")
check("checkout@" not in wjob["attest"] and "run:" not in wjob["attest"] and "contents: write" not in wjob["attest"]
      and "packages: write" not in wjob["attest"] and "id-token: write" in wjob["attest"],
      "#5218: the signing job: OIDC token, no checkout, no shell, no write right on contents / packages")
check(all("id-token" not in j for n, j in wjob.items() if n != "attest"), "#5218: no other weekly job has the OIDC token")
check(re.search(r"needs: \[pick, attest\]", wjob["publish"]) and "needs.attest.result == 'success'" in wjob["publish"],
      "#5218: the release is published only after the attestation")

# ------------------------------------------------------------------ #2913 notices
notes = read("THIRD_PARTY_NOTICES.md").lower()
pins = re.findall(r"([A-Za-z0-9_.-]+)(?:\[[a-z]+\])?==[0-9]", read("tools", "requirements.in"))  # #2915: the image installs from the lock, the direct pins stand here
check(len(pins) >= 15, f"#2913: the pins of the image are read ({len(pins)})")
for p in pins:
    check(p.lower() in notes, f"#2913: {p} is named in THIRD_PARTY_NOTICES.md")
check("psycopg-binary" in notes and "lgpl-3.0-only" in notes, "#2913: psycopg with its license")
check("lucide" not in notes, "#2913: the Lucide section is gone")
check(not re.search(r"^- \S+ \d+\.\d+", notes, re.M), "#2913: no version in the list that could go stale")
check("/usr/share/doc" in notes, "#2913: the system packages of the image are named")

# ------------------------------------------------------------------ #2561 Server-Timing
if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KALMIDO_TEST_TIMING_ALL="0"), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
    A = requests.Session()
    A.headers.update(H)
    assert A.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
    A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
    FID, Fr = freelancer(B, A)
    r = A.get(B + "/api/state")
    check(r.ok and "n=" in r.headers.get("Server-Timing", ""), f"#2561: the instance admin keeps Server-Timing {r.headers.get('Server-Timing')!r}")
    r = Fr.get(B + "/api/state")
    check(r.ok and "Server-Timing" not in r.headers, f"#2561: a person without an organisation gets none {r.headers.get('Server-Timing')!r}")
    kt.proved()  # 2.1021.0 (#5775): an organisation admin invites by address only an account that proved it
    r = Fr.put(B + "/api/orgs/1/members", json={"email": "nobody@example.com"})
    check("Server-Timing" not in r.headers, "#2561: no statement count on a refused invitation either")

print(f"p23602_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
