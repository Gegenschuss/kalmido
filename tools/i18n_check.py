#!/usr/bin/env python3
"""Checks the translation files in static/i18n/ against the strings used in the code.

English is the source language: every tr("..."), trn("one", "other", n), N_("...") and Nn_("one", "other") call in
the web client (static/js/*.js) and the server (app.py + kalmido/) uses its literal English text as the key. For every static/i18n/<code>.json
this reports
  - missing keys            (used in the code, not translated)          -> error
  - placeholder mismatches  ({0} in the key but not in the translation) -> error
  - plural shape errors     (trn key needs [one, other], tr key a string) -> error
  - _meta / name / date format problems                                  -> error
  - unused keys             (in the file, no longer used by the code)   -> warning
Non-literal calls such as tr(name) are listed as info: their argument must be a key that is marked
with N_("...") somewhere (tables), otherwise the checker cannot see it.

usage: python3 tools/i18n_check.py [code ...]      exit code 1 on errors
"""
import glob
import importlib.util
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 2.191.0 A (#1410 #2518): one reader of the keys for this checker and the server (it splits the language files per module):
# kalmido/core/i18nkeys.py, loaded by its path (standard library only, no app import)
_spec = importlib.util.spec_from_file_location("i18nkeys", os.path.join(ROOT, "kalmido", "core", "i18nkeys.py"))
KEYS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(KEYS)
# 2.20.0 (#646): the client in static/js/, the server in the package kalmido/
SOURCES = KEYS.key_sources(ROOT)
I18N_DIR = os.path.join(ROOT, "static", "i18n")
PH = re.compile(r"\{(\d+)\}")
DATE_TOKENS = {"wd", "wdl", "d", "dd", "mm", "mon", "month", "y"}
DATE_KINDS = {"near", "short", "year", "long"}
ARRAYS = {"_weekdays": 7, "_weekdays_short": 7, "_months": 12, "_months_short": 12}
read_string, skip_ws, comment_line = KEYS.key_literal, KEYS.skip_ws, KEYS.comment_line


def extract():
    """-> keys {key: (kind, other, where)}, dynamic [where], errors [str]"""
    keys, dynamic, errors = {}, [], []
    for rel in SOURCES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        py = rel.endswith(".py")
        for fn, key, other, pos in KEYS.key_calls(src, py):
            where = f"{rel}:{src.count(chr(10), 0, pos) + 1}"
            if key is None:
                dynamic.append(f"{where}  {src[pos:pos + 60].splitlines()[0]}")
                continue
            kind = "s"
            if fn in ("trn", "Nn_"):  # Nn_("one", "other"): a plural text translated later with trn
                if other is None:
                    errors.append(f"{where}: {fn}() needs two literal strings (one, other)")
                    continue
                kind = "p"
            prev = keys.get(key)
            if prev and prev[0] != kind:
                errors.append(f"{where}: key {key!r} used both with tr() and trn() (see {prev[2]})")
            elif prev and kind == "p" and prev[1] != other:
                errors.append(f"{where}: plural key {key!r} has two different 'other' forms (see {prev[2]})")
            keys.setdefault(key, (kind, other, where))
    return keys, dynamic, errors


def placeholders(s):
    return set(PH.findall(s))


def check_meta(d):
    errs = []
    meta = d.get("_meta")
    if not isinstance(meta, dict) or not meta.get("name") or not meta.get("locale"):
        errs.append('_meta needs "name" (shown in the language selector) and "locale" (e.g. "de-DE")')
    for k, n in ARRAYS.items():
        v = d.get(k)
        if v is not None and not (isinstance(v, list) and len(v) == n and all(isinstance(x, str) and x for x in v)):
            errs.append(f"{k} must be a list of {n} non-empty strings")
        if v is None:
            errs.append(f"{k} missing (English names would be shown)")
    fm = d.get("_date_formats")
    if fm is not None:
        if not isinstance(fm, dict):
            errs.append("_date_formats must be an object")
        else:
            for kind, p in fm.items():
                if kind not in DATE_KINDS:
                    errs.append(f"_date_formats: unknown format {kind!r} (known: {', '.join(sorted(DATE_KINDS))})")
                for t in re.findall(r"\{(\w+)\}", str(p)):
                    if t not in DATE_TOKENS:
                        errs.append(f"_date_formats.{kind}: unknown token {{{t}}}")
    return errs


def split_check():
    """-> ({key: module}, modules, errors): the modules of lazyload.js exist, no key of a start script or the server is in a part."""
    errs = []
    mod_of, mods = KEYS.module_keys(ROOT)
    if not mods:
        errs.append("static/js/lazyload.js: no modules read from LD_MODS")
    for m, fs in mods.items():
        for f in fs:
            if not os.path.isfile(os.path.join(ROOT, "static", "js", f + ".js")):
                errs.append(f"LD_MODS {m}: static/js/{f}.js does not exist")
    start = re.findall(r'<script src="/static/js/([\w-]+\.js)"', open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read())
    for rel in [os.path.join("static", "js", f) for f in start] + [r for r in SOURCES if r.endswith(".py")]:
        src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        for _, key, _, _ in KEYS.key_calls(src, rel.endswith(".py")):
            if key in mod_of:
                errs.append(f"split: {key!r} of {rel} is in the part of the module {mod_of[key]}, not in the core")
    return mod_of, mods, errs


def main(argv):
    keys, dynamic, errors = extract()
    ok = not errors
    print(f"code: {len(keys)} keys ({sum(1 for v in keys.values() if v[0] == 'p')} plural) in {len(SOURCES)} files (static/js/, app.py, kalmido/)")
    for e in errors:
        print("  ERROR", e)
    if dynamic:
        print(f"  info: {len(dynamic)} non-literal call(s); their keys must be marked with N_(...):")
        for d in dynamic:
            print("   ", d)
    # 2.191.0 A (#1410 #2518): the web client loads the core texts at start and the texts of a module loaded on demand with the
    # module (kalmido/core/i18nparts.py): the split must read the modules and keep every key of the start and the server
    mod_of, mods, split_errs = split_check()
    print(f"split: {len(mod_of)} keys in the parts of {len(set(mod_of.values()))} of {len(mods)} modules loaded on demand, the rest in the core")
    for e in split_errs:
        print("  ERROR", e)
    ok = ok and not split_errs
    files = sorted(glob.glob(os.path.join(I18N_DIR, "*.json")))
    if argv:
        files = [f for f in files if os.path.basename(f)[:-5] in argv]
    for fn in files:
        name = os.path.basename(fn)
        try:
            d = json.load(open(fn, encoding="utf-8"))
        except ValueError as e:
            print(f"\n{name}: invalid JSON: {e}")
            ok = False
            continue
        errs, warns = check_meta(d), []
        core, parts = KEYS.split_lang(d, mod_of)
        if sum(len(p) for p in parts.values()) + len(core) - 1 != len(d) or any(mod_of.get(k) != m for m, p in parts.items() for k in p):
            errs.append("split: the core and the module parts do not add up to the file")
        tkeys = {k: v for k, v in d.items() if not k.startswith("_")}
        missing = [k for k in keys if k not in tkeys]
        for k, v in tkeys.items():
            if k not in keys:
                warns.append(f"unused key {k!r}")
                continue
            kind = keys[k][0]
            if kind == "s":
                if not isinstance(v, str):
                    errs.append(f"{k!r}: must be a string (tr key), got {type(v).__name__}")
                elif placeholders(k) != placeholders(v):
                    errs.append(f"{k!r}: placeholders {sorted(placeholders(k))} vs translation {sorted(placeholders(v))}")
            else:
                if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) for x in v)):
                    errs.append(f"{k!r}: plural key (trn) needs [one, other]")
                    continue
                want = placeholders(k) | placeholders(keys[k][1])
                got = placeholders(v[0]) | placeholders(v[1])
                extra = [x for x in v if not placeholders(x) <= want]
                if got != want or extra:
                    errs.append(f"{k!r}: placeholders {sorted(want)} vs translation {sorted(got)}")
        done = len(keys) - len(missing)
        print(f"\n{name} ({(d.get('_meta') or {}).get('name', '?')}): {done}/{len(keys)} keys translated "
              f"({100 * done / max(len(keys), 1):.0f}%), {len(missing)} missing, {len(errs)} error(s), {len(warns)} unused")
        for k in missing:
            print(f"  MISSING {k!r}  ({keys[k][2]})")
        for e in errs:
            print("  ERROR", e)
        for w in warns:
            print("  warn", w)
        ok = ok and not missing and not errs
    if not files:
        print("\nno translation files in static/i18n/")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
