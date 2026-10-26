#!/usr/bin/env bash
# Register Kalmido's git merge drivers in this clone (2.320, #1368). Worktrees share the clone's config, so once per clone.
#   static/i18n/<code>.json  merged by key (tools/i18n_merge.py): two packages that add different texts never conflict
#   static/sw.js             precache lists rebuilt from index.html + lazyload.js when only they conflict (tools/sw_lists.py)
#   tests/skip.txt, tests/selfstart.txt   line union (git's own driver, .gitattributes)
set -euo pipefail
cd "$(dirname "$(realpath "$0")")/.."
git config merge.i18n.name "Kalmido translations by key"
git config merge.i18n.driver "python3 tools/i18n_merge.py %O %A %B"
git config merge.swlists.name "Kalmido sw.js precache lists"
git config merge.swlists.driver "python3 tools/sw_lists.py %O %A %B"
echo "git merge drivers registered in $(git rev-parse --show-toplevel)"
