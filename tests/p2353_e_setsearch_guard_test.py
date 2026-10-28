#!/usr/bin/env python3
# kalmido-suite: after=p2353_e_setsearch_ui nodata
# 2.353.0 E (#2775) guard: every settings window of an area has an entry in the directory of the settings search
# (SS_AREA in static/js/settings.js), so the search "Search settings" finds it. Static, no server.
# A settings window of an area is drawn by a function named *_settings / *Settings / *_settingsHtml / *SettingsHtml /
# *_sDraw (the convention of docs.js, office*.js). A new window without an entry in SS_AREA (its `src` list) = red;
# an entry naming a function that does not exist any more = red. Windows that are not area-wide (one chat room, a
# saver, a link into the main settings) stand in EXEMPT with the reason.
# freelancer-matrix: n/a (static; the person without an organisation runs in p2353_e_setsearch_ui.js)
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
JS = [os.path.join(ROOT, 'static', 'js', f) for f in sorted(os.listdir(os.path.join(ROOT, 'static', 'js'))) if f.endswith('.js')]
EXEMPT = {
    'tcx_settings': 'the settings of ONE chat room (members, name), opened from the room',
    'ofcSaveSettings': 'saves the office settings form, draws nothing',
    'pl_openSettings': 'opens Settings > Integrations (the main settings dialog, searched anyway)',
}
NAME = r'[A-Za-z_$][\w$]*?(?:_settings|Settings|_settingsHtml|SettingsHtml|_sDraw)'
DEF = re.compile(r'(?:function\s+(' + NAME + r')\s*\(|(?:const|let)\s+(' + NAME + r')\s*=\s*(?:async\s*)?\()')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kt import check, done  # noqa: E402

src = {f: open(f, encoding='utf-8').read() for f in JS}
found = {}
for f, s in src.items():
    for m in DEF.finditer(s):
        n = m.group(1) or m.group(2)
        if n == 'settingsModal' or os.path.basename(f) == 'settings.js':
            continue  # the main settings dialog itself (its panes are searched in place)
        found[n] = os.path.basename(f)
check(len(found) >= 10, 'the scan finds the area settings windows (%d)' % len(found))

st = src[os.path.join(ROOT, 'static', 'js', 'settings.js')]
i, j = st.find('const SS_AREA = ['), st.find('function ss_areaHits(')
check(i > 0 and j > i, 'SS_AREA and ss_areaHits are in settings.js')
block = st[i:j]
listed = set()
for m in re.finditer(r"src:\s*\[([^\]]*)\]", block):
    listed |= set(re.findall(r"'([^']+)'", m.group(1)))
check(len(re.findall(r"\{src:", block)) >= 3, 'the directory has the documents, the office and the bookkeeping windows')

for n, f in sorted(found.items()):
    check(n in listed or n in EXEMPT, f'{n} ({f}) draws an area settings window but has no entry in SS_AREA (static/js/settings.js): '
          'add {src: [...], area, name, words, on, open, root, secs} so the settings search finds it')
alldefs = '\n'.join(src.values())
for n in sorted(listed | set(EXEMPT)):
    check(re.search(r'(?:function\s+|(?:const|let)\s+)' + re.escape(n) + r'\b', alldefs), f'{n} is named in SS_AREA / EXEMPT but defined nowhere (stale entry)')
# every entry: an area, a name, a gate, an opener, a root and at least one section
for m in re.finditer(r"\{src:", block):
    e = block[m.start():m.start() + 4000]
    nxt = e.find('{src:', 5)
    e = e[:nxt] if nxt > 0 else e
    for k in ('area:', 'name:', 'words:', 'on:', 'open:', 'root:', 'secs:'):
        check(k in e, f'an SS_AREA entry lacks {k}: {e[:80]}')

print(f'{len(found)} windows checked')
sys.exit(done('p2353_e_setsearch_guard'))
