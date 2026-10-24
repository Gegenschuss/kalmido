#!/usr/bin/env python3
"""Test tiers: core suites stop a release, edge suites open a bug task (2.284.0, #3121 #3122).

Every suite of run_all.sh has a tier in tests/tiers.txt ("<suite> kern|rand  <why>"):
  kern = sign-in / rights / tenant boundary, data + sync / live, office / invoices / e-invoices / receipts, deleting /
         retention, export / backup, migrations - and every server suite. A red core suite keeps the CI red.
  rand = the UI suites of the other areas. Red in the first try AND in the rerun of its group, it no longer makes the
         CI red: the shard passes with a clear note (annotation, summary); the live train opens a bug task for it.
A suite missing from tiers.txt (new) counts as kern. The list is fixed: `suggest` only proposes tiers, a person decides.

The CI shard step (ci.yml) after its rerun of the failed groups (2.80.1 / 2.149.0):
  python3 tests/tiers.py ci --first "A B" --rerun-log LOG --rerun-rc N [--out tests/timings-vermerk.txt]
    flaky = red in the first try, green in the rerun; still red = core (exit 1) or edge (exit 0). A rerun red without a
    "FAILED suites:" line (container start, time limit) stays red. Writes the note file (lines "wackler|rand-rot|kern-rot
    <suite>"), GitHub annotations ("::warning title=flaky suite X::") and the step summary ($GITHUB_STEP_SUMMARY).
  python3 tests/tiers.py done DIR          job "Test suites": the notes of every shard (DIR/**/timings-vermerk.txt) as ONE
                                           annotation "::notice title=kalmido-vermerk::wackler=A B; rand-rot=C" + summary
  python3 tests/tiers.py split [--json] SUITE...   the tier of each suite ("kern: …" / "rand: …")
  python3 tests/tiers.py suggest [--all]   the proposed tier of the suites missing from tiers.txt (--all: of every suite)
  python3 tests/tiers.py check             tiers.txt well formed (exit 1 if not); names suites missing / no longer there
Python standard library only (the CI lint job and the live train's tools run it without pip packages).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TIERS = os.path.join(HERE, "tiers.txt")
TIER_NAMES = ("kern", "rand")
FAILED_LINE_RE = re.compile(r"^FAILED suites: (.+)$", re.M)
# suggest: words in a UI suite's name or its head comment that make it core (Moritz 24.10.2026, #3122)
KERN_RE = re.compile(
    r"\b(office|invoices?|e-invoices?|einvoice|xrechnung|zugferd|ubl|receipts?|bank|bookings?|datev|vat|tax|ledger|"
    r"billing|payments?|offline|sync|syncs|synced|live updates?|sse|conflicts?|delete|deletes|deleting|deleted|trash|purge|"
    r"retention|retain|exports?|backups?|restore|imports?|migrations?|schema|setup|onboarding|sign[- ]?in|login|logout|"
    r"registration|register|passwords?|2fa|totp|passkeys?|webauthn|encrypt\w*|e2e|tenant|rls|permissions?|rights|"
    r"cross[- ]org|other org)\b", re.I)
CORE_FIRST = ("api", "ui", "settings_ui", "news_ui", "offline", "setup_ui")


def load(path=TIERS):
    """{suite: tier} from tiers.txt (comments and blank lines left out)."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                p = ln.split("#", 1)[0].split()
                if len(p) >= 2 and p[1] in TIER_NAMES:
                    out[p[0]] = p[1]
    except OSError:
        pass
    return out


def tier(suite, tiers=None):
    """kern unless tiers.txt says rand (a new suite is core)."""
    return "rand" if (load() if tiers is None else tiers).get(suite) == "rand" else "kern"


def split(suites, tiers=None):
    tiers = load() if tiers is None else tiers
    out = {"kern": [], "rand": []}
    for s in suites:
        out[tier(s, tiers)].append(s)
    return out


def suggest_rows():
    """[(suite, tier, why)] proposed for every suite of run_all.sh (stages.py reads the groups and the test files)."""
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
    import stages  # noqa: E402 - only for suggest (tools/shards.py next to it)
    repo = stages.Repo(os.path.dirname(HERE), os.path.join(HERE, "run_all.sh"))
    rows = []
    for _, s, f in repo.rows:
        t = repo.text("tests/" + f) if f else ""
        head = "\n".join(ln for ln in t.splitlines()[:8] if ln.lstrip().startswith(("//", "#", "*", "/*")))
        ui = bool(f) and f.endswith(".js") and ("_ui" in s or s.endswith("ui") or "firefox" in head.lower())
        m = KERN_RE.search(s.replace("_", " ")) or KERN_RE.search(head)
        if stages.SEC_NAME_RE.search(s):
            rows.append((s, "kern", "rights / security by name"))
        elif s in CORE_FIRST:
            rows.append((s, "kern", "core flow (first group, setup)"))
        elif not ui:
            rows.append((s, "kern", "server / data suite"))
        elif m:
            rows.append((s, "kern", "core area: " + m.group(0).lower()))
        else:
            rows.append((s, "rand", "UI suite of an edge area"))
    return rows


def failed_of(text):
    """The suites of the last "FAILED suites:" line of a run_all.sh output (None without one)."""
    m = FAILED_LINE_RE.findall(text or "")
    return m[-1].split() if m else None


def _esc(s):
    return s.replace("%", "%25").replace("\r", "").replace("\n", " ")


def ci(first, rerun_text, rerun_rc, out=None, summary=None, tiers=None):
    """The verdict of one CI shard after its rerun: (exit code, {"wackler", "rand-rot", "kern-rot"}, lines to print)."""
    tiers = load() if tiers is None else tiers
    again = failed_of(rerun_text)
    res = {"wackler": [], "rand-rot": [], "kern-rot": []}
    lines = []
    if rerun_rc != 0 and not again:
        lines.append("== rerun red without a list of failed suites (container start / time limit): the shard stays red")
        return rerun_rc or 1, res, lines
    again = again or []
    res["wackler"] = [s for s in first if s not in again]
    for s in again:
        res["rand-rot" if tier(s, tiers) == "rand" else "kern-rot"].append(s)
    for s in res["wackler"]:
        lines.append(f"::warning title=flaky suite {s}::{_esc(s)} red in the first try, green in the rerun of its group "
                     "(counts as green, tests/tiers.py)")
    for s in res["rand-rot"]:
        lines.append(f"::warning title=edge suite {s} red::{_esc(s)} red in the first try and in the rerun; an edge area "
                     "(tests/tiers.txt rand): the shard passes, the live train opens a bug task")
    for s in res["kern-rot"]:
        lines.append(f"== core suite {s} red in the rerun too: the shard stays red")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            for k in ("wackler", "rand-rot", "kern-rot"):
                for s in res[k]:
                    f.write(f"{k} {s}\n")
    if summary and (res["wackler"] or res["rand-rot"] or res["kern-rot"]):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### Shard {os.environ.get('SHARD', '?')}: rerun\n\n")
            if res["wackler"]:
                f.write("- flaky, green in the rerun (counts as green): " + ", ".join(res["wackler"]) + "\n")
            if res["rand-rot"]:
                f.write("- **edge suites red** in both tries (do not stop the release, bug task by the live train): "
                        + ", ".join(res["rand-rot"]) + "\n")
            if res["kern-rot"]:
                f.write("- **core suites red** in both tries (the run is red): " + ", ".join(res["kern-rot"]) + "\n")
            f.write("\n")
    return (1 if res["kern-rot"] else 0), res, lines


def done(base, summary=None):
    """All shard notes of a run -> ({kind: sorted suites}, the one annotation line)."""
    res = {"wackler": set(), "rand-rot": set(), "kern-rot": set()}
    for d, _, files in os.walk(base):
        if "timings-vermerk.txt" in files:
            with open(os.path.join(d, "timings-vermerk.txt"), encoding="utf-8") as f:
                for ln in f:
                    p = ln.split()
                    if len(p) == 2 and p[0] in res:
                        res[p[0]].add(p[1])
    res = {k: sorted(v) for k, v in res.items()}
    line = ("::notice title=kalmido-vermerk::wackler=" + " ".join(res["wackler"]) + "; rand-rot=" + " ".join(res["rand-rot"])
            + "; kern-rot=" + " ".join(res["kern-rot"]))
    if summary and any(res.values()):
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Rerun notes of all shards (tests/tiers.py)\n\n")
            f.write(f"- flaky (red first, green in the rerun): {', '.join(res['wackler']) or 'none'}\n")
            f.write(f"- edge suites red (release goes on, bug task): {', '.join(res['rand-rot']) or 'none'}\n")
            f.write(f"- core suites red: {', '.join(res['kern-rot']) or 'none'}\n\n")
    return res, line


def check():
    """(problems, missing suites, suites no longer in run_all.sh)."""
    bad, seen = [], set()
    try:
        with open(TIERS, encoding="utf-8") as f:
            for i, ln in enumerate(f, 1):
                p = ln.split("#", 1)[0].split()
                if not p:
                    continue
                if len(p) < 2 or p[1] not in TIER_NAMES:
                    bad.append(f"tiers.txt:{i}: '{ln.strip()}' - expected '<suite> kern|rand <why>'")
                elif p[0] in seen:
                    bad.append(f"tiers.txt:{i}: {p[0]} twice")
                seen.add(p[0])
    except OSError as e:
        bad.append(f"tiers.txt: {e}")
    names = [s for s, _, _ in suggest_rows()]
    return bad, [s for s in names if s not in seen], sorted(seen - set(names))


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    cmd, a = argv[0], argv[1:]
    if cmd == "ci":
        o = {"--first": "", "--rerun-log": "", "--rerun-rc": "1", "--out": ""}
        i = 0
        while i < len(a):
            if a[i] not in o or i + 1 >= len(a):
                print(f"tiers.py ci: unknown / incomplete option {a[i]}")
                return 2
            o[a[i]] = a[i + 1]
            i += 2
        try:
            with open(o["--rerun-log"], encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            text = ""
        rc, _, lines = ci(o["--first"].split(), text, int(o["--rerun-rc"]), o["--out"] or None,
                          os.environ.get("GITHUB_STEP_SUMMARY"))
        print("\n".join(lines))
        return rc
    if cmd == "done":
        if len(a) != 1:
            print("usage: tiers.py done DIR")
            return 2
        _, line = done(a[0], os.environ.get("GITHUB_STEP_SUMMARY"))
        print(line)
        return 0
    if cmd == "split":
        js = "--json" in a
        r = split([x for x in a if x != "--json"])
        print(json.dumps(r) if js else f"kern: {' '.join(r['kern'])}\nrand: {' '.join(r['rand'])}")
        return 0
    if cmd == "suggest":
        have = load()
        for s, t, why in suggest_rows():
            if "--all" in a or s not in have:
                print(f"{s} {t}  # {why}")
        return 0
    if cmd == "check":
        bad, missing, gone = check()
        for b in bad:
            print("FAIL: " + b)
        if missing:
            print(f"note: {len(missing)} suites not in tests/tiers.txt (count as kern; propose a tier: tests/tiers.py suggest): "
                  + " ".join(missing[:20]) + (" ..." if len(missing) > 20 else ""))
        if gone:
            print(f"note: {len(gone)} suites in tests/tiers.txt are no longer in run_all.sh: " + " ".join(gone[:20]))
        print(f"tiers.txt: {len(load())} suites, {sum(1 for t in load().values() if t == 'rand')} rand" + (" - FAILED" if bad else " - ok"))
        return 1 if bad else 0
    print(f"tiers.py: unknown command {cmd} (ci | done | split | suggest | check)")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
