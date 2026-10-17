#!/usr/bin/env python3
"""2.76.0 (#1023): builds the index of a pack catalogue (docs/PACKS.md) from a folder of pack files.

    SRC_DIR/country/<code>.json  or  <code>-<version>.json      country packs (format of kalmido/office/packs/*.json)
    SRC_DIR/industry/<code>.json or  <code>-<version>.json      industry packs (format of kalmido/office/packs/industry/*.json)
    SRC_DIR/<kind>/meta.json (optional)  {"<code>": {"name": {"de", "en"}, "description": {"de", "en"}, "author", "license",
                                          "homepage", "verified": true|false, "min_app": "2.76.0", "released": "YYYY-MM-DD",
                                          "changes": {"<version>": {"de", "en"}}}}

Every file is checked with the validators of the app (the same check an installation runs); a file that fails stops the
run (exit 1) with its problems on stderr. version, sha256 and size come from the file itself; the address of a file is
BASE_URL/<kind>/<file name>. The index goes to stdout.

usage: python3 tools/packs_catalog.py SRC_DIR BASE_URL [--name TEXT] [--updated YYYY-MM-DD] [--author TEXT]
                                      [--license SPDX] [--verified] [--min-app X.Y.Z] > index.json"""
import argparse
import datetime
import glob
import hashlib
import importlib.util
import json
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFICE = os.path.join(ROOT, "kalmido", "office")
_FILE_RE = re.compile(r"^(?P<code>[A-Za-z][A-Za-z0-9_]{1,30}?)(?:-(?P<v>\d{1,6}))?\.json$")


def _validators():
    """office_pack_validate + dk_pack_validate without loading the server (packs.py / sheet.py / calc.py use no server
    imports; they are loaded as a small stand-alone package)."""
    pkg = types.ModuleType("_kpk")
    pkg.__path__ = [OFFICE]
    sys.modules["_kpk"] = pkg
    out = {}
    for name in ("calc", "packs", "sheet"):
        spec = importlib.util.spec_from_file_location(f"_kpk.{name}", os.path.join(OFFICE, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"_kpk.{name}"] = mod
        spec.loader.exec_module(mod)
        out[name] = mod
    return {"country": out["packs"].office_pack_validate, "industry": out["sheet"].dk_pack_validate}


def _pair(v, fallback=""):
    if isinstance(v, str):
        return {"de": v, "en": v}
    if isinstance(v, dict):
        de, en = v.get("de") or v.get("en") or fallback, v.get("en") or v.get("de") or fallback
        return {"de": de, "en": en}
    return {"de": fallback, "en": fallback}


def build(src, base, args):
    check = _validators()
    base = base.rstrip("/")
    if not re.match(r"^https?://[^/\s]+", base):
        raise SystemExit("BASE_URL: an absolute http(s) address")
    packs, bad = [], []
    for kind in ("country", "industry"):
        d = os.path.join(src, kind)
        meta_p = os.path.join(d, "meta.json")
        meta = json.load(open(meta_p, encoding="utf-8")) if os.path.isfile(meta_p) else {}
        groups = {}
        for p in sorted(glob.glob(os.path.join(d, "*.json"))):
            fn = os.path.basename(p)
            if fn == "meta.json":
                continue
            m = _FILE_RE.match(fn)
            raw = open(p, "rb").read()
            try:
                pk = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                bad.append(f"{kind}/{fn}: not JSON ({e})")
                continue
            probs = check[kind](pk)
            code = pk.get("code") if isinstance(pk, dict) else None
            if not m or not isinstance(code, str) or m.group("code").lower() != code.lower():
                probs.append("file name: <code>.json or <code>-<version>.json with the code of the pack")
            elif m.group("v") and int(m.group("v")) != pk.get("version"):
                probs.append("file name: the version in the name differs from the pack's version")
            if len(raw) > 512 * 1024:
                probs.append("size: at most 512 KiB")
            if probs:
                bad += [f"{kind}/{fn}: {x}" for x in probs]
                continue
            groups.setdefault(code, []).append((pk, raw, fn))
        for code in sorted(groups):
            mt = meta.get(code) or {}
            vs = sorted(groups[code], key=lambda x: -x[0]["version"])
            if len({x[0]["version"] for x in vs}) != len(vs):
                bad.append(f"{kind}/{code}: the same version twice")
                continue
            top = vs[0][0]
            if kind == "country":
                name = _pair(mt.get("name") or {"de": top["name"], "en": top.get("name_en") or top["name"]})
            else:
                name = _pair(mt.get("name") or top["name"])
            changes = mt.get("changes") or {}
            e = {"kind": kind, "code": code, "name": name,
                 "description": _pair(mt.get("description"), ""), "author": mt.get("author") or args.author or "",
                 "license": mt.get("license") or args.license or "",
                 "verified": bool(mt.get("verified", args.verified)) and not top.get("community", False),
                 "versions": []}
            if mt.get("homepage"):
                e["homepage"] = mt["homepage"]
            for pk, raw, fn in vs:
                v = {"version": pk["version"], "url": f"{base}/{kind}/{fn}", "sha256": hashlib.sha256(raw).hexdigest(),
                     "size": len(raw), "released": mt.get("released") or args.updated,
                     "min_app": mt.get("min_app") or args.min_app}
                ch = changes.get(str(pk["version"]))
                if ch:
                    v["changes"] = _pair(ch)
                e["versions"].append(v)
            packs.append(e)
    if bad:
        print("\n".join(bad), file=sys.stderr)
        raise SystemExit(1)
    return {"format": 1, "name": args.name, "updated": args.updated, "packs": packs}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src")
    ap.add_argument("base_url")
    ap.add_argument("--name", default="Kalmido packs")
    ap.add_argument("--updated", default=datetime.date.today().isoformat())
    ap.add_argument("--author", default="")
    ap.add_argument("--license", default="")
    ap.add_argument("--verified", action="store_true", help="mark every pack as checked (not for community packs)")
    ap.add_argument("--min-app", default="2.76.0")
    args = ap.parse_args()
    idx = build(args.src, args.base_url, args)
    json.dump(idx, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
