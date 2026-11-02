#!/usr/bin/env python3
# kalmido-suite: after=freelancer_coverage nodata
"""2.491.0 (#4020): the client page's block of the documents made from templates follows the name of its area
"Letters & contracts" (Schreiben & Verträge, 2.489 #2646): heading, empty text and button no longer say "Documents" /
"No documents yet." / "New document", the block name in the view builder and the area entry neither; every language has
the new texts. Static (no server)."""
import json
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import check, done  # noqa: E402

R = os.path.join(N, "..")


src = open(os.path.join(R, "static", "js", "clientpage.js"), encoding="utf-8").read()
m = re.search(r"function ms_clGdHtml\(c\) \{(.*?)\n\}", src, re.S)
check(m, "ms_clGdHtml found")
body = m.group(1) if m else ""
check("tr('Letters & contracts')" in body, "#4020: heading says Letters & contracts")
check("tr('No letters or contracts yet.')" in body, "#4020: empty text says no letters or contracts")
check("tr('New letter or contract')" in body, "#4020: button says New letter or contract")
check("tr('Documents')" not in body and "No documents yet." not in body and "tr('New document')" not in body,
      "#4020: no 'Documents' / 'No documents yet.' / 'New document' left in the client page's block")
dash = open(os.path.join(R, "static", "js", "dashboard.js"), encoding="utf-8").read()
check("['gendocs', N_('Letters & contracts')" in dash, "#4020: block name in the view builder")
areas = open(os.path.join(R, "static", "js", "areas.js"), encoding="utf-8").read()
check(re.search(r"key: 'gendocs'[^}]*N_\('Letters & contracts'\)", areas), "#4020: area entry")
for lang in ("de", "es", "fr", "it", "nl"):
    d = json.load(open(os.path.join(R, "static", "i18n", lang + ".json"), encoding="utf-8"))
    check(d.get("No letters or contracts yet.") and d.get("New letter or contract"), f"#4020: {lang} has the new texts")
de = json.load(open(os.path.join(R, "static", "i18n", "de.json"), encoding="utf-8"))
check(de.get("No letters or contracts yet.") == "Noch keine Schreiben oder Verträge.", "#4020: German empty text")
check(de.get("New letter or contract") == "Neues Schreiben oder Vertrag", "#4020: German button")

sys.exit(done("p2491_a_texts"))
