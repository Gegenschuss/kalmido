#!/usr/bin/env python3
"""#5300 (Profi-Bewertung F18): the findings of CodeQL (SARIF) and of the Trivy image scan (JSON) as a Markdown summary.

Both scans only report for now (no gate, decision 08.11.2026): this tool prints the HIGH / CRITICAL findings as a table
for $GITHUB_STEP_SUMMARY and always exits 0 - a broken or missing report is a line in the summary, never a red job.

usage:
  python3 tools/scan_summary.py sarif DIR_OR_FILE...   CodeQL: every *.sarif; high = security-severity >= 7.0, critical >= 9.0
  python3 tools/scan_summary.py trivy FILE.json        Trivy: Results[].Vulnerabilities[] with Severity HIGH / CRITICAL
  python3 tools/scan_summary.py --selftest             checks both readers on small built-in samples (no network)
"""
import glob
import json
import os
import sys

ROWS = 60  # the summary lists at most this many findings, then a count of the rest


def _level(score):
    """CodeQL's security-severity (CVSS-like number as a string) -> CRITICAL / HIGH / '' (lower is not listed)."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    return "CRITICAL" if s >= 9.0 else "HIGH" if s >= 7.0 else ""


def _cell(text):
    return " ".join(str(text or "").split()).replace("|", "\\|")[:160]


def sarif_findings(paths):
    """-> (findings [(level, rule, file:line, message)], notes [str]) of every SARIF file under PATHS."""
    files, out, notes = [], [], []
    for p in paths:
        files += sorted(glob.glob(os.path.join(p, "**", "*.sarif"), recursive=True)) if os.path.isdir(p) else [p]
    if not files:
        notes.append("no SARIF file found (" + ", ".join(paths) + ")")
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as e:
            notes.append(f"{os.path.basename(f)} not readable: {e}")
            continue
        for run in doc.get("runs") or []:
            rules = {}
            for r in ((run.get("tool") or {}).get("driver") or {}).get("rules") or []:
                rules[r.get("id")] = (r.get("properties") or {}).get("security-severity")
            for res in run.get("results") or []:
                rid = res.get("ruleId") or ""
                lvl = _level((res.get("properties") or {}).get("security-severity") or rules.get(rid))
                if not lvl:
                    continue
                loc = ((res.get("locations") or [{}])[0].get("physicalLocation") or {})
                where = (loc.get("artifactLocation") or {}).get("uri", "?")
                line = (loc.get("region") or {}).get("startLine")
                out.append((lvl, rid, f"{where}:{line}" if line else where, (res.get("message") or {}).get("text", "")))
    return out, notes


def trivy_findings(path):
    """-> (findings [(level, id, package version -> fixed, title)], notes) of a Trivy JSON report."""
    out, notes = [], []
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        return out, [f"{path} not readable: {e}"]
    for res in doc.get("Results") or []:
        for v in res.get("Vulnerabilities") or []:
            sev = (v.get("Severity") or "").upper()
            if sev not in ("HIGH", "CRITICAL"):
                continue
            pkg = f"{v.get('PkgName', '?')} {v.get('InstalledVersion', '')}".strip()
            fix = v.get("FixedVersion") or "no fix yet"
            out.append((sev, v.get("VulnerabilityID", "?"), f"{pkg} -> {fix}", v.get("Title") or res.get("Target", "")))
    return out, notes


def markdown(title, cols, findings, notes):
    """The summary block: counts, then the table (critical first), then the notes."""
    findings = sorted(set(findings), key=lambda f: (f[0] != "CRITICAL", f[1], f[2]))
    crit = sum(1 for f in findings if f[0] == "CRITICAL")
    lines = [f"### {title}", "", f"**{crit} critical, {len(findings) - crit} high** (reporting only, no gate)", ""]
    if findings:
        lines += ["| Severity | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
        lines += ["| " + " | ".join(_cell(c) for c in f) + " |" for f in findings[:ROWS]]
        if len(findings) > ROWS:
            lines.append(f"\n... and {len(findings) - ROWS} more (see the report artifact)")
    lines += [f"\n_{n}_" for n in notes]
    return "\n".join(lines) + "\n"


def selftest():
    import tempfile
    d = tempfile.mkdtemp()
    sar = {"runs": [{"tool": {"driver": {"rules": [{"id": "py/sql", "properties": {"security-severity": "8.8"}},
                                                    {"id": "js/low", "properties": {"security-severity": "3.1"}}]}},
                     "results": [{"ruleId": "py/sql", "message": {"text": "a | b"},
                                  "locations": [{"physicalLocation": {"artifactLocation": {"uri": "kalmido/x.py"}, "region": {"startLine": 7}}}]},
                                 {"ruleId": "js/low", "message": {"text": "low"}},
                                 {"ruleId": "js/xss", "properties": {"security-severity": "9.3"}, "message": {"text": "xss"}}]}]}
    with open(os.path.join(d, "python.sarif"), "w", encoding="utf-8") as fh:
        json.dump(sar, fh)
    f, n = sarif_findings([d])
    assert sorted(x[0] for x in f) == ["CRITICAL", "HIGH"] and ("HIGH", "py/sql", "kalmido/x.py:7", "a | b") in f and not n, f
    md = markdown("CodeQL", ["Rule", "Where", "Message"], f, n)
    assert "**1 critical, 1 high**" in md and "a \\| b" in md and md.index("js/xss") < md.index("py/sql"), md
    tv = {"Results": [{"Target": "img", "Vulnerabilities": [
        {"VulnerabilityID": "CVE-1", "PkgName": "openssl", "InstalledVersion": "3.0", "FixedVersion": "3.1", "Severity": "CRITICAL", "Title": "t"},
        {"VulnerabilityID": "CVE-2", "PkgName": "zlib", "InstalledVersion": "1", "Severity": "MEDIUM"},
        {"VulnerabilityID": "CVE-3", "PkgName": "curl", "InstalledVersion": "8", "Severity": "HIGH"}]}]}
    p = os.path.join(d, "trivy.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(tv, fh)
    f, n = trivy_findings(p)
    assert len(f) == 2 and ("HIGH", "CVE-3", "curl 8 -> no fix yet", "img") in f, f
    f, n = trivy_findings(os.path.join(d, "missing.json"))
    assert not f and n and "not readable" in n[0], n
    f, n = sarif_findings([os.path.join(d, "empty")])
    assert not f and n, n
    print("scan_summary selftest: ok")
    return 0


def main(argv):
    if argv[1:2] == ["--selftest"]:
        return selftest()
    if len(argv) < 3 or argv[1] not in ("sarif", "trivy"):
        print(__doc__.strip(), file=sys.stderr)
        return 0  # reporting only: a wrong call is no red job either
    if argv[1] == "sarif":
        f, n = sarif_findings(argv[2:])
        sys.stdout.write(markdown("CodeQL (Python, JavaScript)", ["Rule", "Where", "Message"], f, n))
    else:
        f, n = trivy_findings(argv[2])
        sys.stdout.write(markdown("Trivy (app image)", ["ID", "Package -> fixed in", "Title"], f, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
