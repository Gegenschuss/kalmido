#!/usr/bin/env python3
"""Checks the translation files in static/i18n/ against the strings used in the code.

English is the source language: every tr("..."), trn("one", "other", n), N_("...") and Nn_("one", "other") call in
static/app.js and app.py uses its literal English text as the key. For every static/i18n/<code>.json
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
import ast
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = ["static/app.js", "app.py"]
I18N_DIR = os.path.join(ROOT, "static", "i18n")
CALL = re.compile(r"(?<![\w.$])(trn|tr|Nn_|N_)\(")
PH = re.compile(r"\{(\d+)\}")
DATE_TOKENS = {"wd", "wdl", "d", "dd", "mm", "mon", "month", "y"}
DATE_KINDS = {"near", "short", "year", "long"}
ARRAYS = {"_weekdays": 7, "_weekdays_short": 7, "_months": 12, "_months_short": 12}


def read_string(src, i, py):
    """Parses a quoted string literal at src[i]; returns (value, end) or (None, i)."""
    q = src[i] if i < len(src) else ""
    if q not in "'\"" or not q:
        return None, i
    j = i + 1
    while j < len(src) and src[j] != q:
        j += 2 if src[j] == "\\" else 1
    lit = src[i:j + 1]
    if py:
        return ast.literal_eval(lit), j + 1
    body = lit[1:-1]
    if q == "'":
        body = body.replace("\\'", "'").replace('"', '\\"')
    return json.loads('"' + body + '"'), j + 1


def skip_ws(src, i):
    while i < len(src) and src[i] in " \t\r\n":
        i += 1
    return i


def comment_line(src, pos, py):
    line = src[src.rfind("\n", 0, pos) + 1:pos].lstrip()
    return line.startswith("#") if py else line.startswith(("//", "*", "/*"))


def extract():
    """-> keys {key: (kind, other, where)}, dynamic [where], errors [str]"""
    keys, dynamic, errors = {}, [], []
    for rel in SOURCES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        py = rel.endswith(".py")
        for m in CALL.finditer(src):
            before = src[max(0, m.start() - 9):m.start()]
            if before.endswith(("function ", "def ")) or comment_line(src, m.start(), py):
                continue
            fn, where = m.group(1), f"{rel}:{src.count(chr(10), 0, m.start()) + 1}"
            i = skip_ws(src, m.end())
            key, i = read_string(src, i, py)
            if key is None:
                dynamic.append(f"{where}  {src[m.start():m.start() + 60].splitlines()[0]}")
                continue
            kind, other = "s", None
            if fn in ("trn", "Nn_"):  # Nn_("one", "other"): a plural text translated later with trn
                i = skip_ws(src, i)
                if src[i:i + 1] == ",":
                    other, i = read_string(src, skip_ws(src, i + 1), py)
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


def main(argv):
    keys, dynamic, errors = extract()
    ok = not errors
    print(f"code: {len(keys)} keys ({sum(1 for v in keys.values() if v[0] == 'p')} plural) in {', '.join(SOURCES)}")
    for e in errors:
        print("  ERROR", e)
    if dynamic:
        print(f"  info: {len(dynamic)} non-literal call(s); their keys must be marked with N_(...):")
        for d in dynamic:
            print("   ", d)
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
