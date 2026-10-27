#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.356.0 B (#2934): every importer names its target workspace before it starts (#1940: importTargetConfirm, "Import into
the organisation X?" / "Import into your private space?"). A static check of the web client, no server.
 - KNOWN: the import calls that store something; in its top-level block (function / handler) importTargetConfirm comes first
   (bank statement, DATEV, leads, newsletter consents - the four of #2934 - and the importers that already had it)
 - discovery: every POST / PUT to an /import route in static/js sits in a block that asks importTargetConfirm, or is a step
   that stores nothing (preview, check, parse, key) or is listed in EXEMPT with the place that asks instead. A new importer
   without the question fails here.
usage: p2356_b_import_target_test.py"""
import os
import re
import sys

from kt import FAILS, OKS, check

JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "js")
CALL = re.compile(r"""\b(?:api|rawFetch)\(\s*'(?:POST|PUT)'\s*,\s*[`'"]([^`'"]*)""")
# a top-level block starts at column 0: a function, a const / let, a document / window handler
BOUND = re.compile(r"^(?:async\s+function\s+(\w+)|function\s+(\w+)|(?:const|let)\s+(\w+)\s*=|(document|window)\.)", re.M)
ASK = "importTargetConfirm"
# (file, a regex of the storing call): importTargetConfirm comes before it in the same block
KNOWN = [
    ("office_bank.js", r"api\('POST', '/api/office/bank/import',"),  # #2934: + the account
    ("office_datevimp.js", r"api\('POST', '/api/office/datev/import',"),  # #2934
    ("office_leads.js", r"api\('POST', '/api/office/leads/import', \{text, commit: true\}"),  # #2934
    ("newsletter.js", r"nwl_impCall\(true\)"),  # #2934: consents
    ("sheetsio.js", r"rawFetch\('POST', '/api/sheets/import',"),  # 2.356.0 B: tables, the same rule
    ("office_cashflow.js", r"api\('POST', '/api/office/fixed-costs/import',"),
    ("office_import.js", r"api\('POST', '/api/office/legacy/import',"),
    ("office_travel.js", r"api\('POST', '/api/office/trips/import',"),
    ("budget.js", r"let j = await commit\(rows\)"),  # bg_csvModal: the inner commit() posts .../import/commit
    ("paperless.js", r"\$\{base\}/import`"),
    ("move.js", r"/api/account/import/\$\{UMZ\.cur\.id\}/run"),
    ("settings.js", r"api\('POST', '/api/import/ticktick'"),
    ("feeds.js", r"api\('POST', '/api/feeds/opml',"),  # OPML
    ("calevents.js", r"importTargetConfirm\(\{what: tr\('the events'\)"),
    ("contacts.js", r"importTargetConfirm\(\{what: tr\('the contacts'\)"),
    ("wiki.js", r"wki_start\(sp, f\)"),
]
# (file, block): import calls that store nothing yet or are asked about elsewhere
EXEMPT = {
    ("move.js", "umzUpload"): "uploads the export file only; umzInit asks before .../run",
    ("newsletter.js", "nwl_impCall"): "the shared call of the preview (apply false) and the import (KNOWN: nwl_impCall(true))",
    ("office_leads.js", "leadRead"): "the preview (no commit)",
    ("wkimport.js", "wki_start"): "the upload in pieces; wiki.js asks before it calls wki_start (KNOWN)",
}
DRY = re.compile(r"preview|/check\b|/parse\b|/key\b")


def blocks(src):
    """[(start, name)] of the top-level blocks."""
    return [(m.start(), next(x for x in m.groups() if x)) for m in BOUND.finditer(src)]


def block_of(bl, pos, src):
    st, name = 0, "?"
    for s, n in bl:
        if s > pos:
            nxt = s
            break
        st, name = s, n
    else:
        nxt = len(src)
    return st, nxt, name


SRC = {fn: open(os.path.join(JS, fn), encoding="utf-8").read() for fn in sorted(os.listdir(JS)) if fn.endswith(".js")}
check(ASK in SRC.get("workspace.js", "") and "function importTargetConfirm(" in SRC["workspace.js"], "importTargetConfirm is in workspace.js")

# 1. the known importers: the question comes before the storing call, in the same block
for fn, rx in KNOWN:
    src = SRC.get(fn, "")
    m = re.search(rx, src)
    if not m:
        check(False, f"{fn}: the import call {rx!r} is not found (moved? update KNOWN)")
        continue
    st, _, name = block_of(blocks(src), m.start(), src)
    seg = src[st:m.end()]
    check(ASK in seg, f"#2934: {fn} {name}: importTargetConfirm before the import ({rx})")

# 2. discovery: every call to an /import route
found = 0
for fn, src in SRC.items():
    bl = blocks(src)
    for m in CALL.finditer(src):
        url = m.group(1)
        if "/import" not in url or re.search(r"/(undo|restore)\b", url):
            continue
        found += 1
        st, nx, name = block_of(bl, m.start(), src)
        line = src.count("\n", 0, m.start()) + 1
        if DRY.search(url):
            continue
        if (fn, name) in EXEMPT:
            continue
        check(ASK in src[st:nx], f"#2934: {fn}:{line} ({name}) imports into {url} without importTargetConfirm in its block "
                                 f"- ask where the data goes (workspace.js) or list it in EXEMPT with the reason")
check(found >= 15, f"the discovery sees the import calls ({found})")
for (fn, name), why in EXEMPT.items():
    check(any(n == name for _, n in blocks(SRC.get(fn, ""))), f"EXEMPT {fn} {name} still exists ({why})")

print(f"p2356_b_import_target: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
