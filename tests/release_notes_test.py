#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.538.0 (#4360): tools/release_notes.py makes a public release text from a CHANGELOG section like the one of 2.502.0:
bundle titles ("Bündel: ...", "Sammelpaket: ...") and lines about main / CI are gone, the top shows three to five real
highlights, the whole text stays below MAX_CHARS, the link to the CHANGELOG is at the end. Without a server (CI Lint)."""
import importlib.util
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402

spec = importlib.util.spec_from_file_location("release_notes", os.path.join(N, "..", "tools", "release_notes.py"))
rn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rn)

parts = []
for i in range(30):
    parts.append(f"Package 2.{500 + i} (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).\n### Added\n"
                 f"- Feature number {i} does something people can see (#{4000 + i}).\n### Fixed\n"
                 + "".join(f"- Fix {i}.{j}: a long description of a repaired thing, " + "word " * 30 + f"(#{5000 + j}).\n" for j in range(30))
                 + "- Tests: p1_ui waits for the page (#1).\n"
                 + f"- Main red after CI 2.{i}.0 (#3506).\n- main red: p2391_b was already fixed on main (#4493).\n"
                 + f"- CI of 2.{i}.0: a flake in p5_ui fixed (#77).\n\n")
parts.append("Package 2.540 (Real title for people).\n### Changed\n- The invoice list sorts by date (#9).\n")
text = "".join(parts)
check(len(text) > 100000, f"test input is very long ({len(text)})")
out = rn.render(text)

check(len(out) <= rn.MAX_CHARS, f"text below the limit {len(out)} <= {rn.MAX_CHARS}")
check(rn.MAX_CHARS < 125000, "the limit is far below GitHub's 125000")
check("Bündel" not in out and "Sammelpaket" not in out, "no bundle titles")
check("Main red" not in out and "main red" not in out.lower(), "no lines about main red")
check("Package 2." not in out, "no package numbers")
check("#4000" not in out.replace("`#", ""), "no bare task links")
hl = out.split("**Highlights**", 1)[1].split("\n\n")[1].strip().splitlines() if "**Highlights**" in out else []
check(3 <= len(hl) <= 5 and all(x.startswith("- ") for x in hl), f"three to five highlights on top {hl}")
check("Feature number 0" in hl[0] if hl else False, "highlights are the first real Added entries")
check(not any("Tests:" in x for x in hl), "no test lines as highlights")
check(out.index("**Highlights**") < out.index("<details>"), "highlights before the folded rest")
check(out.rstrip().endswith("CHANGELOG.md](" + rn.CHANGELOG_URL + ")"), "link to the CHANGELOG at the end")
check("too long for this page" in out, "a cut text says so")
check("Test and CI fixes" in out and "a flake in p5_ui fixed" in out, "CI lines stay in the folded block")

small = rn.render("Package 2.540 (Real title for people).\n### Added\n- One thing (#9).\n### Fixed\n- Main red after CI 2.1.0 (#3506).\n")
check("Real title for people" in small and "One thing" in small and "Main red" not in small and "too long" not in small,
      "a short text keeps real titles, drops the main line, is not cut")

print("release_notes: %d ok, %d failed" % (OKS[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
