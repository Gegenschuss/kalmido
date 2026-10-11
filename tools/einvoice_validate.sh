#!/usr/bin/env bash
# 2.38.0 (#1021 P5): validates the e-invoice files Kalmido writes -- PDF/A-3b with veraPDF and the CII XML (EN 16931 /
# XRechnung) with the KoSIT validator. Runs in CI (job "E-invoice validators") and locally:
#   tools/einvoice_validate.sh tests/.data/einvoice/*.pdf tests/.data/einvoice/*.xml
# PDFs go to veraPDF (the Docker image ghcr.io/verapdf/cli, profile 3b); XML files go to the KoSIT validator (Java 17+,
# the release jar + the XRechnung scenario configuration, both downloaded once with their SHA-256 checked into
# $KALMIDO_VALIDATOR_CACHE, default ~/.cache/kalmido-validators). Exit 1 when any file fails, 2 on setup problems.
# The KoSIT reports (HTML) are written next to the cache in reports/.
set -u
CACHE=${KALMIDO_VALIDATOR_CACHE:-$HOME/.cache/kalmido-validators}
VERAPDF_IMAGE=${VERAPDF_IMAGE:-ghcr.io/verapdf/cli:latest}
KOSIT_VERSION=1.6.3
KOSIT_JAR_URL="https://github.com/itplr-kosit/validator/releases/download/v${KOSIT_VERSION}/validator-${KOSIT_VERSION}-standalone.jar"
KOSIT_JAR_SHA=799e64befca97d4080e03608c80b85dd5a5ecc5f4ae4f35d1116ec2855b9a7c9
XR_CONF_VERSION=2026-08-31
XR_CONF_URL="https://github.com/itplr-kosit/validator-configuration-xrechnung/releases/download/v${XR_CONF_VERSION}/xrechnung-3.0.2-validator-configuration-${XR_CONF_VERSION}.zip"
XR_CONF_SHA=2530cd107c414511c5d0462ec10f886910395abfca820db82e83d70bf01221a8
mkdir -p "$CACHE/reports"
pdfs=(); xmls=()
for f in "$@"; do
  case "$f" in *.pdf) pdfs+=("$f");; *.xml) xmls+=("$f");; *) echo "skipped (not .pdf / .xml): $f";; esac
done
[[ ${#pdfs[@]} -eq 0 && ${#xmls[@]} -eq 0 ]] && { echo "usage: einvoice_validate.sh <file.pdf|file.xml>..."; exit 2; }
rc=0

fetch() {  # fetch <url> <file> <sha256>
  if [[ ! -s "$2" ]] || ! echo "$3  $2" | sha256sum -c --quiet - 2>/dev/null; then
    echo "downloading $(basename "$2")"
    curl -fsSL --retry 3 -o "$2.part" "$1" || { echo "download failed: $1"; return 1; }
    echo "$3  $2.part" | sha256sum -c --quiet - || { echo "checksum mismatch: $2"; rm -f "$2.part"; return 1; }
    mv "$2.part" "$2"
  fi
}

if [[ ${#pdfs[@]} -gt 0 ]]; then
  command -v docker >/dev/null || { echo "veraPDF needs docker"; exit 2; }
  abs=(); vols=()
  for f in "${pdfs[@]}"; do
    d=$(cd "$(dirname "$f")" && pwd); b=$(basename "$f")
    vols+=(-v "$d:/data/$(echo "$d" | md5sum | cut -c1-8):ro"); abs+=("/data/$(echo "$d" | md5sum | cut -c1-8)/$b")
  done
  echo "== veraPDF (PDF/A-3b): ${pdfs[*]}"
  out=$(docker run --rm "${vols[@]}" "$VERAPDF_IMAGE" -f 3b --format text "${abs[@]}" 2>&1)
  echo "$out" | grep -E "^(PASS|FAIL)" || echo "$out" | tail -20
  if echo "$out" | grep -q "^FAIL" || ! echo "$out" | grep -q "^PASS"; then
    echo "$out" | grep -vE "^PASS" | tail -40; rc=1
  fi
fi

if [[ ${#xmls[@]} -gt 0 ]]; then
  command -v java >/dev/null || { echo "the KoSIT validator needs java 17+"; exit 2; }
  fetch "$KOSIT_JAR_URL" "$CACHE/validator-${KOSIT_VERSION}-standalone.jar" "$KOSIT_JAR_SHA" || exit 2
  fetch "$XR_CONF_URL" "$CACHE/xrechnung-conf-${XR_CONF_VERSION}.zip" "$XR_CONF_SHA" || exit 2
  conf="$CACHE/xrechnung-conf-${XR_CONF_VERSION}"
  if [[ ! -f "$conf/scenarios.xml" ]]; then
    rm -rf "$conf"; mkdir -p "$conf"
    (cd "$conf" && unzip -q "$CACHE/xrechnung-conf-${XR_CONF_VERSION}.zip") || { echo "unzip failed"; exit 2; }
  fi
  echo "== KoSIT validator ${KOSIT_VERSION} + XRechnung configuration ${XR_CONF_VERSION}: ${xmls[*]}"
  rep="$CACHE/reports"; rm -f "$rep"/*
  java -jar "$CACHE/validator-${KOSIT_VERSION}-standalone.jar" -s "$conf/scenarios.xml" -r "$conf" -h -o "$rep" "${xmls[@]}" 2>&1 | grep -vE "^\s*$" | tail -40
  for f in "${xmls[@]}"; do
    b=$(basename "$f" .xml); r="$rep/$b-report.xml"
    if [[ ! -f "$r" ]]; then echo "FAIL $f: no report"; rc=1; continue; fi
    if grep -q 'rep:assessment' "$r" && grep -q '<rep:accept' "$r" && ! grep -q '<rep:reject' "$r"; then
      echo "PASS $f ($(grep -o 'valid="[a-z]*"' "$r" | head -1))"
    else
      echo "FAIL $f"; grep -oE '<s:(text|message)[^>]*>[^<]*' "$r" | sed 's/<[^>]*>/  /' | head -20
      grep -oE 'rep:message[^>]*>[^<]*' "$r" | head -20
      rc=1
    fi
  done
fi
exit $rc
