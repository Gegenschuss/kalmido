#!/usr/bin/env python3
"""2.11.0 (#439): the translation files, no container. Every language in static/i18n/ (de, fr, es, it, nl) has 100 % of the
keys the code uses (tr / trn / N_ / Nn_ in static/app.js and app.py, read by tools/i18n_check.py), no unused keys, the same
placeholders ({0}, {1} ...) as the English key, plurals as [one, other] with the placeholders of both English forms, the same
HTML tags as the key, no empty texts, a complete _meta (name, locale; the machine-translated ones marked beta), 7 weekday
and 12 month names, date formats with known tokens only; the checker itself exits 0. Also: the server-side helpers that
pick the plural form (French: 0 and 1 are singular) and format numbers / short dates per language.
usage: i18n_test.py"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import i18n_check as ic  # noqa: E402

FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


PH = re.compile(r"\{(\d+)\}")
TAG = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")
ph = lambda s: set(PH.findall(s))  # noqa: E731
tags = lambda s: sorted({m.group(0).split()[0].rstrip(">") for m in TAG.finditer(s)})  # noqa: E731 (kinds of tags)

keys, dynamic, errors = ic.extract()
check(not errors, f"checker reads the code without errors: {errors[:3]}")
check(len(keys) > 3000, f"{len(keys)} keys in the code")
I18N = os.path.join(ROOT, "static", "i18n")
files = sorted(f[:-5] for f in os.listdir(I18N) if f.endswith(".json"))
check(set(files) >= {"de", "fr", "es", "it", "nl"}, f"languages: {files}")
BETA = {"fr", "es", "it", "nl"}
LOCALES = {"de": "de-DE", "fr": "fr-FR", "es": "es-ES", "it": "it-IT", "nl": "nl-NL"}
for code in files:
    d = json.load(open(os.path.join(I18N, code + ".json"), encoding="utf-8"))
    tk = {k: v for k, v in d.items() if not k.startswith("_")}
    missing = [k for k in keys if k not in tk]
    unused = [k for k in tk if k not in keys]
    check(not missing, f"{code}: 100 % of the keys ({len(missing)} missing, e.g. {missing[:2]})")
    check(not unused, f"{code}: no unused keys ({unused[:2]})")
    bad_ph, bad_pl, bad_tag, empty = [], [], [], []
    for k, (kind, other, _) in keys.items():
        v = tk.get(k)
        if v is None:
            continue
        if kind == "p":
            if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) and x.strip() for x in v)):
                bad_pl.append(k)
                continue
            want = ph(k) | ph(other)
            if (ph(v[0]) | ph(v[1])) != want or any(not ph(x) <= want for x in v):
                bad_ph.append(k)
        else:
            if not isinstance(v, str):
                bad_pl.append(k)
                continue
            if not v.strip() and k.strip():
                empty.append(k)
            if ph(v) != ph(k):
                bad_ph.append(k)
            if tags(v) != tags(k):
                bad_tag.append(k)
    check(not bad_ph, f"{code}: placeholders match ({bad_ph[:3]})")
    check(not bad_pl, f"{code}: plural / string shape ({bad_pl[:3]})")
    check(not bad_tag, f"{code}: HTML tags kept ({bad_tag[:3]})")
    check(not empty, f"{code}: no empty texts ({empty[:3]})")
    m = d.get("_meta") or {}
    check(m.get("name") and m.get("locale") == LOCALES.get(code, m.get("locale")), f"{code}: _meta name + locale ({m})")
    check(bool(m.get("beta")) == (code in BETA), f"{code}: beta mark {'set' if code in BETA else 'not set'}")
    check(not ic.check_meta(d), f"{code}: names and date formats valid ({ic.check_meta(d)[:2]})")
    check(len(set(d["_weekdays"])) == 7 and len(set(d["_months"])) == 12, f"{code}: distinct weekday and month names")
    # nothing left in English by accident: the long texts (> 40 characters, no code) differ from their key
    same = [k for k, v in tk.items() if isinstance(v, str) and v == k and len(k) > 40 and not re.search(r"[/_.]\w|\{0\}|<", k)]
    check(code == "en" or len(same) <= 3, f"{code}: long texts are translated ({len(same)} identical, e.g. {same[:2]})")

cp = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "i18n_check.py")], capture_output=True, text=True, timeout=120)
check(cp.returncode == 0 and " 0 unused" in cp.stdout and "MISSING" not in cp.stdout, f"tools/i18n_check.py exit 0: {cp.stdout[-300:]}")

# server helpers: the functions are taken from the server code itself (kalmido/core/i18n.py, ast) and run with the language files, without the app's
# packages or a database
import ast  # noqa: E402
from datetime import date  # noqa: E402
src = open(os.path.join(ROOT, "kalmido", "core", "i18n.py"), encoding="utf-8").read()  # 2.20.0: the package
want = {"lg_base", "dec_comma", "fmt_int", "short_day", "plural_one", "languages", "COMMA_LANGS"}
nodes = [n for n in ast.parse(src).body if (isinstance(n, ast.FunctionDef) and n.name in want)
         or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in want for t in n.targets))]
check(len(nodes) == len(want), f"helpers found in kalmido/core/i18n.py: {[getattr(n, 'name', None) for n in nodes]}")
LANGS = {"en": {"_meta": {"name": "English", "locale": "en-GB"}}}
for code in files:
    LANGS[code] = json.load(open(os.path.join(I18N, code + ".json"), encoding="utf-8"))
ns = {"LANGS": LANGS, "lang": lambda: "en"}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "kalmido/core/i18n.py", "exec"), ns)  # noqa: S102 (our own source)
langs = ns["languages"]()
check({x["code"] for x in langs if x["beta"]} == BETA and {x["code"] for x in langs} >= {"en", "de"} | BETA, f"languages(): beta flags ({langs})")
check(ns["plural_one"](0, "fr") and not ns["plural_one"](0, "de") and not ns["plural_one"](0, "en") and ns["plural_one"](1, "nl")
      and not ns["plural_one"](2, "fr"), "plural_one: fr 0 and 1, the others only 1")
d = date(2026, 10, 3)
sd = ns["short_day"]
got = [sd(d, x) for x in ("de", "en", "fr", "es", "it", "nl")]
check(got == ["03.10.", "03 Oct", "3 oct.", "3 oct", "3 ott", "3 okt"] and sd(d, "it", year=True) == "3 ott 2026", f"short dates per language: {got}")
fi = ns["fmt_int"]
check(fi(1234567, "en") == "1,234,567" and fi(1234567, "de") == "1.234.567" and fi(1234567, "fr") == "1\u202f234\u202f567"
      and fi(1234567, "nl") == "1.234.567", "thousands separators")
check(all(ns["dec_comma"](x) for x in ("de", "fr", "es", "it", "nl")) and not ns["dec_comma"]("en"), "decimal comma (CSV ';') languages")
print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
