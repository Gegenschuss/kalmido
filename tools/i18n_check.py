#!/usr/bin/env python3
"""Checks the translation files in static/i18n/ against the strings used in the code.

English is the source language: every tr("..."), trn("one", "other", n), N_("...") and Nn_("one", "other") call in
the web client (static/js/*.js) and the server (app.py + kalmido/) uses its literal English text as the key. For every static/i18n/<code>.json
this reports
  - missing keys            (used in the code, not translated)          -> error
  - placeholder mismatches  ({0} in the key but not in the translation) -> error
  - plural shape errors     (trn key needs [one, other], tr key a string) -> error
  - _meta / name / date format problems                                  -> error
  - a key with a word the glossary of TRANSLATING.md replaces            -> error
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
# 2.368.4 (#2990): the glossary of TRANSLATING.md: one English word for one thing (en-GB). A variant in a key of the code is an
# error, the part after | is a context, not text. |pack keys are the wording of the office packs (kalmido/office/packs/).
GLOSSARY = ((r"\b[Cc]ustomers?\b", "client"), (r"\b[Ll]ogins?\b", "sign-in"), (r"\b[Ll]og(?:ged|ging|s)? in\b", "sign in"),
            (r"\b[Ll]og(?:ged|s)? out\b|\b[Ll]ogout\b", "sign out"), (r"\b[Cc]olor", "colour"),
            (r"\b(?:[Cc]ustom|[Oo]rgan|[Rr]ecogn|[Ss]ummar)iz", "-ise"), (r"\b[Ii]nquir", "enquiry"), (r"\b[Vv]acations?\b", "holiday"),
            (r"(?<![-@\w.])[Mm]ails?\b(?!-)", "e-mail"), (r"\b[Ee]mails?\b", "e-mail"), (r"\b[Qq]uotes?\b", "quotation"),
            (r"\bNobody assigned\b", "unassigned"),
            # 2.542.0 (#4605): the own workspace is "Private" and nothing else; "personal" only for what belongs to a person
            (r"\b[Mm]y files\b", "Private|workspace"), (r"\b[Pp]ersonal (?:office|workspace|area|space)\b", "private office / private workspace"),
            (r"\b[Mm]y (?:workspace|area|space|office)\b", "Private|workspace"), (r"\bMake personal\b", "Move to Private"),
            # 2.622.0 (#3894): the rest of the wording review #2991 (a person taking over a project keeps "take over", so no rule)
            (r"\bfor good\b", "permanently"), (r"\b[Tt]urn(?:s|ed|ing)?(?: (?:it|them))?(?: back)? (?:on|off)\b", "switch on / off"),
            (r"\b[Vv]iew[- ]only\b|\b[Rr]ead only\b", "read-only"), (r"\b[Dd]ecline[ds]?\b", "reject"),
            (r"\b[Aa]n own\b", "your own / a separate"), (r"\b[Tt]ak(?:e|es|en|ing) back\b|\btook back\b", "undo"),
            (r"\b[Aa]ctual state\b", "current status"), (r"\bTo the sign-in\b", "Go to sign-in"), (r"\bFurther people\b", "Other people"),
            (r"\b[Pp]ick\b(?! up)", "select"),
            (r"\b[Cc]hoose\b(?! (?:(?:a |your |your own |a new |their )?pass(?:word|phrase)|what happens|otherwise|whether|for every))", "select"),
            (r"\bSmall business(?:, no VAT| \(no VAT\))", "Small business: no VAT"))
GLOSSARY_KEEP = frozenset((
    "holiday vacation sick leave day off away absence",  # search words
    "Registered mail",  # the postal service
))


def glossary_errors(keys):
    """(#2990) "key: <word> instead of <glossary word>" for every key of the code that uses a variant."""
    out = []
    for k in keys:
        text = k.split("|")[0] if not k.startswith("|") else k
        if k in GLOSSARY_KEEP or k.endswith("|pack") or "Login with URL" in k:
            continue
        for rx, want in GLOSSARY:
            m = re.search(rx, text)
            if m:
                out.append(f"{k!r}: “{m.group(0)}”, the glossary says “{want}” (TRANSLATING.md)")
    return out


# 2.542.0 (#4605): the same rule for the translations: a third name of the own workspace is refused in the German values
PRIVATE_VARIANTS = ((r"\bMeine Ablage\b|\bMein Bereich\b|\bMein Arbeitsbereich\b", "Privat"),
                    (r"\bpersönliche[nsm]? Büro\b|\bPersönliche[nsm]? Büro\b", "privates Büro"))


def private_term_errors(d, name=""):
    """(#4605) "name: key: <variant>, say <wanted>" for a German value that names the own workspace with a third name."""
    out = []
    if not name.startswith("de"):
        return out
    for k, v in d.items():
        for x in (v if isinstance(v, list) else [v]):
            if not isinstance(x, str) or k.startswith("_"):
                continue
            for rx, want in PRIVATE_VARIANTS:
                m = re.search(rx, x)
                if m:
                    out.append(f"{name}: {k[:60]!r}: “{m.group(0)}”, say “{want}” (Private, #4605)")
    return out


# 2.727.0 (#5197): "Freigabe" is the approval only; sharing is "Teilen", "geteilt mit" or "Zugriff" (a key about approval is exempt)
def share_term_errors(d, name=""):
    """(#5197) "name: key: Freigabe in a text about sharing" for a German value."""
    out = []
    if not name.startswith("de"):
        return out
    for k, v in d.items():
        if k.startswith("_") or re.search(r"approv", k, re.I) or not re.search(r"\bshar(?:e|es|ed|ing)\b", k, re.I):
            continue
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, str) and "Freigabe" in x:
                out.append(f"{name}: {k[:60]!r}: “Freigabe” in a text about sharing, say Teilen / geteilt mit / Zugriff (#5197)")
    return out


def extract():
    """-> keys {key: (kind, other, where)}, dynamic [where], errors [str]"""
    keys, dynamic, errors = {}, [], []
    for rel in SOURCES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        py = rel.endswith(".py")
        bad = []  # 2.191.0 F2 (#2518): a literal the key reader cannot read (the server's split treats it as dynamic)
        for fn, key, other, pos in KEYS.key_calls(src, py, bad):
            where = f"{rel}:{src.count(chr(10), 0, pos) + 1}"
            if bad and bad[-1][0] == pos:
                errors.append(f"{where}: {fn}() with a string the key reader cannot read ({bad[-1][1]})")
                continue
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
    for key, where in KEYS.reason_keys(ROOT).items():  # 2.464.0 (#3841)
        keys.setdefault(key, ("s", None, where))
    for key in sorted(KEYS.data_keys(ROOT)):  # 2.461 (#3773): the holiday files
        keys.setdefault(key, ("s", None, "kalmido/office/packs/holidays/"))
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
    try:
        mod_of, mods = KEYS.module_keys(ROOT)
    except (OSError, ValueError) as e:  # 2.191.0 F2 (#2518): the server turns the split off then
        return {}, {}, [f"split: {e}"]
    for m, fs in mods.items():
        for f in fs:
            if not os.path.isfile(os.path.join(ROOT, "static", "js", f + ".js")):
                errs.append(f"LD_MODS {m}: static/js/{f}.js does not exist")
    start = re.findall(r'<script src="/static/js/([\w-]+\.js)"', open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read())
    for rel in [os.path.join("static", "js", f) for f in start] + [r for r in SOURCES if r.endswith(".py")]:
        src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        for _, key, _, _ in KEYS.key_calls(src, rel.endswith(".py")):
            if key in mod_of and not (rel.endswith(".py") and mod_of[key] == KEYS.PY_PART):  # 2.501.0 (#4198)
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
    for e in glossary_errors(keys):
        print("  ERROR", e)
        ok = False
    files = sorted(glob.glob(os.path.join(I18N_DIR, "*.json")))
    for fn in files:
        try:
            dj = json.load(open(fn, encoding="utf-8"))
            for e in private_term_errors(dj, os.path.basename(fn)) + share_term_errors(dj, os.path.basename(fn)):
                print("  ERROR", e)
                ok = False
        except ValueError:
            pass  # reported below
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
