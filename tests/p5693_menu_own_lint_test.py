#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.1024.0 (#5693) tools/check_menu_own.py: every menu goes through menu() of popovers.js, none built by hand.
 1. the web client as it is: no finding (the fold-outs of #5688-#5691 are gone), and check_layout.py runs the check
 2. each kind of hand-built menu is red, in the shape the old ones had: role="menu" markup (budget / bookmarks / feeds),
    a <details> fold-out at the dots, a button with aria-expanded + aria-haspopup (document view Actions), an icon button
    with aria-expanded showing only the plus (chat plus), openPop with a menu-list of its own (time tracking Export)
 3. what is no menu stays green: a [role="menuitem"] selector, a listbox chooser, the project filter with check boxes,
    a fold with aria-expanded and a chevron, a <details> section with text, menu() itself
 4. the exception: `menu-ok: <reason>` on the same line; without a reason it does not count
 5. popovers.js (the shared menu) is never a finding, even though it draws role="menu"
usage: python3 tests/p5693_menu_own_lint_test.py"""
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from kt import check, done  # noqa: E402
import check_menu_own  # noqa: E402

# 1. the repository
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_menu_own.py")], capture_output=True, text=True, timeout=300)
check(r.returncode == 0, "the web client: no menu built by hand: " + (r.stdout + r.stderr)[-800:])
check("check_menu_own.errors()" in open(os.path.join(ROOT, "tools", "check_layout.py"), encoding="utf-8").read(),
      "check_layout.py (CI lint, Mac lint) runs the check")


def kinds(src):
    return [k for _n, k in check_menu_own.scan("static/js/x.js", src)]


# 2. red (shapes of the fold-outs before #5688-#5691)
RED = {
    "role": """const m = `<details class="bgmenu"><summary class="iconbtn" aria-label="More">${ic('dots')}</summary><div class="bgmenul" role="menu">
  <button type="button" role="menuitem" data-bg="cats">${ic('tag', 's')}<span>${tr('Categories')}</span></button></div></details>`;""",
    "dots": """const m = `<details class="xmenu"><summary title="More">${ic('dots')}</summary><div><button data-x="a">A</button></div></details>`;""",
    "toggle": """return `<span class="dv-actw"><button type="button" class="btn sm" data-dc="actsmore" aria-expanded="${open}" aria-controls="dc-amore" aria-haspopup="true">${tr('Actions')}</button></span>`;""",
    "plus": """return `<button type="button" class="iconbtn chplus" data-chmore aria-expanded="false" title="${l}" aria-label="${l}">${ic('plus')}</button><span class="chtools">${p.join('')}</span>`;""",
    "list": """const p = openPop(a, `<div class="menu-list tvexp"><a href="/api/time/export.csv?${esc(q)}" download>${ic('download', 's')} CSV</a></div>`);""",
    "list2": """const p = openPop(a, `<div class="menu-list runlist">${it.map(row).join('<hr>')}</div>`);""",
}
for name, src in RED.items():
    check(kinds(src), f"red: a hand-built menu ({name})")
check("role" in kinds(RED["role"]) and "dots" in kinds(RED["role"]), "the budget dots: both its role=menu and its fold-out")
check(kinds(RED["toggle"]) == ["toggle"] and kinds(RED["plus"]) == ["toggle"], "the Actions button and the chat plus are toggles")
check(kinds(RED["list"]) == ["list"], "the Export list in openPop")

# 3. green: no menu
GREEN = {
    "selector": "const b = p?.querySelector(`[role=\"menuitem\"][data-i=\"${i + 1}\"]`);",
    "listbox": "openPop(el, `<div class=\"menu-list\" role=\"listbox\" aria-label=\"x\">${body}</div>`);",
    "filter": "const p = openPop(anchor, `<div class=\"menu-list tvlm\"><label><input type=\"checkbox\" data-l=\"all\"> ${tr('All projects')}</label></div>`);",
    "fold": "`<button class=\"sgt\" data-act=\"side-group\" aria-expanded=\"${open}\">${ic('chev', 's fcar')}<span>x</span></button>`",
    "search": "`<button type=\"button\" class=\"iconbtn msbtn\" data-act=\"ms-toggle\" aria-expanded=\"false\">${ic('search')}</button>`",
    "section": "`<details class=\"shelp sdet\"><summary>${tr('How to set it up')}</summary><ol class=\"slist\"></ol></details>`",
    "menu()": "menu(b, [{label: tr('Export'), icon: 'download', fn: () => go()}, '-', {label: tr('Delete'), fn: del}]);",
    "opener": "`<button type=\"button\" class=\"iconbtn\" data-act=\"more\" aria-haspopup=\"menu\" title=\"More\">${ic('dots')}</button>`",
}
for name, src in GREEN.items():
    check(kinds(src) == [], f"green: no menu ({name}): {kinds(src)}")

# 4. the exception on the same line, with a reason
ok = """`${''/* menu-ok: unfolds the per-project switches in place */}<button class="iconbtn cvxfold" aria-expanded="${st.lists}">${ic('dots')}</button>`"""
check(kinds(ok) == [], f"menu-ok with a reason: no finding: {kinds(ok)}")
check(kinds(ok.replace(" unfolds the per-project switches in place", "")) == ["toggle"], "menu-ok without a reason: still red")
check(kinds("// menu-ok: a reason on another line\n" + RED["plus"]) == ["toggle"], "menu-ok on another line: still red")

# 5. popovers.js is the shared menu
pop = os.path.join(ROOT, "static", "js", "popovers.js")
check(check_menu_own.scan("static/js/popovers.js", open(pop, encoding="utf-8").read()), "popovers.js does draw role=menu (the scan sees it)")
check(check_menu_own.hits([pop]) == [], "but popovers.js is never a finding")

sys.exit(done("p5693_menu_own_lint"))
