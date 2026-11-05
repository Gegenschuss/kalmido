#!/usr/bin/env bash
# 2.554.0 (#4052): builds static/vendor/codemirror/codemirror.min.js -- CodeMirror 6 (MIT) for the knowledge page editor
# (static/js/wkcm.js), bundled ONCE here and shipped as a plain file: the app never runs npm and never loads from a CDN.
#   tools/build_codemirror.sh            build in a fresh temporary folder, copy bundle + LICENSE, print the checksums
# Input: tools/codemirror/entry.js (what the editor uses, as the global "CM6"), package.json + package-lock.json (exact
# versions with their npm "integrity"; npm ci refuses a tarball that does not match). Install scripts never run.
# Update: change the versions in tools/codemirror/package.json, run `npm install --ignore-scripts` there once to renew the
# lock file (or edit it by hand), then this script; update static/vendor/codemirror/README and THIRD_PARTY_NOTICES.md.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
src="$root/tools/codemirror" out="$root/static/vendor/codemirror"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
cp "$src/package.json" "$src/package-lock.json" "$src/entry.js" "$work/"
cd "$work"
npm ci --ignore-scripts --no-audit --no-fund >/dev/null
npx --no-install esbuild entry.js --bundle --minify --format=iife --global-name=CM6 --legal-comments=eof \
  --target=es2020 --outfile="$work/codemirror.min.js" --log-level=warning
# one LICENSE with the text of every package that is inside the bundle (all MIT)
pkgs="$(node -e '
const lock = require("./package-lock.json").packages, out = [];
for (const [k, v] of Object.entries(lock)) if (k && !v.dev) out.push(k.replace(/^node_modules\//, "") + "@" + v.version);
console.log(out.sort().join("\n"));')"
{
  echo "CodeMirror 6 and the packages bundled with it into codemirror.min.js. Every one is under the MIT License."
  while read -r p; do
    n="${p%@*}"
    echo; echo "==== $p ===="; echo
    cat "node_modules/$n/LICENSE"*
  done <<< "$pkgs"
} > "$work/LICENSE"
mkdir -p "$out"
cp "$work/codemirror.min.js" "$work/LICENSE" "$out/"
echo "packages:"; sed 's/^/  /' <<< "$pkgs"
cd "$out" && sha256sum codemirror.min.js LICENSE
