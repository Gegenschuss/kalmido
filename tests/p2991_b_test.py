#!/usr/bin/env python3
"""2.99.1 (#1961): national e-invoice formats are contributed by pull request. Text/structure check without a server:
CONTRIBUTING.md names every format of EIN_FORMATS with its specification source, the section, the pull request
checklist and the issue template exist, and CI runs tools/einvoice_validate.sh."""
import os
import re
import sys

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
F, ok = [], 0


def check(c, what):
    global ok
    if c:
        ok += 1
    else:
        F.append(what)
        print("FAIL:", what)


def read(*p):
    with open(os.path.join(R, *p), encoding="utf-8") as f:
        return f.read()


contrib = read("CONTRIBUTING.md")
m = re.search(r"^## Contributing national e-invoice formats\n(.*?)(?=^## )", contrib, re.S | re.M)
check(m is not None, "CONTRIBUTING.md has the section 'Contributing national e-invoice formats'")
sec = m.group(1) if m else ""

src = read("kalmido", "office", "einvoice.py")
fm = re.search(r"^EIN_FORMATS\s*=\s*\(([^)]*)\)", src, re.M)
formats = re.findall(r"[\"']([a-z0-9_]+)[\"']", fm.group(1)) if fm else []
check(len(formats) >= 2, "EIN_FORMATS found in einvoice.py")
for f in formats:
    i = sec.find("`%s`" % f)
    check(i >= 0, "format %s is listed in the section" % f)
    block = sec[i:].split("\n\n")[0] if i >= 0 else ""  # the list entry with its continuation line
    check("http" in block and re.search(r"[Vv]ersion", block), "format %s names a specification link and version" % f)
for w in ("tools/einvoice_validate.sh", "SHA-256", "maintain", "EIN_FORMATS", "epdf_format", "issue"):
    check(w in sec, "section mentions %s" % w)

check("Adding a format" in src[:3000] and "CONTRIBUTING.md" in src[:3000], "einvoice.py points to CONTRIBUTING.md")

pr = read(".github", "pull_request_template.md")
check("New e-invoice format" in pr and "validator" in pr and "specification" in pr, "PR template has the e-invoice checklist")
check("## Checklist" in pr and "tests/run_all.sh" in pr, "PR template keeps the existing checklist")

tpl = os.path.join(".github", "ISSUE_TEMPLATE", "einvoice_format.yml")
check(os.path.exists(os.path.join(R, tpl)) and "E-invoice format proposal" in read(tpl), "issue template exists")

ci = read(".github", "workflows", "ci.yml")
check("tools/einvoice_validate.sh" in ci, "CI calls tools/einvoice_validate.sh")
check(os.path.exists(os.path.join(R, "tools", "einvoice_validate.sh")), "validator script exists")
check("CONTRIBUTING.md" in read("docs", "OFFICE.md"), "docs/OFFICE.md links to the section")

print("p2991_b: %d ok, %d failed" % (ok, len(F)))
sys.exit(1 if F else 0)
