#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.623.0 E (#4621) the finger-drag guard: everything the mouse can drag, the finger can drag too. Static (no container):
every place in static/js that the browser's mouse drag starts from -- a draggable="true" / draggable="${...}" in markup,
setAttribute('draggable', 'true'), .draggable = true, addEventListener('dragstart', ...) -- is named in TD_SITES with its way
for a finger:
  ('drag.js', file)   the shared core static/js/drag.js carries the finger there (drg_attach / rowd_attach / drg_begin in file)
  ('eigen', file, N)  an own touch path in file (touchstart) that works today; it moves onto drag.js with task #N
  ('ohne', N)         no finger way yet; task #N builds it on drg_attach
  ('kein', why)       not a drag of the app (a guard against the browser's drag, a bookmarklet for the browser's bar) or
                      the finger has another way named in why
A new place without an entry turns this test red: give it a finger way through drag.js (or an entry with its reason).
 1. every place is matched by exactly one entry (file + a marker on the place's line or the line after it)
 2. no entry is stale (it matches a place)
 3. a 'drag.js' / 'eigen' entry's file really has that way; 'ohne' / 'eigen' name a task, 'kein' a reason
 4. the scanner itself: a probe without an entry is found (the check above would turn red)
usage: python3 tests/p2623_e_touchdrag_coverage_test.py"""
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(N, "..", "static", "js")
sys.path.insert(0, N)
from kt import check, done  # noqa: E402

# the places a mouse drag starts from; a selector [draggable="true"] inside closest() is the handler's, not a place
SITE = re.compile(r"""(?<!\[)draggable="(?:true|\$\{)|setAttribute\(\s*['"]draggable['"]\s*,\s*['"]true['"]\s*\)"""
                  r"""|\.draggable\s*=\s*true\b|addEventListener\(\s*['"]dragstart['"]""")
FINGER = re.compile(r"\b(?:drg_attach|rowd_attach|drg_begin)\(")
SKIP = {"drag.js"}  # the core itself

# (file, marker) -> way. The marker is a piece of the place's line (or the next line, for a listener on its own line).
TD_SITES = {
    # ---- through drag.js
    ("dnd.js", ".trow[draggable"): ("drag.js", "dnd.js"),            # task rows + calendar chips: tdStart (hold 380)
    ("dnd.js", "shandle"): ("drag.js", "secdrag.js"),               # sections: the header's long press, drg_begin
    ("dnd.js", "[data-sdrag]"): ("drag.js", "secdrag.js"),
    ("render.js", "!opts.trash && !ro && !isMobile()"): ("drag.js", "dnd.js"),  # the task row
    ("dragmulti.js", "dgEnd();"): ("drag.js", "dnd.js"),  # several selected tasks: the grip in select mode
    ("calview.js", 'draggable="${t.status'): ("drag.js", "caldrag.js"),  # calendar chips (month, week, list)
    ("dashboard.js", "nat ?"): ("drag.js", "dashboard.js"),        # the start page's layout editor: rowd_attach on touch
    ("dashboard.js", ".lyed .dcust"): ("drag.js", "dashboard.js"),
    ("basket.js", "kbgrip"): ("drag.js", "basket.js"),              # 2.623.0 E (#4621): the group's header, held
    ("sheetbook.js", 'data-shb="tab"'): ("drag.js", "sheetbook.js"),  # 2.623.0 E (#4621): the sheet tabs, held
    # ---- an own touch path today, onto drag.js with #4966
    ("render.js", 'reorder" data-list'): ("eigen", "sidebar.js", 4966),        # list rows of the sidebar / start page: sdStart
    ("render.js", "sideOD("): ("eigen", "sidebar.js", 4966),
    ("sidebar.js", "#side .srow[data-list]"): ("eigen", "sidebar.js", 4966),
    ("areas.js", "n.drag && !isTouch()"): ("eigen", "areas.js", 4966),  # the areas' tree nodes: SBB_TD
    ("areas.js", "#side .sbbt"): ("eigen", "areas.js", 4966),
    ("favtiles.js", "const drag = isMobile()"): ("eigen", "favtiles.js", 4966),  # favourite tiles: FV2.lp (see #4618)
    ("favtiles.js", ".fv2bar"): ("eigen", "favtiles.js", 4966),
    # ---- no finger way yet
    ("ablage.js", 'class="abrow"'): ("ohne", 4961),                 # a file onto a folder
    ("ablage.js", ".abrow[draggable"): ("ohne", 4961),
    ("areas.js", "sbb_on() && !S.me?.kid"): ("ohne", 4962),         # the icons of the area rail
    ("areas.js", "#srail .srb"): ("ohne", 4962),
    ("office_banknorc.js", "bnrdrag"): ("ohne", 4963),              # a receipt onto a booking
    ("office_banknorc.js", "closest?.('[data-bnr-rc]')"): ("ohne", 4963),
    ("office_docs.js", 'class="ofdli"'): ("ohne", 4964),            # a document onto a folder of the pane
    ("office_tree.js", ".ofdli[draggable"): ("ohne", 4964),
    ("office_pipeline.js", "ppcard"): ("ohne", 4965),               # a pipeline card into another stage
    # ---- not a drag of the app, or another finger way
    ("events.js", "bm-hint"): ("kein", "the bookmarklet goes into the browser's bookmark bar, not into the app"),
    ("integrations.js", "bmhint"): ("kein", "the bookmarklet goes into the browser's bookmark bar, not into the app"),
    ("listedit.js", "DS.on"): ("kein", "a guard: the drag selection pauses while the browser drags"),
    ("sheetgrid.js", "SG.drag"): ("kein", "a guard: holds back the browser's drag over the grid's own cell drag"),
    ("refs.js", "RF_TA_SEL"): ("kein", "a reference dropped into a text box; the finger has the button Insert reference (refs.js)"),
    ("refs.js", "rf_srcKey"): ("kein", "a reference dropped into a text box; the finger has the button Insert reference (refs.js)"),
}


def sites(name, src):
    """-> [(line, context)] of the mouse-drag places in src (context = the place's line and the next one)"""
    lines = src.split("\n")
    out = []
    for m in SITE.finditer(src):
        ln = src.count("\n", 0, m.start())
        out.append((ln + 1, "\n".join(lines[ln:ln + 2])))
    return out


def unmatched(name, src, table):
    """-> ([(line, text)] of places no entry of table names, {(file, marker): hits}); a place two entries name counts as unmatched"""
    hits, left = {}, []
    for ln, ctx in sites(name, src):
        ks = [k for k in table if k[0] == name and k[1] in ctx]
        # a marker on the place's own line wins over one on the next line (two places on neighbouring lines)
        own = [k for k in ks if k[1] in ctx.split("\n")[0]]
        ks = own or ks
        if len(ks) != 1:
            left.append((ln, ctx.split("\n")[0].strip()[:120] + (f"  [{len(ks)} entries]" if ks else "")))
            continue
        hits[ks[0]] = hits.get(ks[0], 0) + 1
    return left, hits


files = sorted(f for f in os.listdir(JS) if f.endswith(".js") and f not in SKIP)
SRC = {f: open(os.path.join(JS, f), encoding="utf-8").read() for f in files}
all_hits, n = {}, 0
for f in files:
    left, hits = unmatched(f, SRC[f], TD_SITES)
    n += len(sites(f, SRC[f]))
    for ln, txt in left:
        check(False, f"static/js/{f}:{ln} a mouse drag without a finger way: give it one through drag.js (drg_attach) or an entry in TD_SITES: {txt}")
    for k, v in hits.items():
        all_hits[k] = all_hits.get(k, 0) + v
check(n > 20, f"the scanner finds the places ({n})")

# 2. nothing stale
for k in TD_SITES:
    check(k in all_hits, f"TD_SITES {k}: matches a place (else drop the entry)")

# 3. the ways are real
for (f, mk), way in TD_SITES.items():
    kind = way[0]
    if kind == "drag.js":
        check(way[1] in SRC and FINGER.search(SRC[way[1]]) is not None, f"{f} {mk!r}: {way[1]} attaches drag.js (drg_attach / rowd_attach / drg_begin)")
    elif kind == "eigen":
        check(way[1] in SRC and "'touchstart'" in SRC[way[1]], f"{f} {mk!r}: {way[1]} has its own touch path")
        check(isinstance(way[2], int) and way[2] > 0, f"{f} {mk!r}: the task that moves it onto drag.js")
    elif kind == "ohne":
        check(isinstance(way[1], int) and way[1] > 0, f"{f} {mk!r}: the task that builds the finger way")
    elif kind == "kein":
        check(isinstance(way[1], str) and len(way[1].strip()) > 10, f"{f} {mk!r}: the reason")
    else:
        check(False, f"{f} {mk!r}: unknown way {kind!r}")

# 2.623.0 E (#4621): the touch ways of this part: the tabs / groups keep the mouse's drag and get the finger from drag.js
check("drg_attach(document, {" in SRC["sheetbook.js"] and "mouse: false" in SRC["sheetbook.js"], "sheetbook.js: the finger by drg_attach, the mouse keeps the browser's drag")
check("!rowd_touch() ? 'draggable=\"true\"'" in SRC["sheetbook.js"], "sheetbook.js: no browser drag on a touch screen (the hold is the app's)")
check("drg_attach(document, {" in SRC["basket.js"] and "kbGroupMove(d.id" in SRC["basket.js"], "basket.js: the finger moves a group by drg_attach, the same kbGroupMove")

# 4. the scanner: a probe place without an entry is found, one with an entry is not, a selector is no place
probe = "const x = `<li class=\"zz\" draggable=\"true\">`;\ndocument.addEventListener('dragstart', e => {\n  e.target.closest?.('.zz[draggable=\"true\"]');\n});\n"
left, _ = unmatched("probe.js", probe, TD_SITES)
check(len(left) == 2, f"a probe file with two places and no entry: both found ({len(left)})")
left, hits = unmatched("probe.js", probe, {("probe.js", 'class="zz"'): ("ohne", 1), ("probe.js", ".zz[draggable"): ("ohne", 1)})
check(not left and len(hits) == 2, f"the same probe with its entries: nothing left ({left})")
check(len(sites("p.js", "x.closest('[draggable=\"true\"]'); img.draggable = false;")) == 0, "a selector and draggable = false are no places")
check(len(sites("p.js", "el.setAttribute('draggable', 'true'); el.draggable = true;")) == 2, "setAttribute and the property are places")

sys.exit(done("p2623_e_touchdrag_coverage"))
