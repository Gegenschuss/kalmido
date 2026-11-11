#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.695.0 (#4619) every row with a "…" button opens the same menu by a long press (phone) and a right click (computer).
Static like tests/export_coverage_test.py, no container. Reads static/js/*.js:
 1. every "…" button (an element whose content is ic('dots', ...)) either carries data-rowmenu="K" or is named in RM_LEFT
    below with the reason why it is no row (a page / head / bar menu, a sort mode where the long press drags, ...)
 2. K is a word of the row selector of a long-press binding: ms_rowMenu / ms_longPress / cm_bind / lm_btnMenu (multisel.js)
    with a string or a const holding one; a binding that finds the button by a selector (lm_btn / lm_open / lm_btnMenu /
    querySelector) names the button's own data attribute in the same statement - so test and code mean the same place
 3. RM_LEFT is exact and not stale: each entry counts the unmarked buttons of that file with that attribute
 4. the binding helpers exist (multisel.js) and every reason is a text
A new "…" in a row without a long press makes this suite red: mark it data-rowmenu="<row class>" and bind the row
(lm_btnMenu(rowSel, btnSel) is the short way), or add it to RM_LEFT with the reason.
The UI side (the real long press opens the menu, the click after it opens nothing, a swipe cancels): tests/p2695_a_longpress_ui.js
usage: python3 tests/p2695_a_rowmenu_coverage_test.py"""
import glob
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(N, "..", "static", "js")
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402

# (file, the button's first data attribute, else its class) -> (how many unmarked buttons, why no row long press)
RM_LEFT = {
    # 2.768.0 (#4888): + the bar above a folder with recognition (ab_foldTools, 2.752.0 #4887) - the count was stale since then
    ("ablage.js", 'data-ab="menu"'): (2, "the open folder's menu in the tool bar above the list and above a folder with recognition (page menus)"),
    ("bookmarks.js", "summary"): (1, "the page menu of the bookmarks (import / export)"),
    ("budget.js", "summary"): (1, "the page menu of a budget"),
    ("feeds.js", "summary"): (1, "the page menu of the feeds (OPML import / export)"),
    ("calabs.js", 'class="iconbtn abchid"'): (1, "an invisible stand-in (aria-hidden) that keeps the columns of the rows in line, no button"),
    ("calendar.js", 'data-act="section-menu"'): (1, "a kanban column head: its long press drags the column, held still it opens the head menu (dnd.js secHold, secdrag.js)"),
    ("calendar.js", 'data-act="cvx-today-menu"'): (1, "the head menu of the calendars on Today"),
    ("calendar.js", 'data-act="cal-more"'): (1, "the head menu of the calendar bar on a phone / tablet (2.855.0, #5462): a bar, not a row"),
    # 2.828.0 (#5464, job/3852): the Calendars window folds "Per project" out with a "…" like the rows beside it
    ("calevents.js", 'data-evc="lists"'): (1, "the fold-out \"Per project\" of the tasks in the Calendars window (aria-expanded), no row menu"),
    ("chat.js", 'data-act="tc-more"'): (1, "the head of a team room (phone only)"),
    ("chat.js", 'data-act="nt-menu"'): (1, "the head of the open note (the note cards have their long press, notesall.js)"),
    ("notesall.js", 'data-act="nt-menu"'): (1, "the head of the quick note (the note cards have their long press)"),
    ("chatwins.js", 'data-cwact="menu"'): (1, "the head of a chat window"),
    ("collab.js", 'data-act="tl-menu"'): (1, "the head of the comments (order, history)"),
    ("contacts.js", 'data-ct="menu"'): (1, "the tool bar of the contacts (import, export)"),
    ("contacts.js", 'data-ct="cmenu"'): (1, "the head of an open contact (the rows: cm_bind #view .ctrow)"),
    ("clientpage.js", 'data-mscl="cmenu"'): (1, "the head of an open client (the rows: cm_bind .msclients .ctrow)"),
    ("detail.js", 'data-act="task-menu"'): (1, "the head of the task's details (the task rows: dnd.js long press selects, its bar has the menu)"),
    ("hubmail.js", 'data-hbma="menu"'): (1, "the head of an open mailbox (its address); the address rows are marked"),
    ("jobchat.js", 'data-act="chat-head-menu"'): (1, "the head of the agent chat"),
    ("mindmap.js", 'data-mm="more"'): (1, "the tool bar of the mind map"),
    # 2.892.0 (#5453, job/3927): the foot of a receipt sheet and the tool bar of the receipts page get "More" on a phone
    ("office_books.js", 'data-m="more"'): (1, "the foot of a receipt sheet on a phone (Open document / Bill on), no row"),
    ("office_docs.js", 'data-ofd="more"'): (1, "the bar of an open office document"),
    ("office_receipts.js", 'data-rcl="menu"'): (1, "the tool bar of the receipts page on a phone (kinds, CSV, ZIP, Select), no row"),
    ("office_doctpl.js", 'data-dt="more"'): (1, "the bar of an open document from a template"),
    ("office_letters.js", 'data-lt="more"'): (1, "the bar of an open letter"),
    ("polls.js", 'data-tpo="menu"'): (1, "the head of the poll dialog"),
    ("render.js", 'class="tico"'): (1, "the icon of More in the phone's tab bar (data-act=\"tabs-more\"), no row"),
    ("render.js", 'data-act="top-more"'): (1, "the top bar of a view"),
    ("render.js", 'data-lsort="${l.id}"'): (2, "sort mode of the projects (page and sidebar): the long press on the grip drags the row, the \"…\" is the keyboard way (WCAG 2.5.7)"),
    ("render.js", 'data-fsort="${esc(f)}"'): (1, "sort mode of a sidebar folder: the long press drags, the \"…\" is the keyboard way"),
    ("render.js", 'data-act="folder-menu"'): (1, "a folder of the sidebar: its long press is the tree's hold (areas.js drg_attach, onTap sbb_tmenu) - drag.js, not multisel.js"),
    ("sheetfold.js", 'data-shf="fmenu"'): (1, "the head of an open table folder; its cards are marked"),
    ("sheetpivot.js", 'data-spv="menu"'): (1, "the bar of a pivot table"),
    ("sheets.js", 'data-shv="omenu"'): (1, "the tool bar of the tables overview"),
    ("sheets.js", 'data-shv="menu"'): (1, "the bar of an open table"),
    ("sprints.js", 'data-spr="more"'): (2, "the sprint bar above the board"),
    ("videorev.js", 'data-vdr="menu"'): (1, "the head of the video review dialog"),
    ("widgets.js", 'data-act="wg-more"'): (1, "a start page tile in edit mode: its long press drags the tile (dashboard.js)"),
    ("wiki.js", 'data-wk="amenu"'): (1, "the tool bar of the knowledge base (a workspace menu)"),
    ("wiki.js", 'data-wk="pmenu"'): (1, "the head of an open page"),
}
BINDERS = ("ms_rowMenu", "ms_longPress", "cm_bind", "lm_btnMenu")
DOTS = re.compile(r"""ic\(\s*['"]dots['"]""")
TAG = re.compile(r"<(button|summary|a|span)\b")


def tag_end(s, i):
    """The end of the opening tag that starts at i (skips ${...} with nested braces and quoted strings in it)."""
    depth, j = 0, i
    while j < len(s):
        if s.startswith("${", j):
            depth += 1
            j += 2
            continue
        c = s[j]
        if depth and c == "{":
            depth += 1
        elif depth and c == "}":
            depth -= 1
        elif not depth and c == ">":
            return j
        j += 1
    return -1


def the_tag(s, pos):
    """The opening tag (button / summary / a / span) whose content holds the ic('dots') at pos, or None."""
    for m in reversed(list(TAG.finditer(s, max(0, pos - 1500), pos))):
        e = tag_end(s, m.start())
        if 0 <= e < pos and not re.search(r"</(button|summary|a|span)>", s[e:pos]):
            return m.group(1), s[m.start():e + 1]
    return None


def key_of(name, tag):
    a = [x for x in re.findall(r'\sdata-[\w-]+(?:="[^"]*")?', tag) if not x.strip().startswith("data-rowmenu")]
    if a:
        return a[0].strip()
    c = re.search(r'\sclass="[^"]*"', tag)
    return c.group(0).strip() if name == "span" and c else name


def word(text, w):
    return re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", text) is not None


files = {os.path.basename(p): open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(JS, "*.js")))}
ms = files.get("multisel.js", "")
for fn in BINDERS:
    check(re.search(rf"function {fn}\(", ms), f"multisel.js: {fn} is defined")
check("lm_btn" in ms and "lm_selKeep" in ms, "multisel.js: lm_btn / lm_selKeep are defined")

# the bindings: (file, row selector, the rest of the statement's line)
consts = {}
for f, s in files.items():
    for m in re.finditer(r"""\bconst ([A-Za-z_$][\w$]*) = (['"])([^'"]*)\2""", s):
        consts.setdefault(m.group(1), m.group(3))
binds = []
for f, s in files.items():
    for m in re.finditer(r"(?<![\w.])(" + "|".join(BINDERS) + r")\(\s*(?:'([^']*)'|\"([^\"]*)\"|([A-Za-z_$][\w$]*))", s):
        if s[max(0, m.start() - 9):m.start()] == "function ":
            continue
        if "//" in s[s.rfind("\n", 0, m.start()) + 1:m.start()]:  # a binding in a comment binds nothing
            continue
        sel = m.group(2) or m.group(3) or consts.get(m.group(4) or "", "")
        if not sel:
            continue
        line = s[m.start():s.find("\n", m.start())]
        binds.append((f, sel, line))
check(len(binds) >= 30, f"the long-press bindings are found ({len(binds)})")
# a start script that runs before multisel.js (index.html order) binds only once the page is ready (domReady), else the
# binding is skipped (typeof ... === 'function' is false then) or throws
html = open(os.path.join(JS, "..", "index.html"), encoding="utf-8").read()
order = re.findall(r'<script src="/static/js/([\w.-]+\.js)"', html)
before = set(order[:order.index("multisel.js")]) if "multisel.js" in order else set()
check(before, "index.html loads multisel.js after other start scripts (the order is read)")
for f, sel, line in binds:
    if f in before:
        check("domReady(" in files[f][files[f].rfind("\n", 0, files[f].find(line)) + 1:files[f].find(line)], f"{f}: binds {sel!r} before multisel.js is loaded (index.html order): wrap it in domReady(() => ...)")

marked, left, seen = 0, {}, 0
for f, s in files.items():
    for m in DOTS.finditer(s):
        seen += 1
        ln = s.count("\n", 0, m.start()) + 1
        t = the_tag(s, m.start())
        if not check(t, f"{f}:{ln}: the element of a \"…\" (ic('dots')) is found (button / summary / a / span)"):
            continue
        name, tag = t
        k = key_of(name, tag)
        rm = re.search(r'\sdata-rowmenu="([^"]*)"', tag)
        if not rm:
            left[(f, k)] = left.get((f, k), 0) + 1
            if (f, k) not in RM_LEFT:
                check(False, f"{f}:{ln}: a \"…\" ({k}) without data-rowmenu and not in RM_LEFT: a row's \"…\" gets data-rowmenu=\"<row class>\" and a long press (multisel.js lm_btnMenu), anything else a line in RM_LEFT with the reason")
            continue
        marked += 1
        key = rm.group(1)
        hit = [b for b in binds if word(b[1], key)]
        if not check(hit, f"{f}:{ln}: data-rowmenu=\"{key}\": no ms_rowMenu / ms_longPress / cm_bind / lm_btnMenu binds a row selector with \"{key}\""):
            continue
        # a binding that looks the button up by a selector names its attribute (the one the button carries)
        attr = k.split("=")[0] if "${" in k else k  # data-rp="menu" (a value with ${...}: the name only)
        by_sel = [b for b in hit if re.search(r"lm_btn\(|lm_open\(|lm_btnMenu\(|querySelector\(", b[2])]
        check(not by_sel or any(attr in b[2] for b in by_sel) or any(re.search(r"lm_btn\(|lm_open\(|lm_btnMenu\(|querySelector\(", b[2]) is None for b in hit),
              f"{f}:{ln}: the binding of \"{key}\" looks for a button, but not for this one ({k}): {[b[0] + ' ' + b[2][:120] for b in by_sel]}")

for (f, k), (n, why) in sorted(RM_LEFT.items()):
    check(why.strip(), f"RM_LEFT {f} {k}: the reason is missing")
    check(left.get((f, k), 0) == n, f"RM_LEFT {f} {k}: says {n} unmarked \"…\", found {left.get((f, k), 0)} (stale or a new one: mark it or fix the count)")

check(seen >= 60, f"the \"…\" buttons of static/js are found ({seen})")
check(marked >= 20, f"rows with a \"…\" are marked data-rowmenu ({marked})")
# data-rowmenu only on a "…" (no stray marker that the scan above would not see)
for f, s in files.items():
    for m in re.finditer(r'<(?:button|a)\b[^<]*?\sdata-rowmenu="', s):
        e = tag_end(s, m.start())
        d = DOTS.search(s, e) if e > 0 else None
        check(d and not re.search(r"</(button|a)>", s[e:d.start()]), f"{f}:{s.count(chr(10), 0, m.start()) + 1}: data-rowmenu on an element without ic('dots') in it")

print(f"p2695_a_rowmenu_coverage: {OKS[0]} ok, {len(FAILS)} failed ({seen} \"…\", {marked} rows, {sum(left.values())} left out)")
sys.exit(1 if FAILS else 0)
