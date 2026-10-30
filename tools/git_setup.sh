#!/usr/bin/env bash
# Register Kalmido's git merge drivers in this clone (2.320, #1368). Worktrees share the clone's config, so once per clone.
#   static/i18n/<code>.json  merged by key (tools/i18n_merge.py): two packages that add different texts never conflict
#   static/sw.js             precache lists rebuilt from index.html + lazyload.js when only they conflict (tools/sw_lists.py)
#   tests/skip.txt, tests/selfstart.txt   line set merge (tools/lines_merge.py, 2.358.0 #3394: git's union brought deleted lines back)
set -euo pipefail
cd "$(dirname "$(realpath "$0")")/.."
git config merge.i18n.name "Kalmido translations by key"
git config merge.i18n.driver "python3 tools/i18n_merge.py %O %A %B"
git config merge.swlists.name "Kalmido sw.js precache lists"
git config merge.swlists.driver "python3 tools/sw_lists.py %O %A %B"
git config merge.lines.name "Kalmido line lists (deleted stays deleted)"
# a tree without tools/lines_merge.py yet (a branch from before 2.358.0): git's union as before
git config merge.lines.driver "python3 tools/lines_merge.py %O %A %B 2>/dev/null || git merge-file --union -q %A %O %B"
echo "git merge drivers registered in $(git rev-parse --show-toplevel)"
