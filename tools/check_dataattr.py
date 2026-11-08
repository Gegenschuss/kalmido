#!/usr/bin/env python3
"""2.525.0 (#4281): one data attribute, one meaning - or a guard. All client files share one `document`: a click listener on
document (or window) that starts with `closest('[data-x]')` also gets the clicks on every other file's data-x. Twice that
was a bug (#4058; #4281: data-rx of the reaction picker sent POST /api/docs/NaN/extracted, data-cc of the choice cards
reached the credit card sheet, data-cb of the address books opened the cash book's "Close day").

    python3 tools/check_dataattr.py [-v]          exit 1 on a finding

For every such listener whose attribute another file emits too, the attribute has to stand in KNOWN below:
 - "shared": the other files emit it on purpose for this handler (the same meaning); the emitting files are listed, so a
   new file that emits it is a finding until somebody looked at it;
 - "guarded": it means something else elsewhere; each listener of it checks the value or its area and says so in its first
   lines (or the comment right above) with `one-meaning guard: data-x` (next to the check).
Standard library only (the CI lint job runs plain Python).
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "static", "js")
LISTEN = re.compile(r"(?:document|window)\.addEventListener\(\s*'click'")
FIRST = re.compile(r"closest\??\.?\(\s*'\[data-([a-z][a-z0-9-]*)\]'\s*\)")
GUARD_LINES = 12  # the marker stands in the listener's first lines (or in the comment lines right above it)
BEFORE = 4

# attribute -> (kind, files that may emit it besides the listener's own file); checked 04.11.2026 (#4281)
KNOWN = {
    "ab": ("shared", {"abdocs.js", "filetext.js", "tagsel.js"}),
    "abo": ("shared", {"office_cashflow.js"}),
    "absel": ("shared", {"tagsel.js"}),
    "bk": ("guarded", {"account.js"}),
    "bka": ("guarded", {"office_bankacc.js", "office_bookarch.js"}),
    "bnk": ("shared", {"office_bankrules.js"}),
    "cb": ("guarded", {"contacts.js"}),
    "cc": ("guarded", {"choicecard.js", "office_cards.js"}),
    "dl": ("guarded", {"family.js", "office_docs.js"}),
    "dpfor": ("shared", {"agentrotate.js"}),
    "dv": ("guarded", {"office_datev.js"}),
    "evopen": ("shared", {"contacts.js"}),
    "fslv": ("shared", {"ablage.js"}),
    "hbmopen": ("shared", {"hubmail.js"}),
    "imr": ("shared", {"office.js"}),
    "lead": ("shared", {"office_import.js"}),
    "lt": ("guarded", {"agents.js", "office.js", "office_letters.js"}),
    "mm": ("guarded", {"popovers.js"}),
    "mwtask": ("shared", {"detail.js"}),
    "ofc": ("shared", {"officeagents.js"}),
    "oinv": ("shared", {"account.js"}),
    "pl": ("guarded", {"render.js", "office_periods.js", "paperless.js"}),
    "pov": ("shared", {"trashui.js"}),
    "pp": ("guarded", {"agents.js", "asstprop.js", "contractprop.js", "dupprop.js", "importprop.js", "lyprop.js",
                       "objprop.js", "office_leads.js", "playbook.js", "rules.js", "sheetprop.js"}),
    "rkf": ("shared", {"office_import.js"}),
    "rx": ("guarded", {"agents.js", "orgexport.js"}),
    "setgo": ("shared", {"office.js", "office_books.js", "office_cashbook.js", "office_import.js", "officeagents.js",
                         "settings.js"}),
    "sv": ("shared", {"favtiles.js"}),
    "wem": ("shared", {"wklive.js"}),
    "wk": ("shared", {"wklive.js"}),
}


def emitters(files):
    """attribute -> files that write data-<attribute>= (exactly that name, not data-<attribute>-more). 2.670.0 (#4576): an
    attribute selector ('[data-x="v"]', a file that only looks for the element, e.g. tourmods.js) writes nothing."""
    out = {}
    for n, t in files.items():
        for a in set(re.findall(r"(?<![a-z0-9\[-])data-([a-z][a-z0-9-]*)=", t)):
            out.setdefault(a, set()).add(n)
    return out


def listeners(files):
    """[(attribute, file, line, text of the first GUARD_LINES lines)] for the document-level click listeners."""
    out = []
    for n, t in files.items():
        lines = t.split("\n")
        for m in LISTEN.finditer(t):
            line = t.count("\n", 0, m.start()) + 1
            body = [lines[line - 1][m.start() - t.rfind("\n", 0, m.start()) - 1:]]
            for x in lines[line:line + 40]:  # the listener's own lines: indented, up to its closing "});"
                if x[:1] not in (" ", "\t", "}", ")"):
                    break
                body.append(x)
                if x.startswith("}"):
                    break
            f = FIRST.search("\n".join(body)[:600])
            if f:
                head = lines[max(0, line - 1 - BEFORE):line - 1] + body[:GUARD_LINES]
                out.append((f.group(1), n, line, "\n".join(head)))
    return out


def check(files):
    em, out = emitters(files), []
    for a, n, line, head in listeners(files):
        others = em.get(a, set()) - {n}
        if not others:
            continue
        kind, ok = KNOWN.get(a, (None, set()))
        if kind is None:
            out.append(f"static/js/{n}:{line}: data-{a} is emitted by {', '.join(sorted(others))} too - same meaning? "
                       f"add it to KNOWN in tools/check_dataattr.py (shared), or check the value / area in the listener "
                       f"and mark it `one-meaning guard: data-{a}` (guarded)")
            continue
        new = others - ok
        if new:
            out.append(f"static/js/{n}:{line}: data-{a} is now emitted by {', '.join(sorted(new))} as well: check that it "
                       f"means the same for this listener, then add the file to KNOWN in tools/check_dataattr.py")
        if kind == "guarded" and f"one-meaning guard: data-{a}" not in head:
            out.append(f"static/js/{n}:{line}: data-{a} means something else in another file: the listener checks the "
                       f"value or its area and says so with `one-meaning guard: data-{a}` in its first {GUARD_LINES} lines")
    return out


def main(argv):
    files = {os.path.basename(f): open(f, encoding="utf-8").read() for f in sorted(glob.glob(os.path.join(JS, "*.js")))}
    out = check(files)
    for x in out:
        print(x)
    if "-v" in argv:
        print(f"check_dataattr: {len(listeners(files))} document click listeners, {len(out)} finding(s)")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
