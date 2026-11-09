#!/usr/bin/env python3
# kalmido-suite: after=p2743_d_logout_ui nodata
"""2.743.0 D (#3794): the actions of the workflows on current major versions, Dependabot for the base images too (file checks only).
 - every action named in the decision stands at least on its major of 2.743 (no step back to a Node-20-era pin), with the
   commit hash and the version behind it (the same hash and version on every line of one action)
 - artifacts: the names a workflow uploads are unique (upload-artifact v4+ refuses a second upload under one name), every
   download names an artifact that the same workflow uploads
 - Dependabot: github-actions and docker (/ and /embed, the two Dockerfiles), each with a limit above the default 5
"""
import fnmatch
import glob
import os
import re
import sys

import yaml

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
from kt import check, done  # noqa: E402

MIN = {"actions/checkout": 7, "actions/setup-python": 7, "actions/setup-node": 7, "actions/cache": 6, "actions/cache/restore": 6,
       "actions/cache/save": 6, "actions/upload-artifact": 7, "actions/download-artifact": 8, "actions/setup-java": 6,
       "docker/login-action": 4, "docker/build-push-action": 7, "docker/setup-qemu-action": 4, "docker/setup-buildx-action": 4}
pins = {}
for p in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))):
    name, text = os.path.basename(p), open(p, encoding="utf-8").read()
    for m in re.finditer(r"uses:\s*([\w-]+/[\w/-]+)@([0-9a-f]{40}) # v(\d+)\.(\d+)\.(\d+)", text):
        pins.setdefault(m.group(1), set()).add((m.group(2), m.group(3) + "." + m.group(4) + "." + m.group(5)))
        if m.group(1) in MIN:
            check(int(m.group(3)) >= MIN[m.group(1)], f"#3794: {name}: {m.group(1)} on v{m.group(3)} (at least v{MIN[m.group(1)]})")
    wf = yaml.safe_load(text)
    up, down = [], []
    for job in (wf.get("jobs") or {}).values():
        for st in job.get("steps") or []:
            u = st.get("uses", "")
            if "upload-artifact@" in u:
                up.append((st.get("with") or {}).get("name"))
            if "download-artifact@" in u:
                w = st.get("with") or {}
                down.append(w.get("name") or w.get("pattern"))  # 2.754.0 (#5300): the coverage job takes every shard's data by pattern
    check(len(up) == len(set(up)) and None not in up, f"#3794: {name}: every upload has its own name {up}")
    upm = [re.sub(r"\$\{\{[^}]*\}\}", "*", x or "") for x in up]  # a matrix name = any value
    check(all(d in up or any(fnmatch.fnmatch(x, d) or fnmatch.fnmatch(d, x) for x in upm) for d in down), f"#3794: {name}: every download names an upload of the same workflow {down} {up}")
for a in MIN:
    check(a in pins, f"#3794: {a} is used")
for a, s in pins.items():
    check(len(s) == 1, f"#3794: {a}: one hash and version everywhere {sorted(s)}")

dep = yaml.safe_load(open(os.path.join(ROOT, ".github", "dependabot.yml"), encoding="utf-8"))
eco = {u["package-ecosystem"]: u for u in dep["updates"]}
check("github-actions" in eco and "docker" in eco, "#3794: Dependabot for the actions and the base images")
dk = eco.get("docker", {})
dirs = set(dk.get("directories") or [dk.get("directory")])
check({"/", "/embed"} <= dirs, f"#3794: docker for / and /embed {sorted(map(str, dirs))}")
for e in ("github-actions", "docker"):
    check((eco.get(e) or {}).get("open-pull-requests-limit", 5) > 5, f"#3794: {e}: more than the default 5 PRs open")
for d in ("Dockerfile", os.path.join("embed", "Dockerfile")):
    froms = re.findall(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)", open(os.path.join(ROOT, d), encoding="utf-8").read(), re.M)
    check(froms and all("@sha256:" in f for f in froms), f"#3794: {d}: every base image on a digest, Dependabot keeps it fresh {froms}")

sys.exit(done("p2743_d_ci_pins"))
